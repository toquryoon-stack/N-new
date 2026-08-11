"""열거형 정의 - 아발롬"""

from enum import Enum, auto


class GameState(Enum):
    WAITING = auto()        # 로비 대기
    NIGHT = auto()          # 밤 단계 (역할 공개)
    TEAM_BUILD = auto()     # 원정대 편성
    TEAM_VOTE = auto()      # 원정대 투표 (찬성/반대)
    QUEST = auto()          # 퀘스트 수행 (성공/실패)
    ASSASSIN = auto()       # 암살자 단계 (멀린 지목)
    GAME_OVER = auto()      # 게임 종료


class Team(Enum):
    GOOD = "선"
    EVIL = "악"


class Role(Enum):
    # ── 선의 진영 ──
    MERLIN = "멀린"
    PERCIVAL = "퍼시벌"
    LOYAL_SERVANT = "아서의 충신"

    # ── 악의 진영 ──
    ASSASSIN = "암살자"
    MORGANA = "모르가나"
    MINION = "모드레드의 하수인"
    MORDRED = "모드레드"


class Vote(Enum):
    APPROVE = "찬성"
    REJECT = "반대"


class QuestVote(Enum):
    SUCCESS = "성공"
    FAIL = "실패"


class QuestResult(Enum):
    SUCCESS = "성공"
    FAIL = "실패"
    PENDING = "진행중"
