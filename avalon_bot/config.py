import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# ── 게임 설정 ──
MIN_PLAYERS = 5
MAX_PLAYERS = 10

# 인원별 선/악 비율
TEAM_COMPOSITION = {
    5:  (3, 2),
    6:  (4, 2),
    7:  (4, 3),
    8:  (5, 3),
    9:  (6, 3),
    10: (6, 4),
}

# 인원별 퀘스트 팀 크기
QUEST_SIZES = {
    5:  [2, 3, 2, 3, 3],
    6:  [2, 3, 4, 3, 4],
    7:  [2, 3, 3, 4, 4],
    8:  [3, 4, 4, 5, 5],
    9:  [3, 4, 4, 5, 5],
    10: [3, 4, 4, 5, 5],
}

# 4번째 퀘스트에서 실패 2개 필요한 최소 인원
DOUBLE_FAIL_MIN_PLAYERS = 7

# 연속 투표 거부 시 악의 승리
MAX_REJECTIONS = 5

# 총 퀘스트 수
TOTAL_QUESTS = 5

# 승리에 필요한 퀘스트 수
QUESTS_TO_WIN = 3
