import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# Game settings
MIN_PLAYERS = 2
MAX_PLAYERS = 5
MAX_ROUNDS = 7
STARTING_CHIPS = 7
LOSE_CHIP_THRESHOLD = 8   # 총 칩 8개 이상이면 패배
