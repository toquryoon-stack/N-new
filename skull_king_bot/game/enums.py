"""열거형 정의 - 게임 모드, 카드 타입, 색상, 해적 이름 등"""

from enum import Enum, auto


class GameMode(Enum):
    """게임 모드"""
    BASIC = "basic"
    LEGENDARY = "legendary"

    @property
    def display_name(self) -> str:
        return "기본판" if self == GameMode.BASIC else "확장판"


class GameState(Enum):
    """게임 진행 상태"""
    WAITING = auto()       # 플레이어 참가 대기
    BIDDING = auto()       # 비딩 단계
    PLAYING = auto()       # 트릭 진행 중
    ROUND_END = auto()     # 라운드 종료 (점수 표시)
    GAME_OVER = auto()     # 게임 종료


class CardType(Enum):
    """카드 종류"""
    NUMBER = "number"
    ESCAPE = "escape"
    PIRATE = "pirate"
    SKULL_KING = "skull_king"
    MERMAID = "mermaid"
    TIGRESS = "tigress"
    LOOT = "loot"
    KRAKEN = "kraken"
    WHITE_WHALE = "white_whale"
    SHRIMP = "shrimp"       # 🦐 새우 (커스텀)


class Suit(Enum):
    """숫자 카드 색상"""
    RED = "red"
    YELLOW = "yellow"
    BLUE = "blue"
    BLACK = "black"         # 트럼프 슈트


class PirateName(Enum):
    """해적 이름 (확장판 능력 연결)"""
    ROSIE = "rosie"         # 다음 리드 지목
    BAHIJ = "bahij"         # 2장 드로우 + 2장 버리기
    JUANITA = "juanita"     # 안 나온 카드 확인
    HARRY = "harry"         # 비딩 ±1 변경
    RASCAL = "rascal"       # 추가 베팅 (10/20점)


class TigressChoice(Enum):
    """타이그리스 선택"""
    PIRATE = "pirate"
    ESCAPE = "escape"
