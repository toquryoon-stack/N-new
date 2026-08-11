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


def _score_merlin_candidates(
    candidate_ids: List[int],
    quest_history: List[dict],
) -> Dict[int, float]:
    """퍼시벌이 멀린/모르가나 후보 중 누가 진짜 멀린에 가까운지 점수를 매긴다.

    단서: 실패한 퀘스트에 반대표를 던졌다면 멀린일 가능성이 높고
    (실제 멀린은 악이 낀 팀을 미리 알아채고 반대하는 경향이 있음),
    성공한 퀘스트에 찬성표를 던진 것도 약한 단서로 취급한다.
    완전한 확신은 주지 않도록 무작위성을 더한다.
    """
    score: Dict[int, float] = {pid: 0.0 for pid in candidate_ids}

    for hist in quest_history:
        result = hist.get("result")
        votes = hist.get("team_votes", {})

        for pid in candidate_ids:
            vote = votes.get(pid)
            if vote is None:
                continue

            if result == "실패" and vote == "반대":
                score[pid] += 1.5
            elif result == "성공" and vote == "찬성":
                score[pid] += 0.4

    # 퍼시벌은 확신할 수 없으므로 약간의 불확실성을 더한다.
    for pid in score:
        score[pid] += random.random() * 1.3

    return score


def _get_confirmed_evil_ids(quest_history: List[dict]) -> set:
    """투표 결과만으로 100% 확정할 수 있는 악을 찾는다.

    2인 원정대에서 실패가 2개 나왔다면, 그 2명 모두 실패를 냈다는 뜻이고
    선은 절대 실패를 낼 수 없으므로 둘 다 확정적으로 악이다.
    이 정보는 (인간이든 AI든) 누구나 공개된 결과만 보고 알 수 있으므로
    멀린을 포함한 모든 선 진영이 활용할 수 있다 - 심지어 모드레드처럼
    멀린에게 원래 안 보이는 악도 이렇게 들키면 정체가 드러난다.
    """
    confirmed = set()
    for hist in quest_history:
        team_ids = hist.get("team_ids", [])
        if len(team_ids) == 2 and hist.get("fail_count", 0) == 2:
            confirmed.update(team_ids)
    return confirmed


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
        player_ids = [p.id for p in all_players]
        confirmed_evil = _get_confirmed_evil_ids(quest_history)

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
                random.shuffle(believed_good)

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

                # 확정된 악은 최대한 피해서 나머지를 채운다
                others = [
                    p.id for p in all_players
                    if p.id not in team and p.id not in confirmed_evil
                ]
                random.shuffle(others)
                while len(team) < team_size and others:
                    team.append(others.pop())

                # 그래도 부족하면 어쩔 수 없이 확정 악도 포함
                last_resort = [p.id for p in all_players if p.id not in team]
                random.shuffle(last_resort)
                while len(team) < team_size and last_resort:
                    team.append(last_resort.pop())

            else:
                # 충신: 투표 기록으로 의심되는 사람은 피하고, 확정된 악은 절대 피함
                suspicious = _get_suspicious_ids(quest_history, all_players)
                safe = [
                    p.id for p in all_players
                    if p.id != leader.id and p.id not in suspicious
                ]
                random.shuffle(safe)
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
    ) -> Vote:
        """원정대에 대한 투표를 결정한다."""

        # 5번째 거부면 무조건 찬성 (악의 자동 승리 방지)
        if rejection_count >= 4:
            return Vote.APPROVE

        # 투표 기록으로 100% 확정된 악 (2인 원정대에서 둘 다 실패)
        confirmed_evil = _get_confirmed_evil_ids(quest_history)

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
                # 악이 없으면 반대 (하지만 너무 반대만 하면 의심)
                return Vote.REJECT if random.random() < 0.7 else Vote.APPROVE
        else:
            # ── 선 전략 ──
            # 확정된 악이 팀에 있다면 그 무엇보다 우선해서 반대한다
            if any(pid in confirmed_evil for pid in team_ids):
                return Vote.REJECT if random.random() < 0.97 else Vote.APPROVE

            # 멀린: 자신이 아는 악(모드레드는 안 보임)이 팀에 있는지로 판단
            if player.role == Role.MERLIN:
                known_evil = _merlin_known_evil_ids(all_players)
                evil_in_team = any(pid in known_evil for pid in team_ids)
                if evil_in_team:
                    # 반대하되, 너무 정확하면 들킴
                    return Vote.REJECT if random.random() < 0.8 else Vote.APPROVE
                else:
                    return Vote.APPROVE if random.random() < 0.9 else Vote.REJECT

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

            if player.id in team_ids:
                # 자기가 팀에 있으면 찬성 경향 (뚜렷한 반대 근거가 없을 때만)
                return Vote.APPROVE if random.random() < 0.8 else Vote.REJECT

            # 퍼시벌(판단 불가시)/충신: 투표 기록 기반 의심도로 판단
            suspicious = _get_suspicious_ids(quest_history, all_players)
            suspicious_in_team = any(pid in team_ids for pid in suspicious)
            if suspicious_in_team:
                return Vote.REJECT if random.random() < 0.65 else Vote.APPROVE
            return Vote.APPROVE if random.random() < 0.6 else Vote.REJECT

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
    ) -> QuestVote:
        """퀘스트에서 성공/실패를 결정한다."""
        if player.is_good:
            # 선은 항상 성공
            return QuestVote.SUCCESS

        # ── 악 전략 ──
        evil_teammates = [
            p.id for p in all_players
            if p.id in team_ids and p.is_evil and p.id != player.id
        ]

        # 2인 원정대에 악이 둘(자신 포함) 있으면, 둘 다 실패를 내는 순간
        # "실패 2개 = 둘 다 악"이라는 사실이 그대로 공개되어 정체가 탄로난다.
        # 따라서 반드시 한 명만 실패 담당을 맡도록 조율한다 (id가 작은 쪽 담당).
        if len(team_ids) == 2 and evil_teammates:
            designated_failer = min(player.id, *evil_teammates)
            if player.id != designated_failer:
                return QuestVote.SUCCESS
            # 담당자는 아래 일반 판단을 따른다 (매번 실패는 아니게 헷갈리게 낸다)

        # 초반에는 성공으로 위장할 수도 있음
        if quest_number == 1 and random.random() < 0.3:
            return QuestVote.SUCCESS  # 30% 확률로 1차 퀘스트 위장

        # 이미 2개 실패했으면 성공해서 의심 피하기
        if fail_count >= 2 and random.random() < 0.4:
            return QuestVote.SUCCESS

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
