"""게임 상태 머신 - 전체 게임 흐름 관리"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import discord

from .enums import GameMode, GameState, CardType, Suit, PirateName, TigressChoice
from .cards import Card
from .deck import Deck
from .player import Player
from .ai import AIUser, AIStrategy, get_next_ai_name, reset_ai_names
from .trick import TrickResolver, TrickResult, PlayedCard, determine_lead_suit
from .scoring import calculate_round_scores
import config as cfg


class Game:
    """스컬킹 게임 인스턴스

    하나의 디스코드 채널에서 하나의 게임이 진행된다.
    """

    def __init__(self, channel_id: int, host: discord.User, mode: GameMode):
        self.channel_id = channel_id
        self.host = host
        self.mode = mode
        self.state = GameState.WAITING

        # ── 플레이어 ──
        self.players: Dict[int, Player] = {}
        self.player_order: List[int] = []   # 플레이어 ID 순서

        # ── 라운드 ──
        self.current_round: int = 0
        self.deck: Optional[Deck] = None
        self.remaining_cards: List[Card] = []  # 후아니타 능력용

        # ── 트릭 ──
        self.current_trick: int = 0
        self.trick_cards: List[PlayedCard] = []
        self.current_player_idx: int = 0     # player_order 내 인덱스
        self.lead_player_id: Optional[int] = None
        self.trick_resolver = TrickResolver(mode)

        # ── 메시지 참조 (UI 업데이트용) ──
        self.lobby_message: Optional[discord.Message] = None
        self.game_message: Optional[discord.Message] = None

    # ================================================================
    #  로비 관리
    # ================================================================

    def add_player(self, user: discord.User) -> bool:
        """플레이어 참가. 성공하면 True."""
        if user.id in self.players:
            return False
        if len(self.players) >= cfg.MAX_PLAYERS:
            return False
        if self.state != GameState.WAITING:
            return False

        self.players[user.id] = Player(user=user)
        self.player_order.append(user.id)
        return True

    def remove_player(self, user_id: int) -> bool:
        """플레이어 퇴장."""
        if user_id not in self.players:
            return False
        del self.players[user_id]
        self.player_order.remove(user_id)
        return True

    def add_ai_player(self) -> Optional[Player]:
        """AI 플레이어를 추가한다. 성공하면 Player 반환."""
        if len(self.players) >= cfg.MAX_PLAYERS:
            return None
        if self.state != GameState.WAITING:
            return None

        ai_user = AIUser(get_next_ai_name())
        ai_player = Player(user=ai_user, is_ai=True)
        self.players[ai_user.id] = ai_player
        self.player_order.append(ai_user.id)
        return ai_player

    def remove_ai_player(self) -> bool:
        """마지막으로 추가된 AI 플레이어를 제거한다."""
        # 뒤에서부터 AI 찾기
        for pid in reversed(self.player_order):
            if self.players[pid].is_ai:
                del self.players[pid]
                self.player_order.remove(pid)
                return True
        return False

    @property
    def ai_count(self) -> int:
        return sum(1 for p in self.players.values() if p.is_ai)

    @property
    def human_count(self) -> int:
        return sum(1 for p in self.players.values() if not p.is_ai)

    def can_start(self) -> bool:
        return (
            self.state == GameState.WAITING
            and len(self.players) >= cfg.MIN_PLAYERS
        )

    @property
    def player_count(self) -> int:
        return len(self.players)

    @property
    def player_list(self) -> List[Player]:
        return [self.players[pid] for pid in self.player_order]

    # ================================================================
    #  라운드 관리
    # ================================================================

    def start_new_round(self) -> int:
        """새 라운드를 시작하고 라운드 번호를 반환한다."""
        self.current_round += 1
        self.current_trick = 0
        self.state = GameState.BIDDING

        # 플레이어 라운드 초기화
        for player in self.players.values():
            player.reset_round()

        # 덱 생성 & 카드 배분
        self.deck = Deck(self.mode)
        hands = self.deck.deal(self.current_round, self.player_count)

        # 남은 카드 저장 (후아니타 능력용)
        self.remaining_cards = self.deck.remaining

        # 손패 배분 & 정렬
        for i, pid in enumerate(self.player_order):
            self.players[pid].hand = hands[i]
            self.players[pid].sort_hand()

        # 시작 플레이어 로테이션 (라운드마다 돌아감)
        start_idx = (self.current_round - 1) % self.player_count
        self.lead_player_id = self.player_order[start_idx]

        return self.current_round

    # ================================================================
    #  비딩
    # ================================================================

    def set_bid(self, player_id: int, bid: int) -> bool:
        """플레이어의 비딩을 설정한다."""
        if self.state != GameState.BIDDING:
            return False
        if player_id not in self.players:
            return False
        if bid < 0 or bid > self.current_round:
            return False

        self.players[player_id].bid = bid
        return True

    def all_bids_in(self) -> bool:
        """모든 플레이어가 비딩했는지 확인."""
        return all(p.bid is not None for p in self.players.values())

    def modify_bid(self, player_id: int, delta: int) -> bool:
        """해리 능력: 비딩 ±1 변경."""
        player = self.players.get(player_id)
        if not player or player.bid is None:
            return False
        new_bid = player.bid + delta
        if new_bid < 0 or new_bid > self.current_round:
            return False
        player.bid = new_bid
        player.bid_modified = True
        return True

    # ================================================================
    #  트릭 진행
    # ================================================================

    def start_trick(self) -> int:
        """새 트릭을 시작하고 트릭 번호를 반환한다."""
        self.current_trick += 1
        self.trick_cards = []
        self.state = GameState.PLAYING

        # 리드 플레이어의 인덱스 찾기
        self.current_player_idx = self.player_order.index(self.lead_player_id)
        return self.current_trick

    @property
    def current_turn_player(self) -> Player:
        """현재 차례인 플레이어."""
        pid = self.player_order[self.current_player_idx]
        return self.players[pid]

    @property
    def lead_suit(self) -> Optional[Suit]:
        """현재 트릭의 리드 색상."""
        return determine_lead_suit(self.trick_cards)

    def get_valid_cards(self, player_id: int) -> List[int]:
        """플레이어가 낼 수 있는 카드 인덱스 목록."""
        player = self.players.get(player_id)
        if not player:
            return []
        return player.get_valid_card_indices(self.lead_suit)

    def play_card(self, player_id: int, card_index: int) -> PlayedCard:
        """플레이어가 카드를 낸다."""
        player = self.players[player_id]
        card = player.play_card(card_index)

        played = PlayedCard(
            player_id=player_id,
            player_name=player.name,
            card=card,
            play_order=len(self.trick_cards),
        )
        self.trick_cards.append(played)
        return played

    def advance_turn(self) -> bool:
        """다음 플레이어로 턴 이동. 트릭이 끝나면 False 반환."""
        next_idx = (self.current_player_idx + 1) % self.player_count
        # 한 바퀴 돌았으면 트릭 종료
        if len(self.trick_cards) >= self.player_count:
            return False

        self.current_player_idx = next_idx
        return True

    def is_trick_complete(self) -> bool:
        """현재 트릭이 끝났는지."""
        return len(self.trick_cards) >= self.player_count

    def resolve_trick(self) -> TrickResult:
        """현재 트릭의 승자를 판정한다."""
        result = self.trick_resolver.resolve(self.trick_cards, self.lead_suit)

        # 승자의 트릭 카운트 증가
        if result.winner_id is not None:
            winner = self.players.get(result.winner_id)
            if winner:
                winner.tricks_won += 1

                # 보너스 기록
                winner.pirates_captured_by_sk += result.pirates_captured_count
                if result.sk_captured_by_mermaid:
                    winner.sk_captured_by_mermaid = True

        # 약탈품 동맹 기록
        for loot_player_id, capturer_id in result.loot_alliances:
            loot_player = self.players.get(loot_player_id)
            capturer = self.players.get(capturer_id)
            if loot_player and capturer:
                loot_player.loot_ally_ids.append(capturer_id)
                capturer.loot_ally_ids.append(loot_player_id)

        # 다음 리드 플레이어 설정
        if result.next_lead_id is not None:
            self.lead_player_id = result.next_lead_id
        elif result.winner_id is not None:
            self.lead_player_id = result.winner_id

        return result

    def is_round_complete(self) -> bool:
        """현재 라운드의 모든 트릭이 끝났는지."""
        return self.current_trick >= self.current_round

    def end_round(self) -> Dict[int, Dict[str, int]]:
        """라운드를 종료하고 점수를 계산한다."""
        self.state = GameState.ROUND_END
        return calculate_round_scores(
            self.player_list, self.current_round, self.mode
        )

    def is_game_over(self) -> bool:
        """게임이 끝났는지 (10라운드 완료)."""
        return self.current_round >= cfg.TOTAL_ROUNDS

    def end_game(self) -> List[Tuple[Player, int]]:
        """게임을 종료하고 최종 순위를 반환한다.

        Returns:
            [(Player, 순위)] 점수 내림차순
        """
        self.state = GameState.GAME_OVER
        ranked = sorted(self.player_list, key=lambda p: p.total_score, reverse=True)
        return [(p, rank + 1) for rank, p in enumerate(ranked)]

    # ================================================================
    #  해적 능력 지원
    # ================================================================

    def bahij_draw(self, player_id: int) -> List[Card]:
        """바히즈 능력: 남은 덱에서 2장 드로우."""
        player = self.players.get(player_id)
        if not player or not self.deck:
            return []

        drawn = []
        for _ in range(2):
            if self.deck.cards:
                card = self.deck.cards.pop()
                drawn.append(card)
                player.hand.append(card)

        player.sort_hand()
        return drawn

    def bahij_discard(self, player_id: int, indices: List[int]) -> List[Card]:
        """바히즈 능력: 2장 버리기."""
        player = self.players.get(player_id)
        if not player:
            return []
        return player.discard_cards(indices)

    def set_rosie_lead(self, target_player_id: int) -> bool:
        """로지 능력: 다음 리드 플레이어 지목."""
        if target_player_id not in self.players:
            return False
        self.lead_player_id = target_player_id
        return True

    def set_rascal_wager(self, player_id: int, wager: int) -> bool:
        """라스칼 능력: 추가 베팅 설정 (10 또는 20)."""
        player = self.players.get(player_id)
        if not player or wager not in (10, 20):
            return False
        player.rascal_wager = wager
        return True

    def get_remaining_cards_info(self) -> List[Card]:
        """후아니타 능력: 이번 라운드 미사용 카드 목록."""
        return self.remaining_cards


class GameManager:
    """채널별 게임 인스턴스 관리"""

    def __init__(self):
        self._games: Dict[int, Game] = {}  # channel_id -> Game

    def create_game(self, channel_id: int, host: discord.User, mode: GameMode) -> Game:
        """새 게임을 생성한다."""
        game = Game(channel_id=channel_id, host=host, mode=mode)
        self._games[channel_id] = game
        return game

    def get_game(self, channel_id: int) -> Optional[Game]:
        """채널의 활성 게임을 가져온다."""
        return self._games.get(channel_id)

    def remove_game(self, channel_id: int) -> bool:
        """게임을 제거한다."""
        if channel_id in self._games:
            del self._games[channel_id]
            return True
        return False

    def find_player_game(self, user_id: int) -> Optional[Game]:
        """플레이어가 참가 중인 게임을 찾는다 (DM 처리용)."""
        for game in self._games.values():
            if user_id in game.players:
                return game
        return None
