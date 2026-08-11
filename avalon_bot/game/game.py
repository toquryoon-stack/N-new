"""게임 상태 머신 - 아발롬 전체 게임 흐름"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import discord

from .enums import GameState, Team, Role, Vote, QuestVote, QuestResult
from .roles import assign_roles, get_team
from .player import Player
from .quest import Quest, create_quests
from .ai import AIUser, get_next_ai_name
import config as cfg


class Game:
    """아발롬 게임 인스턴스"""

    def __init__(self, channel_id: int, host: discord.User):
        self.channel_id = channel_id
        self.host = host
        self.state = GameState.WAITING

        # ── 플레이어 ──
        self.players: Dict[int, Player] = {}
        self.player_order: List[int] = []  # 앉은 순서

        # ── 퀘스트 ──
        self.quests: List[Quest] = []
        self.current_quest_idx: int = 0

        # ── 리더 ──
        self.leader_idx: int = 0  # player_order 내 리더 인덱스
        self.rejection_count: int = 0  # 연속 거부 횟수

        # ── 원정대 ──
        self.current_team_ids: List[int] = []

        # ── 퀘스트 기록 (AI 참고용) ──
        self.quest_history: List[dict] = []

    # ================================================================
    #  로비
    # ================================================================

    def add_player(self, user: discord.User) -> bool:
        if user.id in self.players or len(self.players) >= cfg.MAX_PLAYERS:
            return False
        if self.state != GameState.WAITING:
            return False
        self.players[user.id] = Player(user=user)
        self.player_order.append(user.id)
        return True

    def remove_player(self, user_id: int) -> bool:
        if user_id not in self.players:
            return False
        del self.players[user_id]
        self.player_order.remove(user_id)
        return True

    def add_ai_player(self) -> Optional[Player]:
        if len(self.players) >= cfg.MAX_PLAYERS or self.state != GameState.WAITING:
            return None
        ai_user = AIUser(get_next_ai_name())
        ai_player = Player(user=ai_user, is_ai=True)
        self.players[ai_user.id] = ai_player
        self.player_order.append(ai_user.id)
        return ai_player

    def remove_ai_player(self) -> bool:
        for pid in reversed(self.player_order):
            if self.players[pid].is_ai:
                del self.players[pid]
                self.player_order.remove(pid)
                return True
        return False

    def can_start(self) -> bool:
        return (
            self.state == GameState.WAITING
            and len(self.players) >= cfg.MIN_PLAYERS
        )

    @property
    def player_count(self) -> int:
        return len(self.players)

    @property
    def player_list(self) -> List[Player]:
        return [self.players[pid] for pid in self.player_order]

    @property
    def ai_count(self) -> int:
        return sum(1 for p in self.players.values() if p.is_ai)

    @property
    def leader(self) -> Player:
        return self.players[self.player_order[self.leader_idx]]

    @property
    def current_quest(self) -> Quest:
        return self.quests[self.current_quest_idx]

    @property
    def good_players(self) -> List[Player]:
        return [p for p in self.player_list if p.is_good]

    @property
    def evil_players(self) -> List[Player]:
        return [p for p in self.player_list if p.is_evil]

    @property
    def success_count(self) -> int:
        return sum(
            1 for q in self.quests
            if q.result == QuestResult.SUCCESS
        )

    @property
    def fail_count(self) -> int:
        return sum(
            1 for q in self.quests
            if q.result == QuestResult.FAIL
        )

    # ================================================================
    #  게임 시작
    # ================================================================

    def start_game(self) -> None:
        """게임을 시작한다 - 역할 배정 + 퀘스트 생성"""
        self.state = GameState.NIGHT

        # 역할 배정
        roles = assign_roles(self.player_count)
        for i, pid in enumerate(self.player_order):
            self.players[pid].role = roles[i]

        # 퀘스트 생성
        self.quests = create_quests(self.player_count)
        self.current_quest_idx = 0

        # 리더는 랜덤
        import random
        self.leader_idx = random.randint(0, self.player_count - 1)

    # ================================================================
    #  원정대 편성
    # ================================================================

    def start_team_build(self) -> None:
        """원정대 편성 단계를 시작한다."""
        self.state = GameState.TEAM_BUILD
        self.current_team_ids = []

        # 플레이어 투표 초기화
        for p in self.players.values():
            p.reset_votes()

    def set_team(self, member_ids: List[int]) -> bool:
        """리더가 원정대를 편성한다."""
        quest = self.current_quest
        if len(member_ids) != quest.team_size:
            return False
        # 모두 유효한 플레이어인지 확인
        if not all(pid in self.players for pid in member_ids):
            return False
        self.current_team_ids = member_ids
        quest.team_member_ids = list(member_ids)
        return True

    # ================================================================
    #  팀 투표
    # ================================================================

    def start_team_vote(self) -> None:
        """팀 투표 단계를 시작한다."""
        self.state = GameState.TEAM_VOTE
        self.current_quest.team_votes = {}

    def cast_team_vote(self, player_id: int, vote: Vote) -> bool:
        """팀 투표를 한다."""
        if player_id not in self.players:
            return False
        if player_id in self.current_quest.team_votes:
            return False  # 이미 투표함
        self.players[player_id].team_vote = vote
        self.current_quest.team_votes[player_id] = vote
        return True

    def all_team_voted(self) -> bool:
        """모든 플레이어가 팀 투표를 했는지"""
        return len(self.current_quest.team_votes) >= self.player_count

    def resolve_team_vote(self) -> Tuple[bool, int, int]:
        """팀 투표를 집계한다.

        Returns:
            (승인 여부, 찬성 수, 반대 수)
        """
        quest = self.current_quest
        approve = quest.approve_count
        reject = quest.reject_count
        approved = approve > reject

        if not approved:
            self.rejection_count += 1
        else:
            self.rejection_count = 0

        return approved, approve, reject

    def check_rejection_limit(self) -> bool:
        """연속 거부 횟수가 한계인지 확인"""
        return self.rejection_count >= cfg.MAX_REJECTIONS

    # ================================================================
    #  퀘스트 수행
    # ================================================================

    def start_quest(self) -> None:
        """퀘스트 수행 단계를 시작한다."""
        self.state = GameState.QUEST
        self.current_quest.quest_votes = {}

    def cast_quest_vote(self, player_id: int, vote: QuestVote) -> bool:
        """퀘스트 투표를 한다."""
        if player_id not in self.current_team_ids:
            return False
        if player_id in self.current_quest.quest_votes:
            return False
        # 선은 실패를 낼 수 없음
        player = self.players[player_id]
        if player.is_good and vote == QuestVote.FAIL:
            return False
        player.quest_vote = vote
        self.current_quest.quest_votes[player_id] = vote
        return True

    def all_quest_voted(self) -> bool:
        """모든 원정대원이 퀘스트 투표를 했는지"""
        return len(self.current_quest.quest_votes) >= len(self.current_team_ids)

    def resolve_quest(self) -> Tuple[QuestResult, int, int]:
        """퀘스트 결과를 판정한다.

        Returns:
            (결과, 성공 수, 실패 수)
        """
        quest = self.current_quest
        result = quest.resolve_quest()

        # 기록 저장
        self.quest_history.append({
            "quest_number": quest.quest_number,
            "team_ids": list(quest.team_member_ids),
            "team_votes": {
                pid: v.value for pid, v in quest.team_votes.items()
            },
            "result": result.value,
            "fail_count": quest.fail_count,
        })

        return result, quest.success_count, quest.fail_count

    # ================================================================
    #  퀘스트 진행
    # ================================================================

    def advance_leader(self) -> None:
        """다음 리더로 이동"""
        self.leader_idx = (self.leader_idx + 1) % self.player_count

    def advance_quest(self) -> bool:
        """다음 퀘스트로 이동. 더 이상 없으면 False."""
        self.current_quest_idx += 1
        return self.current_quest_idx < len(self.quests)

    # ================================================================
    #  승패 판정
    # ================================================================

    def check_good_wins_quests(self) -> bool:
        """선이 퀘스트 3개를 성공했는지"""
        return self.success_count >= cfg.QUESTS_TO_WIN

    def check_evil_wins_quests(self) -> bool:
        """악이 퀘스트 3개를 실패시켰는지"""
        return self.fail_count >= cfg.QUESTS_TO_WIN

    def start_assassin_phase(self) -> None:
        """암살자 단계를 시작한다."""
        self.state = GameState.ASSASSIN

    def get_assassin(self) -> Optional[Player]:
        """암살자를 찾는다."""
        for p in self.player_list:
            if p.role == Role.ASSASSIN:
                return p
        return None

    def get_merlin(self) -> Optional[Player]:
        """멀린을 찾는다."""
        for p in self.player_list:
            if p.role == Role.MERLIN:
                return p
        return None

    def assassinate(self, target_id: int) -> Tuple[bool, Optional[Player]]:
        """암살자가 멀린을 지목한다.

        Returns:
            (멀린 맞춤 여부, 대상 플레이어)
        """
        target = self.players.get(target_id)
        if target is None:
            return False, None

        is_merlin = target.role == Role.MERLIN
        self.state = GameState.GAME_OVER
        return is_merlin, target

    def get_quest_summary(self) -> List[dict]:
        """퀘스트 요약 정보를 반환한다."""
        summary = []
        for q in self.quests:
            summary.append({
                "number": q.quest_number,
                "team_size": q.team_size,
                "double_fail": q.requires_double_fail,
                "result": q.result.value,
                "fail_count": q.fail_count if q.result != QuestResult.PENDING else None,
            })
        return summary


class GameManager:
    """채널별 게임 인스턴스 관리"""

    def __init__(self):
        self._games: Dict[int, Game] = {}

    def create_game(self, channel_id: int, host: discord.User) -> Game:
        game = Game(channel_id=channel_id, host=host)
        self._games[channel_id] = game
        return game

    def get_game(self, channel_id: int) -> Optional[Game]:
        return self._games.get(channel_id)

    def remove_game(self, channel_id: int) -> bool:
        if channel_id in self._games:
            del self._games[channel_id]
            return True
        return False
