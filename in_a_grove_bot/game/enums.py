"""열거형 정의"""

from enum import Enum, auto


class GameState(Enum):
    WAITING = auto()       # 로비 대기
    DEALING = auto()       # 타일 배분
    PASSING = auto()       # 타일 전달
    DISCOVERING = auto()   # 발견자 특권
    ACCUSING = auto()      # 고발 단계
    REVEALING = auto()     # 공개 & 판정
    ROUND_END = auto()     # 라운드 종료
    GAME_OVER = auto()     # 게임 종료
