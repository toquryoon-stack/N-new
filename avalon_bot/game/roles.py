"""역할 정의 및 배정 로직

역할 구성:
  선: 멀린(1), 퍼시벌(1), 아서의 충신(나머지)
  악: 암살자(1), 모르가나(1), 모드레드/하수인(나머지)
      - 악이 3명일 때: 암살자 + 모르가나 + 모드레드
      - 악이 4명일 때: 암살자 + 모르가나 + 하수인 2명 (모드레드 없음)

밤 단계 정보:
  멀린   → 악의 진영 플레이어를 알 수 있음 (단, 모드레드는 보이지 않음)
  퍼시벌 → 멀린과 모르가나를 알 수 있음 (누가 진짜인지는 모름)
  암살자 → 다른 악의 진영을 알 수 있음
  모르가나 → 다른 악의 진영을 알 수 있음
  하수인 → 다른 악의 진영을 알 수 있음
  모드레드 → 다른 악의 진영을 알 수 있음 (자신은 멀린에게 보이지 않음)
  충신   → 아무 정보 없음
"""

from __future__ import annotations
import random
from typing import Dict, List, Tuple, TYPE_CHECKING

from .enums import Role, Team
import config as cfg

if TYPE_CHECKING:
    from .player import Player


# ── 역할 → 진영 매핑 ──
ROLE_TEAM: Dict[Role, Team] = {
    Role.MERLIN: Team.GOOD,
    Role.PERCIVAL: Team.GOOD,
    Role.LOYAL_SERVANT: Team.GOOD,
    Role.ASSASSIN: Team.EVIL,
    Role.MORGANA: Team.EVIL,
    Role.MINION: Team.EVIL,
    Role.MORDRED: Team.EVIL,
}

# ── 역할 이모지 ──
ROLE_EMOJI: Dict[Role, str] = {
    Role.MERLIN: "🧙",
    Role.PERCIVAL: "🛡️",
    Role.LOYAL_SERVANT: "⚔️",
    Role.ASSASSIN: "🗡️",
    Role.MORGANA: "🧝‍♀️",
    Role.MINION: "👤",
    Role.MORDRED: "👹",
}

# ── 역할 설명 ──
ROLE_DESCRIPTION: Dict[Role, str] = {
    Role.MERLIN: (
        "당신은 **멀린**입니다. 🧙\n"
        "악의 진영이 누구인지 알 수 있습니다. (단, 모드레드가 있다면 그의 정체는 보이지 않습니다!)\n"
        "하지만 정체가 들키면 암살자에게 죽을 수 있습니다!\n"
        "너무 티 나지 않게, 헷갈리게 선을 이끌어주세요."
    ),
    Role.PERCIVAL: (
        "당신은 **퍼시벌**입니다. 🛡️\n"
        "멀린이 누구인지 알 수 있습니다.\n"
        "하지만 모르가나도 멀린처럼 보입니다!\n"
        "누가 진짜 멀린인지 잘 판단해서 도와주세요."
    ),
    Role.LOYAL_SERVANT: (
        "당신은 **아서의 충신**입니다. ⚔️\n"
        "특별한 정보는 없지만, 토론과 투표로\n"
        "악의 진영을 찾아내야 합니다!"
    ),
    Role.ASSASSIN: (
        "당신은 **암살자**입니다. 🗡️\n"
        "다른 악의 하수인이 누구인지 알 수 있습니다.\n"
        "퀘스트 3개가 성공하면, 멀린을 지목할 기회가 주어집니다.\n"
        "멀린을 맞추면 악의 승리!"
    ),
    Role.MORGANA: (
        "당신은 **모르가나**입니다. 🧝‍♀️\n"
        "다른 악의 하수인이 누구인지 알 수 있습니다.\n"
        "퍼시벌에게 멀린처럼 보입니다!\n"
        "멀린인 척 행동하여 선을 혼란시키세요."
    ),
    Role.MINION: (
        "당신은 **모드레드의 하수인**입니다. 👤\n"
        "다른 악의 하수인이 누구인지 알 수 있습니다.\n"
        "정체를 숨기고 퀘스트를 방해하세요!"
    ),
    Role.MORDRED: (
        "당신은 **모드레드**입니다. 👹\n"
        "다른 악의 하수인이 누구인지 알 수 있습니다.\n"
        "**멀린조차 당신의 정체는 알지 못합니다!**\n"
        "정체를 숨기고 퀘스트를 방해하세요!"
    ),
}


def get_team(role: Role) -> Team:
    """역할의 진영을 반환한다."""
    return ROLE_TEAM[role]


def assign_roles(player_count: int) -> List[Role]:
    """인원수에 맞게 역할 목록을 생성한다.

    Returns:
        셔플된 역할 리스트 (인덱스 = 플레이어 순서)
    """
    good_count, evil_count = cfg.TEAM_COMPOSITION[player_count]

    roles: List[Role] = []

    # 선 진영: 멀린(1) + 퍼시벌(1) + 충신(나머지)
    roles.append(Role.MERLIN)
    roles.append(Role.PERCIVAL)
    remaining_good = good_count - 2
    for _ in range(remaining_good):
        roles.append(Role.LOYAL_SERVANT)

    # 악 진영: 암살자(1) + 모르가나(1) + 모드레드/하수인(나머지)
    roles.append(Role.ASSASSIN)
    roles.append(Role.MORGANA)
    remaining_evil = evil_count - 2

    # 악이 정확히 3명일 때는 남은 한 자리를 모드레드로 채운다.
    # 모드레드는 멀린에게 정체가 보이지 않는 특수 악역이다.
    if evil_count == 3 and remaining_evil == 1:
        roles.append(Role.MORDRED)
    else:
        for _ in range(remaining_evil):
            roles.append(Role.MINION)

    random.shuffle(roles)
    return roles


def get_night_info(
    player: Player,
    all_players: List[Player],
) -> str:
    """밤 단계에서 플레이어에게 보여줄 정보를 생성한다."""
    role = player.role
    if role is None:
        return "역할이 배정되지 않았습니다."

    lines = [ROLE_DESCRIPTION[role], ""]

    if role == Role.MERLIN:
        # 멀린: 악의 진영을 볼 수 있음 (모드레드는 예외 - 보이지 않음)
        evil_names = [
            p.name for p in all_players
            if p.role is not None
            and p.id != player.id
            and get_team(p.role) == Team.EVIL
            and p.role != Role.MORDRED
        ]
        if evil_names:
            lines.append("🔴 **악의 진영으로 보이는 자들:**")
            for name in evil_names:
                lines.append(f"  • {name}")
        else:
            lines.append("악의 진영을 감지하지 못했습니다.")

    elif role == Role.PERCIVAL:
        # 퍼시벌: 멀린과 모르가나를 볼 수 있음 (구분 불가)
        merlin_morgana = [
            p.name for p in all_players
            if p.role in (Role.MERLIN, Role.MORGANA)
            and p.id != player.id
        ]
        random.shuffle(merlin_morgana)
        if merlin_morgana:
            lines.append("🔮 **멀린으로 보이는 자들** (진짜와 가짜가 섞여 있음):")
            for name in merlin_morgana:
                lines.append(f"  • {name}")

    elif get_team(role) == Team.EVIL:
        # 악의 진영: 서로를 알 수 있음
        evil_allies = [
            f"{p.name} ({p.role.value})" for p in all_players
            if p.role is not None
            and p.id != player.id
            and get_team(p.role) == Team.EVIL
        ]
        if evil_allies:
            lines.append("🤝 **악의 동료:**")
            for ally in evil_allies:
                lines.append(f"  • {ally}")
        else:
            lines.append("당신은 혼자입니다...")

    else:
        # 충신: 정보 없음
        lines.append("💭 특별한 정보가 없습니다. 토론으로 진실을 밝혀내세요!")

    return "\n".join(lines)
