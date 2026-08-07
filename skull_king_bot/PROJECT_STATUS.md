# Skull King Discord Bot - Project Status

## Project Overview
Discord channel-based card game bot implementing the board game "Skull King" with expansion rules + custom card.

- **Language**: Python 3 + discord.py v2.x
- **Location**: `skull_king_bot/`
- **Start Date**: 2026-08-07

---

## Completed Features

### 1. Core Game Logic (100%)
| File | Description | Status |
|------|------------|--------|
| `game/enums.py` | GameMode, CardType, Suit, PirateName, TigressChoice enums | Done |
| `game/cards.py` | Card class with emoji display, suit detection, uid | Done |
| `game/deck.py` | Mode-based deck creation (Basic: 68 / Legendary: 75 cards), shuffle, deal | Done |
| `game/player.py` | Player state (hand, bid, tricks, scores, is_ai flag) | Done |
| `game/trick.py` | Trick resolution with full priority chain | Done |
| `game/scoring.py` | Round score calculation with all bonuses | Done |
| `game/game.py` | Game state machine + GameManager (channel-based) | Done |
| `game/ai.py` | AI player logic (AIUser mock, AIStrategy decisions) | Done |

### 2. UI Layer (100%)
| File | Description | Status |
|------|------------|--------|
| `ui/embeds.py` | 10+ embed types (lobby, hand, bidding, trick, scores, etc.) | Done |
| `ui/views.py` | 12 view classes (mode select, lobby, bidding, card select, pirate abilities, etc.) | Done |

### 3. Bot Entry Point (100%)
| File | Description | Status |
|------|------------|--------|
| `bot.py` | Slash command `/skull_king`, full game loop, AI turn handling | Done |
| `config.py` | Settings (scoring values, player limits) | Done |
| `requirements.txt` | discord.py>=2.3.0, python-dotenv>=1.0.0 | Done |
| `.env.example` | DISCORD_TOKEN placeholder | Done |

---

## Game Modes

### Basic Mode (68 cards)
- Number cards: 1-14 x 4 suits (56)
- Escape: 5
- Pirate: 5 (no abilities)
- Skull King: 1
- Shrimp (custom): 1

### Legendary/Expansion Mode (75 cards)
- All Basic cards +
- Mermaid: 2 (beats SK, loses to Pirates)
- Tigress: 1 (player chooses Pirate or Escape)
- Loot: 2 (alliance bonus)
- Kraken: 1 (destroys trick)
- White Whale: 1 (nullifies specials, highest number wins)
- Pirates gain unique abilities (Rosie, Bahij, Juanita, Harry, Rascal)

---

## Custom Card: Shrimp (New)

| Property | Value |
|----------|-------|
| Name | Shrimp / New |
| Count | 1 |
| Available in | Both modes |
| Combat power | None (like Escape) |
| Effect | Lowest number card wins the trick |
| Priority | HIGHEST (overrides Kraken, White Whale, everything) |
| If no number cards | No winner (like Kraken) |

### Shrimp Interaction Rules
```
Shrimp + number cards     -> lowest number wins
Shrimp + Kraken           -> Kraken nullified, lowest number wins
Shrimp + White Whale      -> White Whale nullified, lowest number wins
Shrimp + Pirates/SK/Mermaid -> specials can't win (no number value)
Shrimp + only specials    -> no winner
```

---

## Trick Resolution Priority (trick.py)

```
1. Shrimp      -> lowest number wins (overrides ALL)
2. Kraken + White Whale -> last played card's effect applies
3. Kraken      -> trick destroyed, no winner
4. White Whale -> specials nullified, highest number wins
5. Normal:
   a. Mermaid vs Skull King (Legendary) -> Mermaid wins (+50 bonus)
   b. Skull King -> beats all pirates (+30 per pirate captured)
   c. Mermaid alone (Legendary) -> loses to pirates, beats numbers
   d. Pirates -> beat all number cards (first pirate wins)
   e. Number cards -> Black(trump) > lead suit > off-suit, higher value wins
   f. All escapes -> no winner
```

---

## Scoring System

| Condition | Points |
|-----------|--------|
| 0 bid success | +round_number x 10 |
| 0 bid failure | -round_number x 10 |
| N bid success (N>=1) | +N x 20 |
| Bid failure | -|difference| x 10 |
| SK captures pirate | +30 per pirate |
| Mermaid captures SK | +50 |
| Loot alliance (both hit bid) | +20 each |
| Rascal wager (hit) | +wager |
| Rascal wager (miss) | -wager |

---

## AI Player System

### Architecture
- `AIUser` class mocks `discord.User` (id, display_name, async send() no-op)
- `AIStrategy` class provides static methods for all decisions
- `Player.is_ai` flag distinguishes AI from human
- `Game.add_ai_player()` / `remove_ai_player()` manage AI in lobby

### AI Strategy
| Decision | Method |
|----------|--------|
| Bidding | Hand strength analysis (SK=0.9, Pirate=0.8, Black14=0.85, etc.) + randomness |
| Card play (need tricks) | Strongest card / minimum winning card |
| Card play (don't need) | Weakest card / escape first |
| Tigress | Need tricks -> Pirate, else -> Escape |
| Rosie | Random target (prefer others) |
| Bahij | Random 2 cards to discard |
| Harry | Over-bid -> -1, Under-bid -> +1 |
| Rascal | Close to bid -> 20pts, far -> 10pts |

### AI Turn Flow in bot.py
- Bidding: `AIStrategy.calculate_bid()` with 0.5-1.5s delay
- Card select: `AIStrategy.choose_card()` with 0.8-2.0s delay
- Tigress/Pirate abilities: instant auto-decision
- DM sending: silently skipped (AIUser.send() is no-op)

---

## Game Flow (bot.py)

```
/skull_king command
  -> Mode select (Basic / Legendary)
  -> Lobby (Join / Leave / Add AI / Remove AI / Start)
  -> For each round (1-10):
       -> Deal cards (round_number cards each)
       -> DM hands to human players
       -> Bidding phase (concurrent, AI auto-bids)
       -> For each trick:
            -> Each player plays card (DM select / AI auto)
            -> Tigress choice if applicable
            -> Channel: show played cards
            -> Resolve trick winner
            -> Pirate ability if applicable (Legendary)
       -> Calculate & show round scores
       -> Next round button
  -> Final results + rankings
  -> Restart / End
```

---

## File Structure

```
skull_king_bot/
+-- bot.py              (22.9KB) Main bot + slash commands + game loop
+-- config.py           (0.4KB)  Settings
+-- requirements.txt             Dependencies
+-- .env.example                 Token template
+-- PROJECT_STATUS.md            This file
|
+-- game/
|   +-- __init__.py              Package exports
|   +-- enums.py        (1.5KB)  Enumerations
|   +-- cards.py        (5.7KB)  Card class
|   +-- deck.py         (2.7KB)  Deck creation
|   +-- player.py       (4.0KB)  Player state
|   +-- ai.py           (12.4KB) AI logic
|   +-- trick.py        (16.9KB) Trick resolution
|   +-- scoring.py      (3.6KB)  Score calculation
|   +-- game.py         (13.0KB) Game state machine
|
+-- ui/
    +-- __init__.py              Package exports
    +-- embeds.py       (14.0KB) Discord embeds
    +-- views.py        (14.2KB) Discord UI components
```

---

## Setup Instructions

```bash
# 1. Install Python 3.10+
# 2. Install dependencies
pip install -r requirements.txt

# 3. Create .env file
cp .env.example .env
# Edit .env -> DISCORD_TOKEN=your_bot_token_here

# 4. Discord Developer Portal setup
# - Create application at https://discord.com/developers/applications
# - Bot tab -> enable MESSAGE CONTENT INTENT, SERVER MEMBERS INTENT
# - OAuth2 -> URL Generator -> scopes: bot, applications.commands
# - Bot permissions: Send Messages, Use Slash Commands, Embed Links
# - Copy invite URL and add bot to your server

# 5. Run
python bot.py
```

---

## Known Limitations / Future Improvements

### Not Yet Implemented
- [ ] Persistent score history (database)
- [ ] Multiple concurrent games across servers
- [ ] Spectator mode
- [ ] Game replay / log export
- [ ] AI difficulty levels (Easy / Normal / Hard)
- [ ] Card art / image generation for hands
- [ ] Localization (English support)

### Potential Issues to Watch
- Discord DM must be enabled for human players (bot warns if blocked)
- Timeout handling: auto-selects first valid card / 0 bid on timeout (2 min)
- AI delay is randomized (0.5-2.0s) to feel natural
- Max 6 players per game (any mix of human + AI)
- One game per channel at a time

---

## Key Design Decisions

1. **DM for private info**: Hand cards and bidding done via DM to keep information secret
2. **Channel for public**: Trick results, scores, game status shown in channel
3. **Concurrent bidding**: All players bid simultaneously via asyncio.gather
4. **AI as mock User**: AIUser mimics discord.User interface so existing code works without branching
5. **Mode selection at game creation**: Basic/Legendary chosen once, affects deck and trick resolution
6. **Shrimp overrides everything**: Simplest rule - if Shrimp is in the trick, only numbers matter, lowest wins
