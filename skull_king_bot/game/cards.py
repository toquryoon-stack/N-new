"""카드 클래스 정의 - 카드 표시, 비교, 식별"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from .enums import CardType, Suit, PirateName, TigressChoice


# ── 이모지 매핑 ──────────────────────────────────────────────

SUIT_EMOJI = {
    Suit.RED: "🔴",
    Suit.YELLOW: "🟡",
    Suit.BLUE: "🔵",
    Suit.BLACK: "⚫",
}

SUIT_NAME_KR = {
    Suit.RED: "빨강",
    Suit.YELLOW: "노랑",
    Suit.BLUE: "파랑",
    Suit.BLACK: "검정",
}

SPECIAL_EMOJI = {
    CardType.ESCAPE: "🏳️",
    CardType.PIRATE: "☠️",
    CardType.SKULL_KING: "💀",
    CardType.MERMAID: "🧜‍♀️",
    CardType.TIGRESS: "🐯",
    CardType.LOOT: "💰",
    CardType.KRAKEN: "🦑",
    CardType.WHITE_WHALE: "🐋",
    CardType.SHRIMP: "🦐",
}

SPECIAL_NAME_KR = {
    CardType.ESCAPE: "탈출",
    CardType.PIRATE: "해적",
    CardType.SKULL_KING: "스컬킹",
    CardType.MERMAID: "인어",
    CardType.TIGRESS: "타이그리스",
    CardType.LOOT: "약탈품",
    CardType.KRAKEN: "크라켄",
    CardType.WHITE_WHALE: "백경",
    CardType.SHRIMP: "새우",
}

PIRATE_NAME_KR = {
    PirateName.ROSIE: "로지 들레이니",
    PirateName.BAHIJ: "바히즈",
    PirateName.JUANITA: "후아니타 제이드",
    PirateName.HARRY: "해리 더 자이언트",
    PirateName.RASCAL: "라스칼",
}

PIRATE_ABILITY_DESC = {
    PirateName.ROSIE: "다음 트릭의 리드 플레이어를 지목합니다",
    PirateName.BAHIJ: "카드 2장을 드로우하고 아무 2장을 버립니다",
    PirateName.JUANITA: "이번 라운드에 나오지 않은 카드를 확인합니다",
    PirateName.HARRY: "비딩을 ±1 변경할 수 있습니다",
    PirateName.RASCAL: "10점 또는 20점을 추가로 베팅합니다",
}


# ── Card 클래스 ──────────────────────────────────────────────

@dataclass
class Card:
    """게임 카드"""
    card_type: CardType
    suit: Optional[Suit] = None              # 숫자 카드 전용
    value: Optional[int] = None              # 숫자 카드 전용 (1~14)
    pirate_name: Optional[PirateName] = None # 해적 카드 전용
    tigress_choice: Optional[TigressChoice] = None  # 타이그리스 플레이 시 선택

    # ── 표시 ──

    @property
    def emoji(self) -> str:
        """카드 이모지"""
        if self.card_type == CardType.NUMBER:
            return SUIT_EMOJI.get(self.suit, "🃏")
        return SPECIAL_EMOJI.get(self.card_type, "🃏")

    @property
    def display_name(self) -> str:
        """한글 표시 이름"""
        if self.card_type == CardType.NUMBER:
            suit_name = SUIT_NAME_KR.get(self.suit, "?")
            return f"{suit_name} {self.value}"
        if self.card_type == CardType.PIRATE and self.pirate_name:
            return f"해적 {PIRATE_NAME_KR.get(self.pirate_name, '')}"
        return SPECIAL_NAME_KR.get(self.card_type, "?")

    @property
    def short_display(self) -> str:
        """짧은 표시 (이모지 + 이름)"""
        if self.card_type == CardType.NUMBER:
            return f"{self.emoji}{self.value}"
        if self.card_type == CardType.PIRATE and self.pirate_name:
            return f"{self.emoji}{PIRATE_NAME_KR.get(self.pirate_name, '')}"
        return f"{self.emoji}{SPECIAL_NAME_KR.get(self.card_type, '')}"

    @property
    def label_for_select(self) -> str:
        """Discord Select 메뉴용 라벨 (이모지 제외, 100자 이하)"""
        if self.card_type == CardType.NUMBER:
            suit_name = SUIT_NAME_KR.get(self.suit, "?")
            trump = " (트럼프)" if self.suit == Suit.BLACK else ""
            return f"{suit_name} {self.value}{trump}"
        if self.card_type == CardType.PIRATE and self.pirate_name:
            return f"해적 - {PIRATE_NAME_KR.get(self.pirate_name, '')}"
        return SPECIAL_NAME_KR.get(self.card_type, "?")

    # ── 판별 ──

    def is_number(self) -> bool:
        return self.card_type == CardType.NUMBER

    def is_special(self) -> bool:
        return self.card_type != CardType.NUMBER

    def is_trump(self) -> bool:
        return self.card_type == CardType.NUMBER and self.suit == Suit.BLACK

    def acts_as_escape(self) -> bool:
        """탈출로 작동하는 카드인지 (탈출, 약탈품, 탈출 선택 타이그리스)"""
        if self.card_type == CardType.ESCAPE:
            return True
        if self.card_type == CardType.LOOT:
            return True
        if self.card_type == CardType.TIGRESS and self.tigress_choice == TigressChoice.ESCAPE:
            return True
        return False

    def acts_as_pirate(self) -> bool:
        """해적으로 작동하는 카드인지 (해적, 해적 선택 타이그리스)"""
        if self.card_type == CardType.PIRATE:
            return True
        if self.card_type == CardType.TIGRESS and self.tigress_choice == TigressChoice.PIRATE:
            return True
        return False

    # ── 고유 ID (덱 내 식별) ──

    @property
    def uid(self) -> str:
        """카드 고유 식별자"""
        if self.card_type == CardType.NUMBER:
            return f"num_{self.suit.value}_{self.value}"
        if self.card_type == CardType.PIRATE:
            return f"pirate_{self.pirate_name.value}"
        return self.card_type.value

    def __str__(self) -> str:
        return self.short_display

    def __repr__(self) -> str:
        if self.card_type == CardType.NUMBER:
            return f"Card({self.suit.value} {self.value})"
        return f"Card({self.card_type.value})"
