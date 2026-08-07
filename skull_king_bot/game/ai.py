"""AI 플레이어 로직 - 전략적 의사결정

AI는 손패 강도를 분석하여 비딩하고,
상황에 맞게 카드를 선택한다.
"""

from __future__ import annotations
import random
from typing import List, Optional, TYPE_CHECKING
from .enums import CardType, Suit, GameMode, PirateName, TigressChoice
from .cards import Card

if TYPE_CHECKING:
    from .player import Player
    from .trick import PlayedCard


# ── AI 이름 풀 ──────────────────────────────────────────

AI_NAMES = [
    "선장 봇",
    "해적 봇",
    "앵무새 봇",
    "문어 봇",
    "원숭이 봇",
]

_ai_name_index = 0

def get_next_ai_name() -> str:
    """순서대로 AI 이름을 반환한다."""
    global _ai_name_index
    name = AI_NAMES[_ai_name_index % len(AI_NAMES)]
    _ai_name_index += 1
    return name

def reset_ai_names():
    global _ai_name_index
    _ai_name_index = 0


# ── AI User (Discord User 모방) ──────────────────────────

class AIUser:
    """Discord User를 모방하는 AI 전용 유저 클래스.

    봇이 DM을 보내려 할 때 에러 없이 무시된다.
    """
    _next_id = 900_000_001

    def __init__(self, name: str):
        self.id = AIUser._next_id
        AIUser._next_id += 1
        self.display_name = f"🤖 {name}"
        self.name = name
        self.bot = True

    @property
    def mention(self) -> str:
        return f"**🤖 {self.name}**"

    async def send(self, *args, **kwargs):
        """DM 전송 → AI는 무시"""
        pass

    def __repr__(self) -> str:
        return f"AIUser({self.name}, id={self.id})"


# ── AI 전략 ──────────────────────────────────────────────

class AIStrategy:
    """AI 의사결정 전략 모음"""

    # ════════════════════════════════════════
    #  비딩
    # ════════════════════════════════════════

    @staticmethod
    def calculate_bid(hand: List[Card], round_number: int, mode: GameMode) -> int:
        """손패를 분석하여 비딩 값을 결정한다.

        각 카드의 '승리 확률'을 추정하여 합산한다.
        """
        score = 0.0

        for card in hand:
            score += AIStrategy._card_win_probability(card, mode)

        # 약간의 랜덤성 추가 (±0.4)
        score += random.uniform(-0.4, 0.4)

        bid = max(0, min(round(score), round_number))
        return bid

    @staticmethod
    def _card_win_probability(card: Card, mode: GameMode) -> float:
        """개별 카드의 트릭 승리 확률을 추정한다."""
        ct = card.card_type

        if ct == CardType.SKULL_KING:
            # 확장판에서는 인어에 잡힐 수 있으므로 약간 낮게
            return 0.9 if mode == GameMode.LEGENDARY else 1.0

        if ct == CardType.PIRATE:
            return 0.8

        if ct == CardType.MERMAID:
            return 0.7

        if ct == CardType.TIGRESS:
            return 0.5  # 유연하게 사용 가능

        if ct == CardType.SHRIMP:
            return 0.1  # 상황에 따라 유용하지만 자체로 이기진 못함

        if ct == CardType.KRAKEN:
            return 0.0  # 트릭 파괴 → 자기가 이기는 게 아님

        if ct == CardType.WHITE_WHALE:
            return 0.0  # 상황 의존적

        if ct in (CardType.ESCAPE, CardType.LOOT):
            return 0.0

        # 숫자 카드
        if ct == CardType.NUMBER:
            value = card.value or 0
            if card.suit == Suit.BLACK:
                # 트럼프
                if value >= 12:
                    return 0.85
                elif value >= 9:
                    return 0.55
                elif value >= 5:
                    return 0.3
                else:
                    return 0.1
            else:
                # 일반 색상
                if value >= 13:
                    return 0.25
                elif value >= 10:
                    return 0.12
                else:
                    return 0.05

        return 0.0

    # ════════════════════════════════════════
    #  카드 선택
    # ════════════════════════════════════════

    @staticmethod
    def choose_card(
        player: Player,
        valid_indices: List[int],
        round_number: int,
        current_trick: int,
        trick_cards: List[PlayedCard],
        lead_suit: Optional[Suit],
        mode: GameMode,
    ) -> int:
        """낼 카드를 선택한다.

        전략:
        - 트릭이 더 필요하면 → 강한 카드
        - 트릭이 필요 없으면 → 약한 카드
        - 그 사이면 → 상황에 맞게
        """
        if not valid_indices:
            return 0

        if len(valid_indices) == 1:
            return valid_indices[0]

        bid = player.bid if player.bid is not None else 0
        tricks_needed = bid - player.tricks_won
        tricks_remaining = round_number - current_trick + 1

        hand = player.hand

        if tricks_needed <= 0:
            # 이미 목표 달성 → 가장 약한 카드
            return AIStrategy._pick_weakest(hand, valid_indices)
        elif tricks_needed >= tricks_remaining:
            # 남은 트릭 전부 이겨야 함 → 가장 강한 카드
            return AIStrategy._pick_strongest(hand, valid_indices, trick_cards, lead_suit, mode)
        else:
            # 일부만 이기면 됨 → 스마트 선택
            return AIStrategy._pick_smart(
                hand, valid_indices, trick_cards, lead_suit, mode, tricks_needed, tricks_remaining
            )

    @staticmethod
    def _card_strength(card: Card, lead_suit: Optional[Suit]) -> float:
        """카드의 강도를 숫자로 평가한다 (높을수록 강함)."""
        ct = card.card_type

        if ct == CardType.SKULL_KING:
            return 200
        if ct == CardType.MERMAID:
            return 180
        if card.acts_as_pirate():
            return 160
        if ct == CardType.SHRIMP:
            return 5  # 자체 전투력 없음
        if ct == CardType.KRAKEN:
            return 3
        if ct == CardType.WHITE_WHALE:
            return 4
        if card.acts_as_escape():
            return 1

        # 숫자 카드
        if ct == CardType.NUMBER:
            value = card.value or 0
            if card.suit == Suit.BLACK:
                return 100 + value  # 100~114
            elif lead_suit and card.suit == lead_suit:
                return 50 + value   # 50~64
            else:
                return value        # 1~14 (리드 안 맞으면 약함)

        return 0

    @staticmethod
    def _pick_weakest(hand: List[Card], valid_indices: List[int]) -> int:
        """가장 약한 카드를 선택한다."""
        # 탈출류 우선
        for i in valid_indices:
            if hand[i].acts_as_escape() or hand[i].card_type == CardType.ESCAPE:
                return i

        # 그 외 가장 낮은 강도
        return min(valid_indices, key=lambda i: AIStrategy._card_strength(hand[i], None))

    @staticmethod
    def _pick_strongest(
        hand: List[Card],
        valid_indices: List[int],
        trick_cards: List[PlayedCard],
        lead_suit: Optional[Suit],
        mode: GameMode,
    ) -> int:
        """가장 강한 카드를 선택한다."""
        return max(
            valid_indices,
            key=lambda i: AIStrategy._card_strength(hand[i], lead_suit)
        )

    @staticmethod
    def _pick_smart(
        hand: List[Card],
        valid_indices: List[int],
        trick_cards: List[PlayedCard],
        lead_suit: Optional[Suit],
        mode: GameMode,
        tricks_needed: int,
        tricks_remaining: int,
    ) -> int:
        """상황에 맞게 카드를 선택한다."""
        # 리드 (첫 번째 카드)인 경우
        if not trick_cards:
            # 강한 카드를 골라 리드하되, 너무 강한 카드(SK)는 아까움
            mid_strength = sorted(
                valid_indices,
                key=lambda i: AIStrategy._card_strength(hand[i], lead_suit),
                reverse=True,
            )
            # 중간 정도 강도의 카드 선택 (상위 50% 중 랜덤)
            top_half = mid_strength[:max(1, len(mid_strength) // 2)]
            return random.choice(top_half)

        # 팔로우하는 경우
        # 현재 이기고 있는 카드의 강도 추정
        current_best_strength = 0.0
        for pc in trick_cards:
            s = AIStrategy._card_strength(pc.card, lead_suit)
            current_best_strength = max(current_best_strength, s)

        # 이길 수 있는 카드 찾기
        winning_cards = [
            i for i in valid_indices
            if AIStrategy._card_strength(hand[i], lead_suit) > current_best_strength
            and hand[i].is_number()  # 특수카드는 별도 판단
        ]

        # 특수 승리 카드 (해적, SK, 인어)
        special_winners = [
            i for i in valid_indices
            if hand[i].card_type in (CardType.SKULL_KING, CardType.PIRATE, CardType.MERMAID)
            or hand[i].acts_as_pirate()
        ]

        win_probability = tricks_needed / max(tricks_remaining, 1)

        if random.random() < win_probability:
            # 이기려고 시도
            if winning_cards:
                # 이길 수 있는 가장 약한 카드 (아끼기)
                return min(winning_cards, key=lambda i: AIStrategy._card_strength(hand[i], lead_suit))
            elif special_winners:
                # 특수카드로 이기기
                return random.choice(special_winners)
            else:
                # 이길 수 없으면 약한 카드 버리기
                return AIStrategy._pick_weakest(hand, valid_indices)
        else:
            # 이번엔 지기
            return AIStrategy._pick_weakest(hand, valid_indices)

    # ════════════════════════════════════════
    #  타이그리스 선택
    # ════════════════════════════════════════

    @staticmethod
    def choose_tigress(player: Player, tricks_needed: int) -> TigressChoice:
        """타이그리스를 해적/탈출 중 선택한다."""
        if tricks_needed > 0:
            return TigressChoice.PIRATE
        else:
            return TigressChoice.ESCAPE

    # ════════════════════════════════════════
    #  해적 능력 선택
    # ════════════════════════════════════════

    @staticmethod
    def choose_rosie_target(player_ids: List[int], current_player_id: int) -> int:
        """로지: 다음 리드 플레이어를 랜덤 선택 (자기 제외 우선)."""
        others = [pid for pid in player_ids if pid != current_player_id]
        if others:
            return random.choice(others)
        return current_player_id

    @staticmethod
    def choose_bahij_discards(hand_size: int) -> List[int]:
        """바히즈: 버릴 카드 2장 선택 (뒤에서 2장 = 방금 드로우한 카드 포함)."""
        if hand_size < 2:
            return list(range(hand_size))
        # 마지막 2장 (방금 드로우한 카드일 확률 높음) 또는 랜덤
        indices = list(range(hand_size))
        return random.sample(indices, min(2, len(indices)))

    @staticmethod
    def choose_harry_delta(current_bid: int, tricks_won: int, max_bid: int) -> int:
        """해리: 비딩 변경 결정."""
        diff = current_bid - tricks_won
        if diff > 0 and current_bid > 0:
            return -1  # 초과 비딩이면 낮추기
        elif diff < 0 and current_bid < max_bid:
            return 1   # 부족하면 올리기
        return 0       # 유지

    @staticmethod
    def choose_rascal_wager(current_bid: int, tricks_won: int) -> int:
        """라스칼: 베팅 금액 결정."""
        diff = abs(current_bid - tricks_won)
        if diff <= 1:
            return 20  # 자신감
        else:
            return 10  # 보수적
