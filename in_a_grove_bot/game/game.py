"""게임 상태 머신 - 덤불쏭 전체 게임 흐름"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import discord

from .enums import GameState
from .tiles import Tile, setup_tiles, determine_murderer
from .player import Player
from .ai import AIUser, get_next_ai_name
import config as cfg


class Game:
    """덤불쏭 게임 인스턴스"""

    def __init__(self, channel_id: int, host: discord.User):
        self.channel_id = channel_id
        self.host = host
        self.state = GameState.WAITING

        # ── 플레이어 ──
        self.players: Dict[int, Player] = {}
        self.player_order: List[int] = []

        # ── 라운드 ──
        self.current_round: int = 0
        self.discoverer_idx: int = 0  # player_order 내 발견자 인덱스

        # ── 타일 ──
        self.suspects: List[Tile] = []      # 용의자 3명
        self.victim: Optional[Tile] = None  # 피해자
        self.removed_tiles: List[Tile] = [] # 제거된 타일
        self.unseen_idx: Optional[int] = None  # 발견자가 안 본 용의자 인덱스

        # ── 고발 ──
        self.accusation_stacks: Dict[int, List[int]] = {}
        # suspect_idx -> [player_ids] (고발 순서, 마지막=맨 위)
        self.accusation_order: List[int] = []  # 고발 순서 (player_ids)
        self.current_accuser_idx: int = 0  # 현재 고발자 인덱스 (player_order 기준)
        self.last_accused_idx: Optional[int] = None  # 직전에 고발된 용의자 인덱스

        # ── 2인용 고스트 ──
        self.ghost_tile: Optional[Tile] = None

    # ================================================================
    #  로비
    # ================================================================

    def add_player(self, user: discord.User) -> bool:
        if user.id in self.players or len(self.players) >= cfg.MAX_PLAYERS:
            return False
        if self.state != GameState.WAITING:
            return False
        color_idx = len(self.players)
        self.players[user.id] = Player(user=user, color_index=color_idx)
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
        color_idx = len(self.players)
        ai_player = Player(user=ai_user, color_index=color_idx, is_ai=True)
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
        return self.state == GameState.WAITING and len(self.players) >= cfg.MIN_PLAYERS

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
    def discoverer(self) -> Player:
        return self.players[self.player_order[self.discoverer_idx]]

    # ================================================================
    #  라운드 시작
    # ================================================================

    def start_round(self) -> int:
        """새 라운드를 시작한다."""
        self.current_round += 1
        self.state = GameState.DEALING
        self.ghost_tile = None

        # 플레이어 라운드 초기화
        for p in self.players.values():
            p.reset_round()

        # 고발 초기화
        self.accusation_stacks = {0: [], 1: [], 2: []}
        self.accusation_order = []
        self.last_accused_idx = None

        # 타일 배분
        effective_count = max(self.player_count, 3)  # 2인용은 3인용으로
        tile_data = setup_tiles(effective_count)

        self.suspects = tile_data["suspects"]
        self.victim = tile_data["victim"]
        self.removed_tiles = tile_data["removed"]
        self.unseen_idx = None

        # 플레이어에게 타일 배분
        player_tiles = tile_data["player_tiles"]
        for i, pid in enumerate(self.player_order):
            self.players[pid].original_tile = player_tiles[i]

        # 2인용: 3번째 타일은 고스트 (양쪽 모두 볼 수 있음)
        if self.player_count == 2 and len(player_tiles) >= 3:
            self.ghost_tile = player_tiles[2]

        return self.current_round

    # ================================================================
    #  타일 전달 (오른쪽으로 패스)
    # ================================================================

    def pass_tiles(self) -> None:
        """타일을 오른쪽 플레이어에게 전달한다."""
        self.state = GameState.PASSING
        n = self.player_count
        for i in range(n):
            giver_id = self.player_order[i]
            receiver_id = self.player_order[(i + 1) % n]
            giver = self.players[giver_id]
            receiver = self.players[receiver_id]
            receiver.received_tile = giver.original_tile

    # ================================================================
    #  발견자 특권
    # ================================================================

    def set_discoverer_viewed(self, viewed_indices: List[int]) -> List[Tuple[int, Tile]]:
        """발견자가 용의자 2명을 확인한다.

        Returns:
            [(인덱스, Tile), ...] 확인한 용의자 목록
        """
        self.state = GameState.DISCOVERING
        discoverer = self.discoverer

        # 안 본 인덱스 = 나머지 1개
        all_indices = {0, 1, 2}
        unseen = all_indices - set(viewed_indices)
        self.unseen_idx = unseen.pop() if unseen else None

        discoverer.known_suspect_indices = list(viewed_indices)

        viewed = [(idx, self.suspects[idx]) for idx in viewed_indices]
        return viewed

    def swap_victim(self, suspect_idx: int) -> bool:
        """발견자가 피해자와 용의자를 교체한다."""
        if suspect_idx < 0 or suspect_idx >= 3:
            return False
        if self.victim is None:
            return False
        # 교체
        self.suspects[suspect_idx], self.victim = self.victim, self.suspects[suspect_idx]
        return True

    # ================================================================
    #  고발 단계
    # ================================================================

    def start_accusation(self) -> None:
        """고발 단계를 시작한다."""
        self.state = GameState.ACCUSING
        self.current_accuser_idx = self.discoverer_idx

    @property
    def current_accuser(self) -> Player:
        return self.players[self.player_order[self.current_accuser_idx]]

    def view_suspects_for_next_accuser(self) -> List[Tuple[int, Tile]]:
        """직전에 고발된 용의자를 제외한 나머지 2명을 현재 고발자가 확인한다.

        원작 규칙: 발견자(첫 고발자) 이후의 모든 고발자는, 자신의 차례에
        고발하기 전 "바로 직전에 고발된 용의자"를 제외한 나머지 2명의
        번호를 확인해야 한다.
        """
        if self.last_accused_idx is None:
            indices = [0, 1, 2]
        else:
            indices = [i for i in range(3) if i != self.last_accused_idx]

        accuser = self.current_accuser
        accuser.known_suspect_indices = list(indices)
        return [(i, self.suspects[i]) for i in indices]

    def make_accusation(self, player_id: int, suspect_idx: int) -> bool:
        """플레이어가 용의자를 고발한다."""
        if suspect_idx < 0 or suspect_idx >= 3:
            return False
        player = self.players.get(player_id)
        if not player:
            return False

        player.accusation = suspect_idx
        self.accusation_stacks[suspect_idx].append(player_id)
        self.accusation_order.append(player_id)
        self.last_accused_idx = suspect_idx
        return True

    def advance_accuser(self) -> bool:
        """다음 고발자로 이동. 모두 끝나면 False."""
        next_offset = len(self.accusation_order)
        if next_offset >= self.player_count:
            return False
        # 발견자부터 시계방향
        self.current_accuser_idx = (self.discoverer_idx + next_offset) % self.player_count
        return True

    def all_accused(self) -> bool:
        return len(self.accusation_order) >= self.player_count

    # ================================================================
    #  공개 & 판정
    # ================================================================

    def reveal_and_judge(self) -> dict:
        """용의자를 공개하고 범인을 판정한다.

        Returns:
            {
                "suspects": [Tile, Tile, Tile],
                "murderer": Tile,
                "murderer_idx": int,
                "correct_players": [player_id, ...],
                "wrong_stacks": {suspect_idx: {
                    "top_player_id": int,
                    "all_player_ids": [int, ...],
                    "chip_count": int,
                }},
                "has_five": bool,
            }
        """
        self.state = GameState.REVEALING

        murderer = determine_murderer(self.suspects)
        murderer_idx = None
        if murderer:
            for i, s in enumerate(self.suspects):
                if s == murderer:
                    murderer_idx = i
                    break

        has_five = any(t.value == 5 for t in self.suspects)

        correct_players = []
        wrong_stacks = {}

        for idx in range(3):
            stack = self.accusation_stacks[idx]
            if not stack:
                continue

            if idx == murderer_idx:
                # 맞춘 사람들 → 칩 게임에서 제거 (신판 규칙)
                correct_players.extend(stack)
            else:
                # 틀린 스택 → 맨 위 사람이 전부 받음
                top_player_id = stack[-1]  # 마지막 = 맨 위
                wrong_stacks[idx] = {
                    "top_player_id": top_player_id,
                    "all_player_ids": list(stack),
                    "chip_count": len(stack),
                }

        return {
            "suspects": self.suspects,
            "murderer": murderer,
            "murderer_idx": murderer_idx,
            "correct_players": correct_players,
            "wrong_stacks": wrong_stacks,
            "has_five": has_five,
        }

    def apply_results(self, result: dict) -> Dict[int, dict]:
        """판정 결과를 플레이어에게 적용한다.

        Returns:
            {player_id: {"correct": bool, "chips_lost": int, "penalty_received": int}}
        """
        self.state = GameState.ROUND_END
        player_results = {}

        # 맞춘 사람: 수사 칩 1개 제거 (게임에서 영구 제거)
        for pid in result["correct_players"]:
            p = self.players.get(pid)
            if p:
                p.investigation_chips = max(0, p.investigation_chips - 1)
                player_results[pid] = {"correct": True, "chips_lost": 1, "penalty_received": 0}

        # 틀린 스택: 맨 위 플레이어가 모든 칩을 무능 칩으로 받음
        for idx, stack_info in result["wrong_stacks"].items():
            top_pid = stack_info["top_player_id"]
            chip_count = stack_info["chip_count"]

            for pid in stack_info["all_player_ids"]:
                p = self.players.get(pid)
                if p and pid not in player_results:
                    if pid == top_pid:
                        # 맨 위: 자기 칩 1개 잃고 + 전체 스택을 무능 칩으로 받음
                        p.investigation_chips = max(0, p.investigation_chips - 1)
                        p.inept_chips += chip_count
                        player_results[pid] = {
                            "correct": False,
                            "chips_lost": 1,
                            "penalty_received": chip_count,
                        }
                    else:
                        # 아래: 자기 칩 1개만 잃음
                        p.investigation_chips = max(0, p.investigation_chips - 1)
                        player_results[pid] = {
                            "correct": False,
                            "chips_lost": 1,
                            "penalty_received": 0,
                        }

        # 가장 많은 벌점 받은 사람 → 다음 라운드 발견자
        max_penalty = 0
        max_penalty_pid = None
        for pid, info in player_results.items():
            if info["penalty_received"] > max_penalty:
                max_penalty = info["penalty_received"]
                max_penalty_pid = pid

        if max_penalty_pid and max_penalty_pid in self.player_order:
            self.discoverer_idx = self.player_order.index(max_penalty_pid)

        return player_results

    # ================================================================
    #  승패 판정
    # ================================================================

    def check_game_over(self) -> Optional[dict]:
        """게임 종료 조건을 확인한다.

        Returns:
            None if game continues, else:
            {"loser_id": int, "reason": str, "winner_id": int}
        """
        for p in self.player_list:
            # 수사 칩 0개 → 패배
            if p.investigation_chips <= 0:
                winner = self._find_winner(exclude_id=p.id)
                return {
                    "loser_id": p.id,
                    "reason": f"{p.name}의 수사 칩이 모두 소진되었습니다!",
                    "winner_id": winner.id if winner else None,
                }

        # 최대 라운드 도달
        if self.current_round >= cfg.MAX_ROUNDS:
            winner = self._find_winner()
            return {
                "loser_id": None,
                "reason": f"최대 {cfg.MAX_ROUNDS}라운드 도달!",
                "winner_id": winner.id if winner else None,
            }

        return None

    def _find_winner(self, exclude_id: Optional[int] = None) -> Optional[Player]:
        """패배자를 제외하고 총 칩이 가장 적은 플레이어를 찾는다."""
        candidates = [p for p in self.player_list if p.id != exclude_id]
        if not candidates:
            return None
        return min(candidates, key=lambda p: p.total_chips)

    def get_standings(self) -> List[Tuple[Player, int]]:
        """현재 순위를 반환한다. (총 칩 오름차순)"""
        ranked = sorted(self.player_list, key=lambda p: p.total_chips)
        return [(p, rank + 1) for rank, p in enumerate(ranked)]


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
