"""덱 생성 및 관리 - 모드별 카드 구성, 셔플, 배분"""

from __future__ import annotations
import random
from typing import List
from .cards import Card
from .enums import CardType, Suit, PirateName, GameMode


def create_deck(mode: GameMode) -> List[Card]:
    """모드에 따라 전체 덱을 생성한다.

    기본판 (68장): 숫자56 + 탈출5 + 해적5 + SK1 + 새우1
    확장판 (75장): 기본판 + 인어2 + 타이그리스1 + 약탈품2 + 크라켄1 + 백경1
    """
    deck: List[Card] = []

    # ── 숫자 카드: 4색 × 14장 = 56장 ──
    for suit in Suit:
        for value in range(1, 15):
            deck.append(Card(card_type=CardType.NUMBER, suit=suit, value=value))

    # ── 탈출: 5장 ──
    for _ in range(5):
        deck.append(Card(card_type=CardType.ESCAPE))

    # ── 해적: 5장 (각각 고유 이름) ──
    for pirate in PirateName:
        deck.append(Card(card_type=CardType.PIRATE, pirate_name=pirate))

    # ── 스컬킹: 1장 ──
    deck.append(Card(card_type=CardType.SKULL_KING))

    # ── 🦐 새우: 1장 (양쪽 모드 모두) ──
    deck.append(Card(card_type=CardType.SHRIMP))

    # ── 확장판 전용 카드 ──
    if mode == GameMode.LEGENDARY:
        # 인어: 2장
        for _ in range(2):
            deck.append(Card(card_type=CardType.MERMAID))

        # 타이그리스: 1장
        deck.append(Card(card_type=CardType.TIGRESS))

        # 약탈품: 2장
        for _ in range(2):
            deck.append(Card(card_type=CardType.LOOT))

        # 크라켄: 1장
        deck.append(Card(card_type=CardType.KRAKEN))

        # 백경: 1장
        deck.append(Card(card_type=CardType.WHITE_WHALE))

    return deck


class Deck:
    """덱 관리 클래스 - 셔플, 배분, 남은 카드 확인"""

    def __init__(self, mode: GameMode):
        self.mode = mode
        self.cards: List[Card] = create_deck(mode)
        self.shuffle()

    def shuffle(self) -> None:
        """덱을 무작위로 섞는다."""
        random.shuffle(self.cards)

    def deal(self, num_cards: int, num_players: int) -> List[List[Card]]:
        """각 플레이어에게 num_cards장씩 배분한다.

        Returns:
            List[List[Card]]: 플레이어별 손패 리스트
        """
        hands: List[List[Card]] = [[] for _ in range(num_players)]
        for _ in range(num_cards):
            for p in range(num_players):
                if self.cards:
                    hands[p].append(self.cards.pop())
        return hands

    @property
    def remaining(self) -> List[Card]:
        """남은 카드 목록 (후아니타 능력용)"""
        return list(self.cards)

    @property
    def remaining_count(self) -> int:
        return len(self.cards)
