"""점수 계산 로직

점수 체계:
- 0 비딩 성공: +라운드 수 × 10
- 0 비딩 실패: -라운드 수 × 10
- N 비딩 성공 (N≥1): +N × 20
- 비딩 실패: -|차이| × 10
- SK로 해적 잡기: 해적 1장당 +30
- 인어로 SK 잡기: +50
- 약탈품 동맹 성공: 양쪽 각 +20
- 라스칼 베팅: 성공 시 +, 실패 시 -
"""

from __future__ import annotations
from typing import List, Dict, Tuple
from .player import Player
from .enums import GameMode
import config as cfg


def calculate_round_scores(
    players: List[Player],
    round_number: int,
    mode: GameMode,
) -> Dict[int, Dict[str, int]]:
    """라운드 종료 시 각 플레이어의 점수를 계산한다.

    Returns:
        Dict[player_id, {
            "base": 기본 점수,
            "sk_bonus": SK 해적 잡기 보너스,
            "mermaid_bonus": 인어 SK 잡기 보너스,
            "loot_bonus": 약탈품 동맹 보너스,
            "rascal_bonus": 라스칼 베팅 보너스,
            "total": 라운드 총점,
        }]
    """
    scores: Dict[int, Dict[str, int]] = {}

    # 약탈품 동맹 성공 여부 확인 (양쪽 모두 비딩 적중해야 함)
    loot_ally_map: Dict[int, List[int]] = {}  # player_id -> [ally_ids]
    for p in players:
        if p.loot_ally_ids:
            loot_ally_map[p.id] = p.loot_ally_ids

    for player in players:
        bid = player.bid if player.bid is not None else 0
        won = player.tricks_won
        hit = (bid == won)

        # ── 기본 점수 ──
        if bid == 0:
            if hit:
                base = round_number * cfg.ZERO_BID_MULTIPLIER
            else:
                base = -(round_number * cfg.ZERO_BID_MULTIPLIER)
        else:
            if hit:
                base = bid * cfg.POINTS_PER_TRICK_WON
            else:
                diff = abs(bid - won)
                base = -(diff * cfg.POINTS_PER_TRICK_MISSED)

        # ── SK 해적 잡기 보너스 ──
        sk_bonus = 0
        if hit and player.pirates_captured_by_sk > 0:
            sk_bonus = player.pirates_captured_by_sk * cfg.SKULL_KING_CAPTURE_BONUS

        # ── 인어 SK 잡기 보너스 (확장판) ──
        mermaid_bonus = 0
        if hit and player.sk_captured_by_mermaid and mode == GameMode.LEGENDARY:
            mermaid_bonus = cfg.MERMAID_CAPTURE_BONUS

        # ── 약탈품 동맹 보너스 (확장판) ──
        loot_bonus = 0
        if mode == GameMode.LEGENDARY and hit:
            # 이 플레이어가 동맹인 모든 관계 확인
            for ally_id in player.loot_ally_ids:
                ally = next((p for p in players if p.id == ally_id), None)
                if ally and ally.bid is not None and ally.bid == ally.tricks_won:
                    # 양쪽 모두 비딩 적중 → 보너스!
                    loot_bonus += cfg.LOOT_ALLIANCE_BONUS

        # ── 라스칼 베팅 보너스 (확장판) ──
        rascal_bonus = 0
        if mode == GameMode.LEGENDARY and player.rascal_wager > 0:
            if hit:
                rascal_bonus = player.rascal_wager
            else:
                rascal_bonus = -player.rascal_wager

        # ── 합산 ──
        total = base + sk_bonus + mermaid_bonus + loot_bonus + rascal_bonus

        scores[player.id] = {
            "base": base,
            "sk_bonus": sk_bonus,
            "mermaid_bonus": mermaid_bonus,
            "loot_bonus": loot_bonus,
            "rascal_bonus": rascal_bonus,
            "total": total,
        }

        # 플레이어 객체에도 반영
        player.round_score = total
        player.total_score += total

    return scores
