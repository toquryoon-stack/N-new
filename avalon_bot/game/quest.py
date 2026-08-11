"""퀘스트 로직 - 원정대 편성, 투표, 퀘스트 수행"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import config as cfg
from .enums import Vote, QuestVote, QuestResult


@dataclass
class Quest:
    """단일 퀘스트 정보"""
    quest_number: int          # 1~5
    team_size: int             # 원정대 인원
    requires_double_fail: bool  # 실패 2개 필요 여부

    # ── 원정대 ──
    team_member_ids: List[int] = field(default_factory=list)

    # ── 투표 ──
    team_votes: Dict[int, Vote] = field(default_factory=dict)       # player_id → 찬/반
    quest_votes: Dict[int, QuestVote] = field(default_factory=dict) # player_id → 성공/실패

    # ── 결과 ──
    result: QuestResult = QuestResult.PENDING
    rejection_count: int = 0   # 연속 거부 횟수

    @property
    def team_approved(self) -> Optional[bool]:
        """팀 투표 결과. None=아직 투표 중"""
        if not self.team_votes:
            return None
        approve_count = sum(1 for v in self.team_votes.values() if v == Vote.APPROVE)
        reject_count = sum(1 for v in self.team_votes.values() if v == Vote.REJECT)
        total = approve_count + reject_count
        if total == 0:
            return None
        return approve_count > reject_count  # 과반수 찬성

    @property
    def approve_count(self) -> int:
        return sum(1 for v in self.team_votes.values() if v == Vote.APPROVE)

    @property
    def reject_count(self) -> int:
        return sum(1 for v in self.team_votes.values() if v == Vote.REJECT)

    @property
    def fail_count(self) -> int:
        return sum(1 for v in self.quest_votes.values() if v == QuestVote.FAIL)

    @property
    def success_count(self) -> int:
        return sum(1 for v in self.quest_votes.values() if v == QuestVote.SUCCESS)

    def resolve_quest(self) -> QuestResult:
        """퀘스트 결과를 판정한다."""
        fails_needed = 2 if self.requires_double_fail else 1
        if self.fail_count >= fails_needed:
            self.result = QuestResult.FAIL
        else:
            self.result = QuestResult.SUCCESS
        return self.result


def create_quests(player_count: int) -> List[Quest]:
    """인원수에 맞는 퀘스트 목록을 생성한다."""
    sizes = cfg.QUEST_SIZES[player_count]
    quests = []
    for i, size in enumerate(sizes):
        # 4번째 퀘스트(인덱스 3)에서 7명 이상이면 실패 2개 필요
        double_fail = (
            i == 3 and player_count >= cfg.DOUBLE_FAIL_MIN_PLAYERS
        )
        quests.append(Quest(
            quest_number=i + 1,
            team_size=size,
            requires_double_fail=double_fail,
        ))
    return quests
