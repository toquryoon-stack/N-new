"""트릭 승패 판정 로직

우선순위:
1. 🦐 새우 (SHRIMP) - 최우선, 가장 낮은 숫자 승리
2. 크라켄 vs 백경 - 둘 다 있으면 나중에 낸 카드 효과
3. 크라켄 - 트릭 파괴 (아무도 못 이김)
4. 백경 - 특수카드 무력화, 높은 숫자 승리
5. 일반 판정:
   a. 인어 vs 스컬킹 (확장판) → 인어 승리
   b. 스컬킹 → 해적 모두 이김
   c. 해적 → 숫자 카드 이김
   d. 숫자 카드끼리 → 트럼프(검정) > 리드 색상 > 나머지
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from .cards import Card
from .enums import CardType, Suit, GameMode, PirateName, TigressChoice


@dataclass
class PlayedCard:
    """트릭에 낸 카드 정보"""
    player_id: int
    player_name: str
    card: Card
    play_order: int  # 낸 순서 (0부터)


@dataclass
class TrickResult:
    """트릭 판정 결과"""
    winner_id: Optional[int] = None          # 승자 (없으면 None)
    winner_name: str = ""
    no_winner: bool = False                  # 아무도 못 이김 (크라켄 등)
    next_lead_id: Optional[int] = None       # 다음 트릭 리드

    # ── 보너스 정보 ──
    pirates_captured_count: int = 0          # SK가 잡은 해적 수
    sk_captured_by_mermaid: bool = False      # 인어가 SK 잡았는지
    loot_alliances: List[Tuple[int, int]] = field(default_factory=list)
    # (약탈품 낸 player_id, 먹은 player_id)

    # ── 해적 능력 (확장판) ──
    pirate_ability: Optional[Tuple[int, PirateName]] = None
    # (승자 player_id, 해적 이름)

    # ── 설명 텍스트 ──
    description: str = ""
    winning_card: Optional[Card] = None

    # ── 새우 효과 발동 여부 ──
    shrimp_activated: bool = False


class TrickResolver:
    """트릭 판정기"""

    def __init__(self, mode: GameMode):
        self.mode = mode

    def resolve(self, played_cards: List[PlayedCard], lead_suit: Optional[Suit]) -> TrickResult:
        """트릭의 승자를 판정한다."""
        result = TrickResult()
        cards = played_cards

        if not cards:
            result.no_winner = True
            result.description = "카드가 없습니다."
            return result

        # ── 1. 새우 체크 (최우선) ──
        has_shrimp = any(pc.card.card_type == CardType.SHRIMP for pc in cards)
        if has_shrimp:
            return self._resolve_shrimp(cards, result)

        # ── 2. 크라켄 & 백경 체크 (확장판) ──
        if self.mode == GameMode.LEGENDARY:
            has_kraken = any(pc.card.card_type == CardType.KRAKEN for pc in cards)
            has_whale = any(pc.card.card_type == CardType.WHITE_WHALE for pc in cards)

            if has_kraken and has_whale:
                return self._resolve_kraken_whale(cards, result, lead_suit)
            if has_kraken:
                return self._resolve_kraken(cards, result)
            if has_whale:
                return self._resolve_white_whale(cards, result)

        # ── 3. 일반 판정 ──
        return self._resolve_normal(cards, result, lead_suit)

    # ──────────────────────────────────────────────
    # 새우 판정: 숫자가 가장 낮은 카드 승리
    # ──────────────────────────────────────────────
    def _resolve_shrimp(self, cards: List[PlayedCard], result: TrickResult) -> TrickResult:
        result.shrimp_activated = True

        # 숫자 카드만 추출
        number_cards = [(pc.player_id, pc.player_name, pc.card, pc.play_order)
                        for pc in cards if pc.card.is_number()]

        if not number_cards:
            # 숫자 카드가 하나도 없음 → 아무도 못 이김
            result.no_winner = True
            result.description = "🦐 새우 효과! 숫자 카드가 없어 아무도 트릭을 가져가지 못합니다."
            # 다음 리드: 새우를 낸 사람 (없으면 첫 번째)
            shrimp_player = next(pc for pc in cards if pc.card.card_type == CardType.SHRIMP)
            result.next_lead_id = shrimp_player.player_id
            return result

        # 가장 낮은 숫자 찾기 (동점 시 먼저 낸 사람)
        number_cards.sort(key=lambda x: (x[2].value, x[3]))
        winner_id, winner_name, winning_card, _ = number_cards[0]

        result.winner_id = winner_id
        result.winner_name = winner_name
        result.winning_card = winning_card
        result.next_lead_id = winner_id
        result.description = (
            f"🦐 새우 효과! 가장 낮은 숫자 {winning_card.short_display}(이)가 승리!"
        )

        # 약탈품 동맹 체크
        self._check_loot_alliances(cards, winner_id, result)

        return result

    # ──────────────────────────────────────────────
    # 크라켄 + 백경: 나중에 낸 카드 효과 적용
    # ──────────────────────────────────────────────
    def _resolve_kraken_whale(
        self, cards: List[PlayedCard], result: TrickResult, lead_suit: Optional[Suit]
    ) -> TrickResult:
        kraken_order = next(pc.play_order for pc in cards if pc.card.card_type == CardType.KRAKEN)
        whale_order = next(pc.play_order for pc in cards if pc.card.card_type == CardType.WHITE_WHALE)

        if kraken_order > whale_order:
            # 크라켄이 나중 → 트릭 파괴
            return self._resolve_kraken(cards, result)
        else:
            # 백경이 나중 → 백경 효과
            return self._resolve_white_whale(cards, result)

    # ──────────────────────────────────────────────
    # 크라켄: 트릭 파괴
    # ──────────────────────────────────────────────
    def _resolve_kraken(self, cards: List[PlayedCard], result: TrickResult) -> TrickResult:
        result.no_winner = True
        result.description = "🦑 크라켄! 이 트릭은 파괴되었습니다. 아무도 가져가지 못합니다."

        # 다음 리드: 크라켄이 없었다면 이겼을 사람
        # → 간단히 첫 번째 플레이어
        result.next_lead_id = cards[0].player_id
        return result

    # ──────────────────────────────────────────────
    # 백경: 특수카드 무력화, 높은 숫자 승리
    # ──────────────────────────────────────────────
    def _resolve_white_whale(self, cards: List[PlayedCard], result: TrickResult) -> TrickResult:
        # 숫자 카드만 추출 (색상 무시, 순수 숫자 비교)
        number_cards = [(pc.player_id, pc.player_name, pc.card, pc.play_order)
                        for pc in cards if pc.card.is_number()]

        if not number_cards:
            result.no_winner = True
            result.description = "🐋 백경 효과! 숫자 카드가 없어 아무도 트릭을 가져가지 못합니다."
            result.next_lead_id = cards[0].player_id
            return result

        # 색상 무시, 가장 높은 숫자 (동점 시 먼저 낸 사람)
        number_cards.sort(key=lambda x: (-x[2].value, x[3]))
        winner_id, winner_name, winning_card, _ = number_cards[0]

        result.winner_id = winner_id
        result.winner_name = winner_name
        result.winning_card = winning_card
        result.next_lead_id = winner_id
        result.description = (
            f"🐋 백경 효과! 모든 특수카드 무력화! "
            f"가장 높은 숫자 {winning_card.short_display}(이)가 승리!"
        )
        return result

    # ──────────────────────────────────────────────
    # 일반 판정
    # ──────────────────────────────────────────────
    def _resolve_normal(
        self, cards: List[PlayedCard], result: TrickResult, lead_suit: Optional[Suit]
    ) -> TrickResult:
        # 카드 분류
        sk_cards = [pc for pc in cards if pc.card.card_type == CardType.SKULL_KING]
        pirate_cards = [pc for pc in cards if pc.card.acts_as_pirate()]
        mermaid_cards = [pc for pc in cards if pc.card.card_type == CardType.MERMAID]
        number_cards = [pc for pc in cards if pc.card.is_number()]
        # 탈출류: escape, loot, tigress(escape선택)
        escape_cards = [pc for pc in cards if pc.card.acts_as_escape()]

        has_sk = len(sk_cards) > 0
        has_pirates = len(pirate_cards) > 0
        has_mermaids = len(mermaid_cards) > 0

        # ── 5a. 인어 vs 스컬킹 (확장판) ──
        if self.mode == GameMode.LEGENDARY and has_mermaids and has_sk:
            # 인어가 스컬킹을 잡음!
            winner_pc = min(mermaid_cards, key=lambda pc: pc.play_order)
            result.winner_id = winner_pc.player_id
            result.winner_name = winner_pc.player_name
            result.winning_card = winner_pc.card
            result.next_lead_id = winner_pc.player_id
            result.sk_captured_by_mermaid = True
            result.description = "🧜‍♀️ 인어가 💀 스컬킹을 사로잡았습니다! (+50점 보너스)"

            # 약탈품 동맹 체크
            self._check_loot_alliances(cards, winner_pc.player_id, result)
            return result

        # ── 5b. 스컬킹 ──
        if has_sk:
            winner_pc = sk_cards[0]
            result.winner_id = winner_pc.player_id
            result.winner_name = winner_pc.player_name
            result.winning_card = winner_pc.card
            result.next_lead_id = winner_pc.player_id
            result.pirates_captured_count = len(pirate_cards)

            if result.pirates_captured_count > 0:
                result.description = (
                    f"💀 스컬킹이 해적 {result.pirates_captured_count}명을 잡았습니다! "
                    f"(+{result.pirates_captured_count * 30}점 보너스)"
                )
            else:
                result.description = "💀 스컬킹이 트릭을 가져갑니다!"

            # 해적 능력 체크 (확장판에서는 SK 승리 시 능력 없음)
            self._check_loot_alliances(cards, winner_pc.player_id, result)
            return result

        # ── 5c. 인어 단독 (확장판, SK 없음) ──
        if self.mode == GameMode.LEGENDARY and has_mermaids:
            if has_pirates:
                # 해적이 인어를 이김
                winner_pc = min(pirate_cards, key=lambda pc: pc.play_order)
                result.winner_id = winner_pc.player_id
                result.winner_name = winner_pc.player_name
                result.winning_card = winner_pc.card
                result.next_lead_id = winner_pc.player_id
                result.description = f"☠️ 해적이 🧜‍♀️ 인어를 이겼습니다!"

                # 해적 능력 체크
                self._check_pirate_ability(winner_pc, result)
                self._check_loot_alliances(cards, winner_pc.player_id, result)
                return result
            else:
                # 인어가 숫자 카드를 이김
                winner_pc = min(mermaid_cards, key=lambda pc: pc.play_order)
                result.winner_id = winner_pc.player_id
                result.winner_name = winner_pc.player_name
                result.winning_card = winner_pc.card
                result.next_lead_id = winner_pc.player_id
                result.description = "🧜‍♀️ 인어가 트릭을 가져갑니다!"

                self._check_loot_alliances(cards, winner_pc.player_id, result)
                return result

        # ── 5d. 해적 (SK/인어 없음) ──
        if has_pirates:
            winner_pc = min(pirate_cards, key=lambda pc: pc.play_order)
            result.winner_id = winner_pc.player_id
            result.winner_name = winner_pc.player_name
            result.winning_card = winner_pc.card
            result.next_lead_id = winner_pc.player_id
            result.description = f"☠️ 해적이 트릭을 가져갑니다!"

            # 해적 능력 체크 (확장판)
            self._check_pirate_ability(winner_pc, result)
            self._check_loot_alliances(cards, winner_pc.player_id, result)
            return result

        # ── 5e. 숫자 카드만 ──
        if number_cards:
            winner_pc = self._resolve_number_cards(number_cards, lead_suit)
            result.winner_id = winner_pc.player_id
            result.winner_name = winner_pc.player_name
            result.winning_card = winner_pc.card
            result.next_lead_id = winner_pc.player_id
            result.description = f"{winner_pc.card.short_display}(이)가 트릭을 가져갑니다!"

            self._check_loot_alliances(cards, winner_pc.player_id, result)
            return result

        # ── 5f. 모두 탈출류 ──
        result.no_winner = True
        result.description = "모두 탈출 카드! 아무도 트릭을 가져가지 못합니다."
        # 다음 리드: 첫 번째 사람이 리드
        result.next_lead_id = cards[0].player_id
        return result

    # ──────────────────────────────────────────────
    # 숫자 카드 간 승부
    # ──────────────────────────────────────────────
    def _resolve_number_cards(
        self, number_cards: List[PlayedCard], lead_suit: Optional[Suit]
    ) -> PlayedCard:
        """숫자 카드끼리 비교하여 승자를 결정한다.

        우선순위:
        1. 검정(트럼프) 숫자 카드 중 최고값
        2. 리드 색상 숫자 카드 중 최고값
        3. (리드 색상이 없으면 먼저 낸 카드 기준)
        """
        # 실제 리드 색상 결정: 첫 번째 숫자 카드의 색상
        if lead_suit is None:
            lead_suit = number_cards[0].card.suit

        # 트럼프(검정) 카드
        black_cards = [pc for pc in number_cards if pc.card.suit == Suit.BLACK]
        if black_cards:
            return max(black_cards, key=lambda pc: pc.card.value)

        # 리드 색상 카드
        lead_cards = [pc for pc in number_cards if pc.card.suit == lead_suit]
        if lead_cards:
            return max(lead_cards, key=lambda pc: pc.card.value)

        # fallback: 첫 번째 카드
        return number_cards[0]

    # ──────────────────────────────────────────────
    # 해적 능력 체크 (확장판)
    # ──────────────────────────────────────────────
    def _check_pirate_ability(self, winner_pc: PlayedCard, result: TrickResult) -> None:
        """해적 승리 시 능력 발동 체크 (확장판만)"""
        if self.mode != GameMode.LEGENDARY:
            return

        card = winner_pc.card
        # 타이그리스(해적 선택)는 고유 능력 없음
        if card.card_type == CardType.TIGRESS:
            return
        if card.card_type == CardType.PIRATE and card.pirate_name:
            result.pirate_ability = (winner_pc.player_id, card.pirate_name)

    # ──────────────────────────────────────────────
    # 약탈품 동맹 체크
    # ──────────────────────────────────────────────
    def _check_loot_alliances(
        self, cards: List[PlayedCard], winner_id: int, result: TrickResult
    ) -> None:
        """약탈품 카드의 동맹 관계를 기록한다."""
        if self.mode != GameMode.LEGENDARY:
            return

        for pc in cards:
            if pc.card.card_type == CardType.LOOT and winner_id != pc.player_id:
                # 약탈품 낸 사람과 먹은 사람이 동맹
                result.loot_alliances.append((pc.player_id, winner_id))


def determine_lead_suit(played_cards: List[PlayedCard]) -> Optional[Suit]:
    """현재까지 낸 카드에서 리드 색상을 결정한다.

    첫 번째 숫자 카드의 색상이 리드 색상.
    숫자 카드가 없으면 None.
    """
    for pc in sorted(played_cards, key=lambda x: x.play_order):
        if pc.card.is_number():
            return pc.card.suit
    return None
