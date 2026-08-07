"""Discord UI 컴포넌트 - 버튼, 셀렉트 메뉴 등"""

from __future__ import annotations
import asyncio
from typing import Optional, List, TYPE_CHECKING
import discord
from discord.ui import View, Button, Select, button, select

if TYPE_CHECKING:
    from game.game import Game
    from game.player import Player
    from game.cards import Card
    from game.enums import GameMode, PirateName

from game.enums import GameMode, TigressChoice, PirateName


# ════════════════════════════════════════════
#  모드 선택
# ════════════════════════════════════════════

class ModeSelectView(View):
    """기본판 / 확장판 선택 버튼"""

    def __init__(self):
        super().__init__(timeout=120)
        self.selected_mode: Optional[GameMode] = None

    @button(label="📜 기본판", style=discord.ButtonStyle.primary, custom_id="mode_basic")
    async def basic_button(self, interaction: discord.Interaction, btn: Button):
        self.selected_mode = GameMode.BASIC
        await interaction.response.defer()
        self.stop()

    @button(label="⚔️ 확장판", style=discord.ButtonStyle.danger, custom_id="mode_legendary")
    async def legendary_button(self, interaction: discord.Interaction, btn: Button):
        self.selected_mode = GameMode.LEGENDARY
        await interaction.response.defer()
        self.stop()


# ════════════════════════════════════════════
#  로비 (참가 / 시작)
# ════════════════════════════════════════════

class LobbyView(View):
    """게임 로비 - 참가/퇴장/AI추가/AI제거/시작 버튼"""

    def __init__(self, game: Game, on_join, on_leave, on_start, on_add_ai, on_remove_ai):
        super().__init__(timeout=600)  # 10분
        self.game = game
        self._on_join = on_join
        self._on_leave = on_leave
        self._on_start = on_start
        self._on_add_ai = on_add_ai
        self._on_remove_ai = on_remove_ai

    @button(label="🏴‍☠️ 참가", style=discord.ButtonStyle.success, custom_id="lobby_join", row=0)
    async def join_button(self, interaction: discord.Interaction, btn: Button):
        await self._on_join(interaction)

    @button(label="🚪 퇴장", style=discord.ButtonStyle.secondary, custom_id="lobby_leave", row=0)
    async def leave_button(self, interaction: discord.Interaction, btn: Button):
        await self._on_leave(interaction)

    @button(label="🤖 AI 추가", style=discord.ButtonStyle.primary, custom_id="lobby_add_ai", row=1)
    async def add_ai_button(self, interaction: discord.Interaction, btn: Button):
        await self._on_add_ai(interaction)

    @button(label="🤖 AI 제거", style=discord.ButtonStyle.secondary, custom_id="lobby_remove_ai", row=1)
    async def remove_ai_button(self, interaction: discord.Interaction, btn: Button):
        await self._on_remove_ai(interaction)

    @button(label="🚀 게임 시작", style=discord.ButtonStyle.success, custom_id="lobby_start", row=2)
    async def start_button(self, interaction: discord.Interaction, btn: Button):
        await self._on_start(interaction)


# ════════════════════════════════════════════
#  비딩
# ════════════════════════════════════════════

class BiddingView(View):
    """비딩 선택 (DM으로 전송)"""

    def __init__(self, max_bid: int):
        super().__init__(timeout=120)  # 2분
        self.selected_bid: Optional[int] = None

        # 비딩 버튼 동적 생성 (0 ~ max_bid)
        for i in range(max_bid + 1):
            btn = Button(
                label=str(i),
                style=discord.ButtonStyle.primary if i > 0 else discord.ButtonStyle.danger,
                custom_id=f"bid_{i}",
                row=i // 5,  # 5개씩 한 줄
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, bid_value: int):
        async def callback(interaction: discord.Interaction):
            self.selected_bid = bid_value
            await interaction.response.edit_message(
                content=f"✅ **{bid_value}** 트릭으로 비딩했습니다!",
                embed=None,
                view=None,
            )
            self.stop()
        return callback


# ════════════════════════════════════════════
#  카드 선택
# ════════════════════════════════════════════

class CardSelectView(View):
    """카드 선택 (DM으로 전송)"""

    def __init__(self, hand: List[Card], valid_indices: List[int]):
        super().__init__(timeout=120)
        self.selected_index: Optional[int] = None

        # 셀렉트 메뉴 생성
        options = []
        for i in valid_indices:
            card = hand[i]
            options.append(discord.SelectOption(
                label=card.label_for_select,
                value=str(i),
                emoji=card.emoji,
                description=f"#{i+1}",
            ))

        self.card_select = Select(
            placeholder="카드를 선택하세요...",
            options=options,
            custom_id="card_select",
        )
        self.card_select.callback = self._on_select
        self.add_item(self.card_select)

    async def _on_select(self, interaction: discord.Interaction):
        self.selected_index = int(self.card_select.values[0])
        await interaction.response.edit_message(
            content="✅ 카드를 선택했습니다!",
            embed=None,
            view=None,
        )
        self.stop()


# ════════════════════════════════════════════
#  타이그리스 선택
# ════════════════════════════════════════════

class TigressChoiceView(View):
    """타이그리스: 해적 or 탈출 선택"""

    def __init__(self):
        super().__init__(timeout=60)
        self.choice: Optional[TigressChoice] = None

    @button(label="☠️ 해적으로 사용", style=discord.ButtonStyle.danger, custom_id="tigress_pirate")
    async def pirate_button(self, interaction: discord.Interaction, btn: Button):
        self.choice = TigressChoice.PIRATE
        await interaction.response.edit_message(
            content="☠️ 타이그리스를 **해적**으로 사용합니다!",
            view=None,
        )
        self.stop()

    @button(label="🏳️ 탈출로 사용", style=discord.ButtonStyle.secondary, custom_id="tigress_escape")
    async def escape_button(self, interaction: discord.Interaction, btn: Button):
        self.choice = TigressChoice.ESCAPE
        await interaction.response.edit_message(
            content="🏳️ 타이그리스를 **탈출**로 사용합니다!",
            view=None,
        )
        self.stop()


# ════════════════════════════════════════════
#  해적 능력
# ════════════════════════════════════════════

class PirateAbilityView(View):
    """해적 능력 발동 UI (공통 베이스)"""

    def __init__(self, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.result = None


class RosieSelectView(PirateAbilityView):
    """로지: 다음 리드 플레이어 선택"""

    def __init__(self, players: List[Player]):
        super().__init__()
        options = [
            discord.SelectOption(
                label=p.name,
                value=str(p.id),
                emoji="🏴‍☠️",
            )
            for p in players
        ]
        self.player_select = Select(
            placeholder="다음 트릭 리드 플레이어를 선택하세요...",
            options=options,
            custom_id="rosie_select",
        )
        self.player_select.callback = self._on_select
        self.add_item(self.player_select)

    async def _on_select(self, interaction: discord.Interaction):
        self.result = int(self.player_select.values[0])
        await interaction.response.edit_message(
            content="✅ 리드 플레이어를 지정했습니다!",
            view=None,
        )
        self.stop()


class BahijDiscardView(PirateAbilityView):
    """바히즈: 버릴 카드 2장 선택"""

    def __init__(self, hand: List[Card]):
        super().__init__()
        options = [
            discord.SelectOption(
                label=card.label_for_select,
                value=str(i),
                emoji=card.emoji,
                description=f"#{i+1}",
            )
            for i, card in enumerate(hand)
        ]
        self.card_select = Select(
            placeholder="버릴 카드 2장을 선택하세요...",
            options=options,
            min_values=2,
            max_values=2,
            custom_id="bahij_discard",
        )
        self.card_select.callback = self._on_select
        self.add_item(self.card_select)

    async def _on_select(self, interaction: discord.Interaction):
        self.result = [int(v) for v in self.card_select.values]
        await interaction.response.edit_message(
            content="✅ 카드 2장을 버렸습니다!",
            view=None,
        )
        self.stop()


class HarryBidView(PirateAbilityView):
    """해리: 비딩 ±1 변경"""

    def __init__(self, current_bid: int, max_bid: int):
        super().__init__()
        self.current_bid = current_bid

        # +1 버튼
        if current_bid < max_bid:
            btn_plus = Button(
                label=f"+1 (→ {current_bid + 1})",
                style=discord.ButtonStyle.success,
                custom_id="harry_plus",
            )
            btn_plus.callback = self._on_plus
            self.add_item(btn_plus)

        # -1 버튼
        if current_bid > 0:
            btn_minus = Button(
                label=f"-1 (→ {current_bid - 1})",
                style=discord.ButtonStyle.danger,
                custom_id="harry_minus",
            )
            btn_minus.callback = self._on_minus
            self.add_item(btn_minus)

        # 유지 버튼
        btn_keep = Button(
            label=f"유지 ({current_bid})",
            style=discord.ButtonStyle.secondary,
            custom_id="harry_keep",
        )
        btn_keep.callback = self._on_keep
        self.add_item(btn_keep)

    async def _on_plus(self, interaction: discord.Interaction):
        self.result = 1
        await interaction.response.edit_message(
            content=f"✅ 비딩을 **{self.current_bid + 1}**(으)로 변경했습니다!",
            view=None,
        )
        self.stop()

    async def _on_minus(self, interaction: discord.Interaction):
        self.result = -1
        await interaction.response.edit_message(
            content=f"✅ 비딩을 **{self.current_bid - 1}**(으)로 변경했습니다!",
            view=None,
        )
        self.stop()

    async def _on_keep(self, interaction: discord.Interaction):
        self.result = 0
        await interaction.response.edit_message(
            content=f"✅ 비딩을 **{self.current_bid}**(으)로 유지합니다.",
            view=None,
        )
        self.stop()


class RascalWagerView(PirateAbilityView):
    """라스칼: 10점 또는 20점 추가 베팅"""

    def __init__(self):
        super().__init__()

    @button(label="10점 베팅", style=discord.ButtonStyle.primary, custom_id="rascal_10")
    async def wager_10(self, interaction: discord.Interaction, btn: Button):
        self.result = 10
        await interaction.response.edit_message(
            content="✅ **10점** 추가 베팅!",
            view=None,
        )
        self.stop()

    @button(label="20점 베팅", style=discord.ButtonStyle.danger, custom_id="rascal_20")
    async def wager_20(self, interaction: discord.Interaction, btn: Button):
        self.result = 20
        await interaction.response.edit_message(
            content="✅ **20점** 추가 베팅!",
            view=None,
        )
        self.stop()


# ════════════════════════════════════════════
#  게임 종료 후
# ════════════════════════════════════════════

class GameOverView(View):
    """게임 종료 - 다시하기 / 끝내기"""

    def __init__(self):
        super().__init__(timeout=120)
        self.action: Optional[str] = None

    @button(label="🔄 다시 하기", style=discord.ButtonStyle.success, custom_id="game_restart")
    async def restart_button(self, interaction: discord.Interaction, btn: Button):
        self.action = "restart"
        await interaction.response.defer()
        self.stop()

    @button(label="🚪 끝내기", style=discord.ButtonStyle.secondary, custom_id="game_end")
    async def end_button(self, interaction: discord.Interaction, btn: Button):
        self.action = "end"
        await interaction.response.defer()
        self.stop()


# ════════════════════════════════════════════
#  라운드 진행 확인
# ════════════════════════════════════════════

class NextRoundView(View):
    """라운드 종료 후 다음 라운드 진행 버튼"""

    def __init__(self):
        super().__init__(timeout=120)
        self.proceed: bool = False

    @button(label="▶️ 다음 라운드", style=discord.ButtonStyle.success, custom_id="next_round")
    async def next_button(self, interaction: discord.Interaction, btn: Button):
        self.proceed = True
        await interaction.response.defer()
        self.stop()
