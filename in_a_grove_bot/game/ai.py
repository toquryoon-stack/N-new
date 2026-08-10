"""AI 플레이어 로직 - 추리 & 고발 전략

AI는 자신이 아는 타일 정보를 바탕으로
용의자의 범인 확률을 추정하고 고발을 결정한다.
"""

from __future__ import annotations
import random
from typing import List, Optional, Dict, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .player import Player
    from .tiles import Tile

from .tiles import Tile, BLANK_VALUE


# ── AI 이름 풀 ──

AI_NAMES = ["탐정 봇", "형사 봇", "수사관 봇", "경감 봇", "검시관 봇"]
_ai_name_index = 0


def get_next_ai_name() -> str:
    global _ai_name_index
    name = AI_NAMES[_ai_name_index % len(AI_NAMES)]
    _ai_name_index += 1
    return name


def reset_ai_names():
    global _ai_name_index
    _ai_name_index = 0


class AIUser:
    """Discord User를 모방하는 AI 전용 유저"""
    _next_id = 800_000_001

    def __init__(self, name: str):
        self.id = AIUser._next_id
        AIUser._next_id += 1
        self.display_name = f"🤖 {name}"
        self.name = name
        self.bot = True

    @property
    def mention(self) -> str:
        return f"**🤖 {self.name}**"

    async def send(self, *args, **kwargs):
        pass

    def __repr__(self) -> str:
        return f"AIUser({self.name}, id={self.id})"


class AIStrategy:
    """AI 의사결정 전략"""

    @staticmethod
    def choose_suspects_to_view(num_suspects: int = 3) -> List[int]:
        """발견자 AI: 볼 용의자 2명 선택 (인덱스)."""
        indices = list(range(num_suspects))
        return sorted(random.sample(indices, 2))

    @staticmethod
    def decide_swap_victim(
        viewed_suspects: List[Tuple[int, Tile]],
        victim_tile: Tile,
        known_tiles: List[Tile],
    ) -> Optional[int]:
        """발견자 AI: 피해자와 용의자 교체 여부 결정.

        전략: 교체하면 다른 플레이어를 혼란시킬 수 있음.
        - 5번 타일이 관련되면 교체하여 규칙 반전 유발
        - 랜덤하게 30% 확률로 교체
        """
        if random.random() < 0.3:
            # 30% 확률로 교체
            swap_idx = random.choice([idx for idx, _ in viewed_suspects])
            return swap_idx
        return None

    @staticmethod
    def choose_accusation(
        player: Player,
        suspects: List[Optional[Tile]],  # None = 모름, Tile = 알고 있음
        known_tiles: List[Tile],
        accusation_stacks: Dict[int, List[int]],  # suspect_idx -> [player_ids] (순서)
        player_count: int,
    ) -> int:
        """고발할 용의자를 선택한다.

        전략:
        1. 알고 있는 용의자 정보로 범인 추론
        2. 모르는 타일은 확률적으로 추정
        3. 이미 쌓인 스택 위에 올리는 것은 위험 (틀리면 전부 받음)
        """
        num_suspects = len(suspects)

        # 각 용의자의 "범인일 확률" 추정
        scores: Dict[int, float] = {}

        for i in range(num_suspects):
            tile = suspects[i]
            if tile is not None:
                # 타일을 알고 있음
                if tile.is_blank:
                    scores[i] = 0.0  # 빈 타일은 절대 범인 아님
                else:
                    scores[i] = tile.value / 8.0  # 높을수록 범인 가능성 높음
            else:
                # 모름 → 중간 확률
                scores[i] = 0.5

        # 5번 타일이 알려진 용의자에 있으면 규칙 반전
        known_suspect_values = [
            suspects[i].value for i in range(num_suspects)
            if suspects[i] is not None and not suspects[i].is_blank
        ]
        has_five_known = 5 in known_suspect_values

        if has_five_known:
            # 5가 있으면 낮은 숫자가 범인 → 점수 반전
            for i in range(num_suspects):
                tile = suspects[i]
                if tile is not None and not tile.is_blank:
                    scores[i] = (9 - tile.value) / 8.0

        # 스택 위험도 반영: 이미 칩이 많이 쌓인 곳은 위험
        for i in range(num_suspects):
            stack_size = len(accusation_stacks.get(i, []))
            if stack_size > 0:
                # 틀리면 stack_size + 1개 칩을 받으므로 위험
                scores[i] *= max(0.3, 1.0 - stack_size * 0.2)

        # 가장 높은 점수의 용의자 선택 (약간의 랜덤성)
        if scores:
            # 상위 2개 중 랜덤 선택 (블러핑 요소)
            sorted_suspects = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
            top = sorted_suspects[:min(2, len(sorted_suspects))]

            # 80% 확률로 최고 점수, 20% 확률로 2위
            if len(top) > 1 and random.random() < 0.2:
                return top[1]
            return top[0]

        return random.randint(0, num_suspects - 1)
