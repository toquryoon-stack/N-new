"""플레이어 상태 관리"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Set, TYPE_CHECKING
import discord

if TYPE_CHECKING:
    from .cards import Card
    from .enums import Suit


@dataclass
class Player:
    """게임 내 플레이어 상태"""
    user: discord.User
    is_ai: bool = False
    hand: List[Card] = field(default_factory=list)
    bid: Optional[int] = None
    tricks_won: int = 0
    round_score: int = 0
    total_score: int = 0
    bonus_points: int = 0

    # ── 보너스 추적 ──
    pirates_captured_by_sk: int = 0     # SK로 잡은 해적 수
    sk_captured_by_mermaid: bool = False # 인어로 SK 잡았는지
    loot_ally_ids: List[int] = field(default_factory=list)  # 약탈품 동맹 user ID

    # ── 라스칼 베팅 ──
    rascal_wager: int = 0               # 0, 10, 또는 20

    # ── 해리 비딩 변경 ──
    bid_modified: bool = False

    @property
    def id(self) -> int:
        return self.user.id

    @property
    def name(self) -> str:
        return self.user.display_name

    @property
    def mention(self) -> str:
        return self.user.mention

    def reset_round(self) -> None:
        """라운드 시작 시 상태 초기화"""
        self.hand = []
        self.bid = None
        self.tricks_won = 0
        self.round_score = 0
        self.bonus_points = 0
        self.pirates_captured_by_sk = 0
        self.sk_captured_by_mermaid = False
        self.loot_ally_ids = []
        self.rascal_wager = 0
        self.bid_modified = False

    def play_card(self, card_index: int) -> Card:
        """손패에서 카드를 내고 반환한다."""
        return self.hand.pop(card_index)

    def add_cards(self, cards: List[Card]) -> None:
        """손패에 카드를 추가한다 (바히즈 능력용)."""
        self.hand.extend(cards)

    def discard_cards(self, indices: List[int]) -> List[Card]:
        """지정 인덱스의 카드를 손패에서 제거한다 (바히즈 능력용)."""
        indices_sorted = sorted(indices, reverse=True)
        removed = []
        for i in indices_sorted:
            if 0 <= i < len(self.hand):
                removed.append(self.hand.pop(i))
        return removed

    def get_valid_card_indices(self, lead_suit: Optional[Suit]) -> List[int]:
        """낼 수 있는 카드의 인덱스 목록을 반환한다.

        Rules:
        - 특수 카드는 항상 낼 수 있음
        - 리드 색상이 있고, 해당 색상 숫자 카드가 있으면 그 색상만 가능
        - 리드 색상이 없거나 해당 색상이 없으면 아무 카드 가능
        """
        if lead_suit is None:
            # 리드 색상 미정 → 모든 카드 가능
            return list(range(len(self.hand)))

        # 리드 색상 숫자 카드가 있는지 확인
        has_lead_suit = any(
            c.is_number() and c.suit == lead_suit
            for c in self.hand
        )

        if not has_lead_suit:
            # 리드 색상 없음 → 모든 카드 가능
            return list(range(len(self.hand)))

        # 리드 색상 숫자 카드 또는 특수 카드만 가능
        valid = []
        for i, card in enumerate(self.hand):
            if card.is_special():
                valid.append(i)
            elif card.is_number() and card.suit == lead_suit:
                valid.append(i)
        return valid

    def sort_hand(self) -> None:
        """손패를 정렬한다: 색상별 → 숫자순, 특수카드는 뒤로"""
        suit_order = {"red": 0, "yellow": 1, "blue": 2, "black": 3}
        type_order = {
            "number": 0, "escape": 1, "pirate": 2, "skull_king": 3,
            "mermaid": 4, "tigress": 5, "loot": 6, "kraken": 7,
            "white_whale": 8, "shrimp": 9,
        }

        def sort_key(card):
            if card.is_number():
                return (0, suit_order.get(card.suit.value, 99), card.value)
            return (1, type_order.get(card.card_type.value, 99), 0)

        self.hand.sort(key=sort_key)
