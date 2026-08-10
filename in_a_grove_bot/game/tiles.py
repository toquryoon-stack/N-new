"""타일 정의 및 범인 판정 로직

타일: 숫자 1~8 + 빈 타일(X) = 9장
범인 규칙:
  - 5가 용의자에 없으면 → 가장 높은 숫자 = 범인
  - 5가 용의자에 있으면 → 가장 낮은 숫자 = 범인
  - 빈 타일(X)은 절대 범인이 될 수 없음
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import random


BLANK_VALUE = 0  # 빈 타일 내부 값


@dataclass
class Tile:
    """인물 타일"""
    value: int  # 1~8, 0=빈 타일(X)

    @property
    def is_blank(self) -> bool:
        return self.value == BLANK_VALUE

    @property
    def display(self) -> str:
        if self.is_blank:
            return "❌"
        return f"👤{self.value}"

    @property
    def name(self) -> str:
        if self.is_blank:
            return "빈 타일"
        return f"{self.value}번"

    @property
    def emoji(self) -> str:
        if self.is_blank:
            return "❌"
        num_emojis = {
            1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣",
            5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣",
        }
        return num_emojis.get(self.value, "❓")

    def __repr__(self) -> str:
        return f"Tile({self.name})"

    def __eq__(self, other) -> bool:
        if isinstance(other, Tile):
            return self.value == other.value
        return False

    def __hash__(self) -> int:
        return hash(self.value)


def create_all_tiles() -> List[Tile]:
    """전체 9장의 타일을 생성한다."""
    tiles = [Tile(value=i) for i in range(1, 9)]  # 1~8
    tiles.append(Tile(value=BLANK_VALUE))           # 빈 타일
    return tiles


def determine_murderer(suspects: List[Tile]) -> Optional[Tile]:
    """용의자 3명 중 범인을 결정한다.

    Rules:
    - 빈 타일은 범인이 될 수 없음
    - 5가 용의자에 있으면 → 가장 낮은 숫자 = 범인
    - 5가 용의자에 없으면 → 가장 높은 숫자 = 범인
    """
    numbered = [t for t in suspects if not t.is_blank]
    if not numbered:
        return None

    has_five = any(t.value == 5 for t in suspects)

    if has_five:
        return min(numbered, key=lambda t: t.value)
    else:
        return max(numbered, key=lambda t: t.value)


def setup_tiles(player_count: int) -> dict:
    """플레이어 수에 맞게 타일을 셔플하고 배분한다.

    Returns:
        {
            "player_tiles": [Tile, ...],  # 플레이어에게 배분할 타일들
            "suspects": [Tile, Tile, Tile],  # 용의자 3명
            "victim": Tile,  # 피해자 1명
            "removed": [Tile, ...],  # 제거된 타일 (비공개)
        }
    """
    all_tiles = create_all_tiles()
    random.shuffle(all_tiles)

    needed = player_count + 4  # 플레이어 수 + 용의자3 + 피해자1
    removed = all_tiles[needed:]
    used = all_tiles[:needed]

    player_tiles = used[:player_count]
    suspects = used[player_count:player_count + 3]
    victim = used[player_count + 3]

    return {
        "player_tiles": player_tiles,
        "suspects": suspects,
        "victim": victim,
        "removed": removed,
    }
