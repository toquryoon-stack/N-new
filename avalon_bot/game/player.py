"""플레이어 상태 관리 - 아발롬"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING
import discord

if TYPE_CHECKING:
    pass

from .enums import Role, Team, Vote, QuestVote
from .roles import get_team


@dataclass
class Player:
    """게임 내 플레이어 상태"""
    user: discord.User
    is_ai: bool = False

    # ── 역할 ──
    role: Optional[Role] = None

    # ── 현재 퀘스트 ──
    team_vote: Optional[Vote] = None         # 원정대 투표 (찬성/반대)
    quest_vote: Optional[QuestVote] = None   # 퀘스트 수행 (성공/실패)

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
    def team(self) -> Optional[Team]:
        if self.role is None:
            return None
        return get_team(self.role)

    @property
    def is_good(self) -> bool:
        return self.team == Team.GOOD

    @property
    def is_evil(self) -> bool:
        return self.team == Team.EVIL

    def reset_votes(self) -> None:
        """퀘스트 시작 시 투표 초기화"""
        self.team_vote = None
        self.quest_vote = None
