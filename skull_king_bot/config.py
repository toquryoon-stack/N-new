import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# Game settings
MIN_PLAYERS = 2
MAX_PLAYERS = 6
TOTAL_ROUNDS = 10

# Scoring
POINTS_PER_TRICK_WON = 20
POINTS_PER_TRICK_MISSED = 10
ZERO_BID_MULTIPLIER = 10
SKULL_KING_CAPTURE_BONUS = 30  # SK captures pirate
MERMAID_CAPTURE_BONUS = 50     # Mermaid captures SK
LOOT_ALLIANCE_BONUS = 20      # Both allies hit bid
