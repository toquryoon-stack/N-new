"""AI 플레이어 로직 - 아발롬

AI 전략:
  선 AI: 퀘스트를 성공시키려 함, 의심스러운 플레이어 배제
  악 AI: 적절히 섞어서 실패를 유도, 들키지 않으려 함

역할별 지식 제한 (실제 사람 플레이어와 동일한 정보만 사용):
  멀린   - 악의 진영을 알지만, 모드레드(있는 경우)는 보이지 않는다.
           또한 이 지식을 그대로 드러내면 정체가 들키므로,
           의도적으로 애매하게/헷갈리게 행동해야 한다.
  퍼시벌 - 멀린과 모르가나 둘 다 보이지만 누가 진짜인지는 모른다.
           퀘스트 기록을 바탕으로 추리하되, 100% 확신하지 않는다.
"""

from __future__ import annotations
import random
from typing import List, Optional, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from .player import Player
    from .quest import Quest

from .enums import Role, Team, Vote, QuestVote
from .roles import get_team
import config as cfg


# ── AI 이름 풀 ──
AI_NAMES = [
    "기사 봇", "마법사 봇", "성기사 봇", "궁수 봇",
    "현자 봇", "전사 봇", "수호자 봇", "정찰병 봇",
    "사령관 봇", "용사 봇",
]
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
    _next_id = 900_000_001

    def __init__(self, name: str):
        self.id = AIUser._next_id
        AIUser._next_id += 1
        self.display_name = f"\U0001f916 {name}"
        self.name = name
        self.bot = True

    @property
    def mention(self) -> str:
        return f"**\U0001f916 {self.name}**"

    async def send(self, *args, **kwargs):
        pass

    async def create_dm(self):
        return self

    def __repr__(self) -> str:
        return f"AIUser({self.name}, id={self.id})"


def _merlin_known_evil_ids(all_players: List[Player]) -> set:
    """멀린이 실제로 볼 수 있는 악의 진영 id 목록.

    모드레드는 멀린에게 보이지 않으므로 제외한다.
    (멀린 AI는 이 함수로 얻은 정보만 사용해야 하며, 실제 진영 정보를
    그대로 참조하면 모드레드까지 알아채는 '치팅'이 되어버린다.)
    """
    return {
        p.id for p in all_players
        if p.role is not None
        and get_team(p.role) == Team.EVIL
        and p.role != Role.MORDRED
    }


# 실패 담당을 정할 때 "정체가 드러나도 상대적으로 덜 아까운" 순서.
# 숫자가 작을수록 먼저 실패를 담당한다 (위장 능력이 없는 역할을 우선 소모).
#   암살자/하수인 - 위장 능력이 없어 들켜도 잃을 게 적다
#   모르가나      - 퍼시벌에게 멀린으로 보이는 위장이 아깝다
#   모드레드      - 멀린에게도 안 보이는 유일한 패라 가장 아깝다
_EXPOSE_PRIORITY = {
    Role.ASSASSIN: 0,
    Role.MINION: 0,
    Role.MORGANA: 1,
    Role.MORDRED: 2,
}


def _expose_priority(role: Optional[Role]) -> int:
    return _EXPOSE_PRIORITY.get(role, 0)


def _score_merlin_candidates(
    candidate_ids: List[int],
    quest_history: List[dict],
) -> Dict[int, float]:
    """퍼시벌이 멀린/모르가나 후보 중 누가 진짜 멀린에 가까운지 점수를 매긴다.

    단서: 실패한 퀘스트에 반대표를 던졌다면 멀린일 가능성이 높고
    (실제 멀린은 악이 낀 팀을 미리 알아채고 반대하는 경향이 있음),
    성공한 퀘스트에 찬성표를 던진 것도 약한 단서로 취급한다.
    또한 실제로 그 퀘스트에 참여해서 성공/실패시켰는지도 참고한다
    (성공한 원정대에 있었으면 멀린 쪽에, 실패한 원정대에 있었으면
    모르가나 쪽에 조금 더 무게를 둔다). 완전한 확신은 주지 않도록
    무작위성을 더한다.
    """
    score: Dict[int, float] = {pid: 0.0 for pid in candidate_ids}

    for hist in quest_history:
        result = hist.get("result")
        votes = hist.get("team_votes", {})
        team_ids = hist.get("team_ids", [])

        for pid in candidate_ids:
            vote = votes.get(pid)
            if vote is not None:
                if result == "실패" and vote == "반대":
                    score[pid] += 1.5
                elif result == "성공" and vote == "찬성":
                    score[pid] += 0.4

            if pid in team_ids:
                if result == "성공":
                    score[pid] += 0.6
                elif result == "실패":
                    score[pid] -= 0.8

    # 퍼시벌은 확신할 수 없으므로 약간의 불확실성을 더한다.
    for pid in score:
        score[pid] += random.random() * 1.3

    return score


def _get_confirmed_evil_ids(quest_history: List[dict]) -> set:
    """투표 결과만으로 100% 확정할 수 있는 악을 찾는다.

    어떤 원정대의 실패 수가 인원수와 같다면(전원이 실패를 냈다는 뜻),
    선은 절대 실패를 낼 수 없으므로 그 팀 전원이 확정적으로 악이다.
    (2인 팀에서 실패 2개가 가장 흔한 경우지만, 3인 이상이어도 전원 실패라면
    마찬가지로 100% 확정된다.) 이 정보는 누구나 공개된 결과만 보고 알 수
    있으므로 멀린을 포함한 모든 선 진영이 활용할 수 있다 - 모드레드처럼
    멀린에게 원래 안 보이는 악도 이렇게 들키면 정체가 드러난다.
    """
    confirmed = set()
    for hist in quest_history:
        team_ids = hist.get("team_ids", [])
        if team_ids and hist.get("fail_count", 0) == len(team_ids):
            confirmed.update(team_ids)
    return confirmed


def _min_forced_evil_overlap(candidate_ids, quest_history: List[dict]) -> int:
    """과거 원정대 기록만으로, 후보 팀(candidate_ids)에 최소 몇 명의 악이
    반드시 포함되는지 하한선을 계산한다 (전원 확정까지는 아니어도 되는 경우).

    과거 원정대(인원 n, 실패 k)에서 선일 수 있는 인원은 최대 (n-k)명이다.
    후보 팀과 그 원정대가 겹치는 인원(overlap)이 (n-k)명을 넘어서면,
    그 초과분만큼은 아무리 좋게 봐도 악일 수밖에 없다.
    예: 3인 원정대에서 실패가 2개 나왔다면 그 팀의 선은 최대 1명이므로,
    그 3명 중 아무 2명을 묶어 새 원정대를 꾸려도 그 안엔 최소 1명의 악이
    포함된다는 게 논리적으로 확정된다 - 누가 정확히 악인지는 몰라도,
    이 조합 자체를 원정대로 승인하면 안 된다는 것만은 확실하다.
    """
    candidate_ids = set(candidate_ids)
    worst = 0
    for hist in quest_history:
        team_ids = hist.get("team_ids", [])
        n = len(team_ids)
        if n == 0:
            continue
        fail_count = hist.get("fail_count", 0)
        max_good = n - fail_count
        overlap = len(candidate_ids & set(team_ids))
        forced_evil = overlap - max_good
        if forced_evil > worst:
            worst = forced_evil
    return worst


def _success_trust_scores(quest_history: List[dict]) -> Dict[int, float]:
    """성공한 원정대에 있었던 플레이어일수록 선일 가능성이 높다고 보고
    신뢰 점수를 준다 (같은 조합을 다시 구성하는 데 쓰인다).

    단, 악이 교묘하게 성공한 척 속이는 경우도 있으므로 이건 어디까지나
    '가능성이 높다'는 힌트일 뿐 확정적인 증거는 아니다.
    """
    trust: Dict[int, float] = {}
    for hist in quest_history:
        if hist.get("result") != "성공":
            continue
        for pid in hist.get("team_ids", []):
            trust[pid] = trust.get(pid, 0.0) + 1.0
    return trust


def _weighted_order_by_trust(ids: List[int], trust: Dict[int, float]) -> List[int]:
    """신뢰 점수가 높은 사람이 뒤쪽(=먼저 pop되는 쪽)에 오도록 정렬한다.

    확정이 아니라 '확률을 높이는' 수준이어야 하므로 무작위성을 충분히 섞는다.
    """
    # 오름차순 정렬 후 pop()으로 뒤에서부터 꺼내 쓰므로, 신뢰 점수가 높을수록
    # 정렬 키도 커지게(=리스트 뒤쪽에 오게) 만든다.
    def sort_key(pid: int) -> float:
        return random.random() + trust.get(pid, 0.0) * 0.35

    return sorted(ids, key=sort_key)


def _early_game_skepticism(quest_history: List[dict]) -> float:
    """게임 초반에는 뚜렷한 근거 없이도 원정대를 더 자주 반대하게 만드는
    보정값. 아직 완료된 퀘스트가 없으면(즉 첫 퀘스트 편성 단계) 여러 번
    재편성을 거치도록 유도해 다른 플레이어들의 투표 패턴을 관찰할 기회를
    만든다. 퀘스트가 쌓일수록(=검증할 자료가 쌓일수록) 원래 성향으로 돌아온다.
    """
    completed = len(quest_history)
    if completed == 0:
        return 0.30
    if completed == 1:
        return 0.10
    return 0.0


def _percival_guess_merlin_id(
    candidate_ids: List[int],
    quest_history: List[dict],
) -> Optional[int]:
    """퍼시벌이 판단한 '진짜 멀린일 가능성이 높은' 후보 id를 반환한다.

    확신이 아니라 판단이므로, 점수가 가장 높은 후보를 대부분(75%) 고르되
    가끔은(25%) 헷갈려서 반대 후보(모르가나일 수도 있음)를 고른다.
    """
    if not candidate_ids:
        return None
    if len(candidate_ids) == 1:
        return candidate_ids[0]

    scores = _score_merlin_candidates(candidate_ids, quest_history)
    ranked = sorted(candidate_ids, key=lambda pid: scores[pid], reverse=True)

    if random.random() < 0.75:
        return ranked[0]
    return ranked[1]


class AIStrategy:
    """AI 의사결정 전략"""

    # ================================================================
    #  원정대 편성 (리더일 때)
    # ================================================================

    @staticmethod
    def propose_team(
        leader: Player,
        all_players: List[Player],
        team_size: int,
        quest_history: List[dict],
    ) -> List[int]:
        """원정대 멤버를 선택한다.

        Returns:
            선택된 player_id 리스트
        """
        def _build_once() -> List[int]:
            player_ids = [p.id for p in all_players]
            confirmed_evil = _get_confirmed_evil_ids(quest_history)
            # 과거에 성공한 원정대에 있었던 사람일수록 선일 확률이 높다고 보고
            # (교묘하게 속인 악일 수도 있으니 절대적이진 않다) 우선 고려한다.
            trust = _success_trust_scores(quest_history)

            if leader.is_evil:
                # ── 악 리더 전략 ──
                # 자기 자신은 포함 (의심 회피)
                team = [leader.id]

                # 악 동료 중 1명을 포함 (퀘스트 실패를 위해)
                evil_allies = [
                    p.id for p in all_players
                    if p.is_evil and p.id != leader.id
                ]
                if evil_allies:
                    # 70% 확률로 악 동료 1명 포함 - 이미 정체가 탄로난 동료보다는
                    # 아직 안 들킨 동료를 우선해서 더 의심을 사지 않도록 한다
                    if random.random() < 0.7:
                        not_exposed = [pid for pid in evil_allies if pid not in confirmed_evil]
                        pool = not_exposed if not_exposed else evil_allies
                        team.append(random.choice(pool))

                # 나머지는 선 진영에서 채움 (의심 회피)
                good_players = [
                    p.id for p in all_players
                    if p.is_good and p.id not in team
                ]
                random.shuffle(good_players)
                while len(team) < team_size and good_players:
                    team.append(good_players.pop())

                # 부족하면 아무나
                remaining = [pid for pid in player_ids if pid not in team]
                random.shuffle(remaining)
                while len(team) < team_size and remaining:
                    team.append(remaining.pop())

            else:
                # ── 선 리더 전략 ──
                team = [leader.id]

                if leader.role == Role.MERLIN:
                    # 멀린: 자신이 아는 악(모드레드는 안 보임) + 투표로 탄로난 악을 피해서 선택
                    known_evil = _merlin_known_evil_ids(all_players) | confirmed_evil
                    believed_good = [
                        p.id for p in all_players
                        if p.id != leader.id and p.id not in known_evil
                    ]
                    believed_good = _weighted_order_by_trust(believed_good, trust)

                    # 90% 확률로 아는 악만 피해서 넣기 (10%는 일부러 섞어서 정체 숨기기)
                    if random.random() < 0.9:
                        while len(team) < team_size and believed_good:
                            team.append(believed_good.pop())
                    else:
                        # 약간의 블러핑 - 너무 정확하게만 뽑으면 들키므로 일부러 섞는다
                        others = [p.id for p in all_players if p.id != leader.id]
                        random.shuffle(others)
                        while len(team) < team_size and others:
                            team.append(others.pop())

                elif leader.role == Role.PERCIVAL:
                    # 퍼시벌: 멀린/모르가나 중 진짜 멀린이라 판단되는 쪽을 포함
                    merlin_morgana = [
                        p.id for p in all_players
                        if p.role in (Role.MERLIN, Role.MORGANA)
                    ]
                    believed_merlin = _percival_guess_merlin_id(
                        merlin_morgana, quest_history
                    )
                    if believed_merlin is not None:
                        team.append(believed_merlin)

                    # 확정된 악은 최대한 피해서 나머지를 채운다 (성공한 조합 우선)
                    others = [
                        p.id for p in all_players
                        if p.id not in team and p.id not in confirmed_evil
                    ]
                    others = _weighted_order_by_trust(others, trust)
                    while len(team) < team_size and others:
                        team.append(others.pop())

                    # 그래도 부족하면 어쩔 수 없이 확정 악도 포함
                    last_resort = [p.id for p in all_players if p.id not in team]
                    random.shuffle(last_resort)
                    while len(team) < team_size and last_resort:
                        team.append(last_resort.pop())

                else:
                    # 충신: 투표 기록으로 의심되는 사람은 피하고, 확정된 악은 절대 피함.
                    # 과거에 함께 성공시킨 조합이 있으면 그 사람들을 우선 다시 부른다.
                    suspicious = _get_suspicious_ids(quest_history, all_players)
                    safe = [
                        p.id for p in all_players
                        if p.id != leader.id and p.id not in suspicious
                    ]
                    safe = _weighted_order_by_trust(safe, trust)
                    while len(team) < team_size and safe:
                        team.append(safe.pop())

                    # 부족하면 의심자 중에서 채우되, 확정 악은 최후의 순간까지 피한다
                    remaining = [
                        pid for pid in player_ids
                        if pid not in team and pid not in confirmed_evil
                    ]
                    random.shuffle(remaining)
                    while len(team) < team_size and remaining:
                        team.append(remaining.pop())

                    # 그래도 부족하면 어쩔 수 없이 확정 악도 포함
                    last_resort = [pid for pid in player_ids if pid not in team]
                    random.shuffle(last_resort)
                    while len(team) < team_size and last_resort:
                        team.append(last_resort.pop())

            return team[:team_size]

        team = _build_once()

        # 선 리더라면, 과거 기록상 "이 조합엔 반드시 악이 있다"고 확정되는
        # 조합은 최대한 피하도록 몇 번 더 시도해본다 (완전히 피할 방법이
        # 없으면 마지막 시도를 그대로 사용한다).
        if leader.is_good:
            for _ in range(6):
                if _min_forced_evil_overlap(team, quest_history) == 0:
                    break
                team = _build_once()

        return team

    # ================================================================
    #  팀 투표 (찬성/반대)
    # ================================================================

    @staticmethod
    def vote_team(
        player: Player,
        team_ids: List[int],
        all_players: List[Player],
        rejection_count: int,
        quest_history: List[dict],
        leader_id: Optional[int] = None,
    ) -> Vote:
        """원정대에 대한 투표를 결정한다."""

        # 5번째 거부면 무조건 찬성 (악의 자동 승리 방지)
        if rejection_count >= 4:
            return Vote.APPROVE

        # 투표 기록으로 100% 확정된 악 (2인 원정대에서 둘 다 실패)
        confirmed_evil = _get_confirmed_evil_ids(quest_history)

        completed_success_count = sum(1 for h in quest_history if h.get("result") == "성공")
        completed_fail_count = sum(1 for h in quest_history if h.get("result") == "실패")

        if player.is_evil:
            # ── 악 전략 ──
            # 악은 팀에 악(자신 포함)이 있으면 원정대를 찬성해야 실패를 낼 기회가 생긴다.
            evil_in_team = any(
                p.id in team_ids for p in all_players if p.is_evil
            )
            if evil_in_team:
                approve_prob = 0.85
                # 다른 사람들이 나를 악으로 볼 수 있으므로, 이미 의심/탄로난 상황이면
                # 너무 티나게 계속 찬성만 하지 않도록 확률을 낮춘다
                if player.id in confirmed_evil:
                    approve_prob = 0.55
                elif any(pid in confirmed_evil for pid in team_ids):
                    approve_prob = 0.65
                return Vote.APPROVE if random.random() < approve_prob else Vote.REJECT
            else:
                # 이번 퀘스트가 성공하면 곧바로 선의 승리가 확정되는데(이미 성공 2개)
                # 이 팀엔 악이 하나도 없어서 실패를 낼 수가 없다. 통과시키면 그대로
                # 게임이 끝나버리므로, 막을 수 있는 유일한 방법인 투표 거부에
                # 최대한 매달려야 한다.
                if completed_success_count >= cfg.QUESTS_TO_WIN - 1:
                    return Vote.REJECT if random.random() < 0.95 else Vote.APPROVE
                # 악이 없으면 반대 (하지만 너무 반대만 하면 의심)
                return Vote.REJECT if random.random() < 0.7 else Vote.APPROVE
        else:
            # ── 선 전략 ──
            # 확정된 악이 팀에 있다면 그 무엇보다 우선해서 반대한다
            if any(pid in confirmed_evil for pid in team_ids):
                return Vote.REJECT if random.random() < 0.97 else Vote.APPROVE

            # 특정 개인까진 아니어도, 과거 원정대 기록과의 겹침만으로 "이 조합엔
            # 최소 1명의 악이 반드시 있다"가 논리적으로 확정되는 경우도 있다.
            # 예: 3인 원정대에서 실패가 2개 나왔다면 그 팀의 선은 최대 1명이므로,
            # 그중 아무 2명을 다시 묶은 새 원정대도 반드시 악을 1명 이상 포함한다.
            if _min_forced_evil_overlap(team_ids, quest_history) >= 1:
                return Vote.REJECT if random.random() < 0.95 else Vote.APPROVE

            # 인원수만으로도 확정할 수 있는 경우: 내가 선인데 이 원정대에
            # 빠져 있고, 남은 선 인원만으로는 이 팀 크기를 채울 수 없다면
            # (비둘기집 원리) 그 팀에는 무조건 악이 껴 있다는 뜻이다.
            # 예: 5인 게임(선3/악2)에서 나를 뺀 3인 원정대는 나를 제외한
            # 선이 2명뿐이므로 반드시 악이 최소 1명 포함된다.
            if player.id not in team_ids:
                good_count, _evil_count = cfg.TEAM_COMPOSITION.get(len(all_players), (0, 0))
                other_good_available = good_count - 1
                if good_count and len(team_ids) > other_good_available:
                    return Vote.REJECT if random.random() < 0.95 else Vote.APPROVE

            # 내가 이 원정대를 짠 리더라면, 이미 스스로 고민해서 구성한
            # 팀이므로 반대할 이유가 거의 없다 (역할별 판단보다 우선).
            if leader_id is not None and player.id == leader_id:
                return Vote.APPROVE if random.random() < 0.92 else Vote.REJECT

            # 멀린: 자신이 아는 악(모드레드는 안 보임)이 팀에 있는지로 판단.
            # 다만 매 투표마다 "실패한 팀엔 반대, 성공한 팀엔 찬성"을 너무 정확히
            # 반복하면 그 상관관계만으로 정체가 드러난다. 그래서 게임이 걸린
            # 순간이 아니면 판단을 일부러 흐려서 패턴 자체를 숨긴다.
            if player.role == Role.MERLIN:
                known_evil = _merlin_known_evil_ids(all_players)
                evil_in_team = any(pid in known_evil for pid in team_ids)
                game_deciding = completed_fail_count >= cfg.QUESTS_TO_WIN - 1

                if game_deciding:
                    # 악이 한 번만 더 실패시키면 지는 상황에서는 들킬 위험보다
                    # 승리가 훨씬 중요하므로 아는 정보를 분명하게 활용한다.
                    if evil_in_team:
                        return Vote.REJECT if random.random() < 0.85 else Vote.APPROVE
                    return Vote.APPROVE if random.random() < 0.95 else Vote.REJECT

                # 평소에는 가끔(20%) 아는 정보를 일부러 무시하고, 정보가 없는
                # 평범한 선과 똑같은 기준으로 판단해서 투표 패턴에 잡음을 섞는다.
                if random.random() < 0.2:
                    base = 0.6 - _early_game_skepticism(quest_history)
                    return Vote.APPROVE if random.random() < base else Vote.REJECT

                if evil_in_team:
                    return Vote.REJECT if random.random() < 0.6 else Vote.APPROVE
                else:
                    return Vote.APPROVE if random.random() < 0.75 else Vote.REJECT

            # 퍼시벌: 진짜 멀린이라 판단되는 사람이 팀에 있는지로 판단
            if player.role == Role.PERCIVAL:
                merlin_morgana = [
                    p.id for p in all_players
                    if p.role in (Role.MERLIN, Role.MORGANA)
                ]
                believed_merlin = _percival_guess_merlin_id(
                    merlin_morgana, quest_history
                )
                if believed_merlin is not None and believed_merlin in team_ids:
                    return Vote.APPROVE if random.random() < 0.85 else Vote.REJECT

            # 이번 퀘스트가 실패하면 곧바로 악의 승리가 확정되는데(이미 실패 2개)
            # 내가 이 원정대에 없어서 안에 악이 있는지 확인할 방법이 없다면,
            # 어설프게 믿고 넘어가기엔 결과가 너무 크므로 훨씬 더 적극적으로 반대한다.
            if player.id not in team_ids and completed_fail_count >= cfg.QUESTS_TO_WIN - 1:
                return Vote.REJECT if random.random() < 0.9 else Vote.APPROVE

            if player.id in team_ids:
                # 자기가 팀에 있으면 찬성 경향 (뚜렷한 반대 근거가 없을 때만)
                return Vote.APPROVE if random.random() < 0.8 else Vote.REJECT

            # 퍼시벌(판단 불가시)/충신: 투표 기록 기반 의심도로 판단
            suspicious = _get_suspicious_ids(quest_history, all_players)
            suspicious_in_team = any(pid in team_ids for pid in suspicious)
            if suspicious_in_team:
                return Vote.REJECT if random.random() < 0.65 else Vote.APPROVE

            # 과거에 성공시킨 원정대원이 여럿 겹치면 그만큼 신뢰도를 높인다.
            # (다만 악이 성공한 척 속였을 수도 있으니 100%는 아니다)
            trust = _success_trust_scores(quest_history)
            trusted_in_team = sum(1 for pid in team_ids if trust.get(pid, 0) > 0)
            if trusted_in_team >= 2:
                return Vote.APPROVE if random.random() < 0.85 else Vote.REJECT

            # 뚜렷한 근거가 없을 때의 기본 성향. 게임 초반에는 아직 아무런
            # 검증(투표 기록)도 없는 상태이므로, 너무 쉽게 찬성해버리면
            # 여러 번 재편성을 거치며 서로의 투표 패턴을 관찰할 기회 자체가
            # 사라진다. 그래서 초반일수록 더 신중하게(자주 반대) 판단하다가,
            # 퀘스트 기록이 쌓일수록 원래 성향으로 돌아온다.
            approve_prob = 0.6 - _early_game_skepticism(quest_history)
            return Vote.APPROVE if random.random() < approve_prob else Vote.REJECT

    # ================================================================
    #  퀘스트 수행 (성공/실패)
    # ================================================================

    @staticmethod
    def quest_vote(
        player: Player,
        quest_number: int,
        success_count: int,
        fail_count: int,
        team_ids: List[int],
        all_players: List[Player],
        requires_double_fail: bool = False,
    ) -> QuestVote:
        """퀘스트에서 성공/실패를 결정한다."""
        if player.is_good:
            # 선은 항상 성공
            return QuestVote.SUCCESS

        # ── 악 전략 ──
        evil_teammates = [
            p for p in all_players
            if p.id in team_ids and p.is_evil and p.id != player.id
        ]

        # 이번 퀘스트가 실패하면 곧바로 악의 승리가 확정되는 상황(이미 실패 2개)
        # 이라면, 정체를 숨기는 것보다 승리가 훨씬 중요하므로 무조건 실패를 낸다.
        # (게임이 그 즉시 끝나버리므로 나중에 들통날 걱정을 할 필요가 없다.)
        game_deciding = fail_count >= cfg.QUESTS_TO_WIN - 1
        if game_deciding:
            return QuestVote.FAIL

        # 원정대에 악이 여럿(자신 포함) 있으면, 필요한 수보다 많이 실패를 내는
        # 순간 그만큼 정체가 드러날 위험이 커진다. 그래서 이번 퀘스트를
        # 실패시키는 데 필요한 인원만 "실패 담당"으로 정하고 나머지는 성공을
        # 내서 정체를 지킨다. 담당자는 정체를 들켜도 상대적으로 덜 아까운
        # 역할(암살자/하수인) 먼저, 그다음 모르가나, 마지막으로 모드레드
        # 순으로 정한다 - 위장 능력이 있는 역할일수록 최대한 아낀다.
        if evil_teammates:
            fails_needed = 2 if requires_double_fail else 1
            evil_on_team = evil_teammates + [player]
            ranked = sorted(
                evil_on_team,
                key=lambda p: (_expose_priority(p.role), p.id),
            )
            designated_ids = {p.id for p in ranked[:fails_needed]}
            if player.id not in designated_ids:
                return QuestVote.SUCCESS
            # 담당자는 아래 일반 판단을 따른다 (매번 실패는 아니게 헷갈리게 낸다)

        # 초반에는 성공으로 위장할 수도 있음
        if quest_number == 1 and random.random() < 0.3:
            return QuestVote.SUCCESS  # 30% 확률로 1차 퀘스트 위장

        # 기본적으로 실패, 하지만 매번 확정적이지 않도록 약간의 성공도 섞는다
        return QuestVote.SUCCESS if random.random() < 0.15 else QuestVote.FAIL

    # ================================================================
    #  암살자: 멀린 지목
    # ================================================================

    @staticmethod
    def choose_merlin(
        assassin: Player,
        all_players: List[Player],
        quest_history: List[dict],
    ) -> int:
        """암살자가 멀린을 지목한다.

        Returns:
            지목한 player_id
        """
        good_players = [p for p in all_players if p.is_good]

        if not good_players:
            return all_players[0].id

        # 퀘스트에서 정확하게 투표한 사람이 멀린일 가능성 높음
        # 간단한 전략: 선 중 가장 "정확하게" 반대한 사람
        suspicion: Dict[int, float] = {p.id: 0.0 for p in good_players}

        for hist in quest_history:
            team_ids = hist.get("team_ids", [])
            result = hist.get("result")
            votes = hist.get("team_votes", {})

            for p in good_players:
                pid = p.id
                vote = votes.get(pid)
                if vote is None:
                    continue

                if result == "실패":
                    # 실패한 퀘스트에 반대했으면 → 멀린 의심
                    if vote == "반대":
                        suspicion[pid] += 2.0
                elif result == "성공":
                    # 성공한 퀘스트에 찬성했으면 → 약간 의심
                    if vote == "찬성":
                        suspicion[pid] += 0.5

        # 가장 의심되는 사람 (랜덤성 추가)
        for pid in suspicion:
            suspicion[pid] += random.random() * 1.5

        if suspicion:
            return max(suspicion, key=lambda x: suspicion[x])

        return random.choice(good_players).id


def _get_suspicious_ids(
    quest_history: List[dict],
    all_players: List[Player],
) -> List[int]:
    """퀘스트 기록에서 의심되는 플레이어를 찾는다."""
    suspicious = set()

    for hist in quest_history:
        if hist.get("result") == "실패":
            team_ids = hist.get("team_ids", [])
            for pid in team_ids:
                suspicious.add(pid)

    return list(suspicious)
