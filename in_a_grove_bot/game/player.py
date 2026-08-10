"""플레이어 상태 관리"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Set, TYPE_CHECKING
import discord

if TYPE_CHECKING:
    from .tiles import Tile


# 플레이어별 색상 이모지
PLAYER_COLORS = ["🔴", "🔵", "🟢", "🟡", "🟣"]
PLAYER_COLOR_NAMES = ["빨강", "파랑", "초록", "노랑", "보라"]


@dataclass
class Player:
    """게임 내 플레이어 상태"""
    user: discord.User
    color_index: int = 0
    is_ai: bool = False

    # ── 칩 관리 ──
    investigation_chips: int = 7   # 수사 칩 (사용 가능)
    inept_chips: int = 0           # 무능 형사 칩 (벌점)

    # ── 라운드 내 정보 ──
    original_tile: Optional[Tile] = None   # 처음 받은 타일
    received_tile: Optional[Tile] = None   # 오른쪽에서 받은 타일
    known_suspect_indices: List[int] = field(default_factory=list)
    # 발견자가 확인한 용의자 인덱스 (0, 1, 2)

    # ── 고발 ──
    accusation: Optional[int] = None  # 고발한 용의자 인덱스 (0, 1, 2)

    @property
    def id(self) -> int:
        return self.user.id

    @property
    def name(self) -> str:
        return self.user.display_name

    @property
    def mention(self) -> str:
        return self.user.mention

    @property
    def color_emoji(self) -> str:
        return PLAYER_COLORS[self.color_index % len(PLAYER_COLORS)]

    @property
    def color_name(self) -> str:
        return PLAYER_COLOR_NAMES[self.color_index % len(PLAYER_COLOR_NAMES)]

    @property
    def total_chips(self) -> int:
        """총 칩 수 (수사칩 + 무능칩)"""
        return self.investigation_chips + self.inept_chips

    @property
    def has_chips(self) -> bool:
        """수사 칩이 남아 있는지"""
        return self.investigation_chips > 0

    def reset_round(self) -> None:
        """라운드 시작 시 정보 초기화"""
        self.original_tile = None
        self.received_tile = None
        self.known_suspect_indices = []
        self.accusation = None

    @property
    def known_tiles(self) -> List[Tile]:
        """이 플레이어가 알고 있는 타일 목록"""
        tiles = []
        if self.original_tile:
            tiles.append(self.original_tile)
        if self.received_tile:
            tiles.append(self.received_tile)
        return tiles
