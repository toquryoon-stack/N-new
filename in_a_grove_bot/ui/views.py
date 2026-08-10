"""Discord UI 컴포넌트 - 버튼 & 셀렉트 메뉴"""

from __future__ import annotations
import asyncio
from typing import Optional, List, TYPE_CHECKING
import discord
from discord.ui import View, Button, Select, button, select

if TYPE_CHECKING:
    from game.game import Game


# ================================================================
#  로비 뷰
# ================================================================

class LobbyView(View):
    """로비 대기 화면 - 참가/퇴장/AI 추가/시작"""

    def __init__(self, game: Game, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.game = game
        self.started = False

    @button(label="참가", style=discord.ButtonStyle.green, emoji="✋")
    async def join_button(self, interaction: discord.Interaction, btn: Button):
        if self.game.add_player(interaction.user):
            from .embeds import EmbedBuilder
            await interaction.response.edit_message(
                embed=EmbedBuilder.lobby(self.game), view=self
            )
        else:
            await interaction.response.send_message(
                "이미 참가했거나 인원이 가득 찼습니다!", ephemeral=True
            )

    @button(label="퇴장", style=discord.ButtonStyle.grey, emoji="🚪")
    async def leave_button(self, interaction: discord.Interaction, btn: Button):
        if interaction.user == self.game.host:
            await interaction.response.send_message(
                "호스트는 퇴장할 수 없습니다!", ephemeral=True
            )
            return
        if self.game.remove_player(interaction.user.id):
            from .embeds import EmbedBuilder
            await interaction.response.edit_message(
                embed=EmbedBuilder.lobby(self.game), view=self
            )
        else:
            await interaction.response.send_message(
                "참가하지 않았습니다!", ephemeral=True
            )

    @button(label="AI 추가", style=discord.ButtonStyle.blurple, emoji="🤖")
    async def add_ai_button(self, interaction: discord.Interaction, btn: Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message(
                "호스트만 AI를 추가할 수 있습니다!", ephemeral=True
            )
            return
        ai_player = self.game.add_ai_player()
        if ai_player:
            from .embeds import EmbedBuilder
            await interaction.response.edit_message(
                embed=EmbedBuilder.lobby(self.game), view=self
            )
        else:
            await interaction.response.send_message(
                "인원이 가득 찼습니다!", ephemeral=True
            )

    @button(label="AI 제거", style=discord.ButtonStyle.grey, emoji="❌")
    async def remove_ai_button(self, interaction: discord.Interaction, btn: Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message(
                "호스트만 AI를 제거할 수 있습니다!", ephemeral=True
            )
            return
        if self.game.remove_ai_player():
            from .embeds import EmbedBuilder
            await interaction.response.edit_message(
                embed=EmbedBuilder.lobby(self.game), view=self
            )
        else:
            await interaction.response.send_message(
                "제거할 AI가 없습니다!", ephemeral=True
            )

    @button(label="게임 시작", style=discord.ButtonStyle.red, emoji="🎮")
    async def start_button(self, interaction: discord.Interaction, btn: Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message(
                "호스트만 게임을 시작할 수 있습니다!", ephemeral=True
            )
            return
        if not self.game.can_start():
            await interaction.response.send_message(
                "최소 2명이 필요합니다!", ephemeral=True
            )
            return
        self.started = True
        # 버튼 비활성화
        for item in self.children:
            item.disabled = True
        from .embeds import EmbedBuilder
        await interaction.response.edit_message(
            embed=EmbedBuilder.lobby(self.game), view=self
        )
        self.stop()


# ================================================================
#  발견자: 용의자 선택 뷰
# ================================================================

class SuspectSelectView(View):
    """발견자가 확인할 용의자 2명을 선택"""

    def __init__(self, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.selected_indices: List[int] = []
        self.done = False

    @select(
        placeholder="확인할 용의자 2명을 선택하세요",
        min_values=2,
        max_values=2,
        options=[
            discord.SelectOption(label="용의자 1", value="0", emoji="1️⃣"),
            discord.SelectOption(label="용의자 2", value="1", emoji="2️⃣"),
            discord.SelectOption(label="용의자 3", value="2", emoji="3️⃣"),
        ],
    )
    async def suspect_select(self, interaction: discord.Interaction, sel: Select):
        self.selected_indices = sorted([int(v) for v in sel.values])
        self.done = True
        # 비활성화
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ 용의자 {self.selected_indices[0] + 1}, {self.selected_indices[1] + 1}을(를) 선택했습니다!",
            view=self,
        )
        self.stop()


# ================================================================
#  발견자: 피해자 교체 뷰
# ================================================================

class SwapVictimView(View):
    """발견자가 용의자와 피해자를 교체할지 선택"""

    def __init__(self, viewed_indices: List[int], timeout: float = 60):
        super().__init__(timeout=timeout)
        self.viewed_indices = viewed_indices
        self.swap_idx: Optional[int] = None
        self.done = False

        # 동적으로 교체 버튼 추가
        for idx in viewed_indices:
            btn = Button(
                label=f"용의자 {idx + 1}과 교체",
                style=discord.ButtonStyle.danger,
                custom_id=f"swap_{idx}",
                emoji="🔄",
            )
            btn.callback = self._make_swap_callback(idx)
            self.add_item(btn)

        # 교체 안 함 버튼
        skip_btn = Button(
            label="교체 안 함",
            style=discord.ButtonStyle.grey,
            custom_id="swap_skip",
            emoji="⏭️",
        )
        skip_btn.callback = self._skip_callback
        self.add_item(skip_btn)

    def _make_swap_callback(self, idx: int):
        async def callback(interaction: discord.Interaction):
            self.swap_idx = idx
            self.done = True
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content=f"🔄 용의자 {idx + 1}과 피해자를 교체합니다!",
                view=self,
            )
            self.stop()
        return callback

    async def _skip_callback(self, interaction: discord.Interaction):
        self.swap_idx = None
        self.done = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="⏭️ 교체 없이 넘어갑니다.",
            view=self,
        )
        self.stop()


# ================================================================
#  고발 뷰
# ================================================================

class AccusationView(View):
    """플레이어가 고발할 용의자를 선택"""

    def __init__(self, game: Game, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.game = game
        self.chosen_idx: Optional[int] = None
        self.done = False

    @button(label="용의자 1", style=discord.ButtonStyle.danger, emoji="1️⃣")
    async def accuse_1(self, interaction: discord.Interaction, btn: Button):
        await self._do_accuse(interaction, 0)

    @button(label="용의자 2", style=discord.ButtonStyle.danger, emoji="2️⃣")
    async def accuse_2(self, interaction: discord.Interaction, btn: Button):
        await self._do_accuse(interaction, 1)

    @button(label="용의자 3", style=discord.ButtonStyle.danger, emoji="3️⃣")
    async def accuse_3(self, interaction: discord.Interaction, btn: Button):
        await self._do_accuse(interaction, 2)

    async def _do_accuse(self, interaction: discord.Interaction, idx: int):
        # 본인 차례인지 확인
        accuser = self.game.current_accuser
        if interaction.user.id != accuser.id:
            await interaction.response.send_message(
                "지금은 당신의 차례가 아닙니다!", ephemeral=True
            )
            return

        self.chosen_idx = idx
        self.done = True

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=f"⚖️ **용의자 {idx + 1}**을(를) 고발했습니다!",
            view=self,
        )
        self.stop()


# ================================================================
#  다음 라운드 뷰
# ================================================================

class NextRoundView(View):
    """라운드 종료 후 다음 라운드 진행"""

    def __init__(self, host_id: int, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.host_id = host_id
        self.proceed = False

    @button(label="다음 라운드", style=discord.ButtonStyle.green, emoji="▶️")
    async def next_round_button(self, interaction: discord.Interaction, btn: Button):
        if interaction.user.id != self.host_id:
            await interaction.response.send_message(
                "호스트만 다음 라운드를 시작할 수 있습니다!", ephemeral=True
            )
            return
        self.proceed = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="▶️ 다음 라운드를 시작합니다!",
            view=self,
        )
        self.stop()

    @button(label="게임 종료", style=discord.ButtonStyle.grey, emoji="🛑")
    async def end_game_button(self, interaction: discord.Interaction, btn: Button):
        if interaction.user.id != self.host_id:
            await interaction.response.send_message(
                "호스트만 게임을 종료할 수 있습니다!", ephemeral=True
            )
            return
        self.proceed = False
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="🛑 게임을 종료합니다.",
            view=self,
        )
        self.stop()


# ================================================================
#  게임 종료 뷰
# ================================================================

class GameOverView(View):
    """게임 종료 - 재시작 옵션"""

    def __init__(self, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.restart = False

    @button(label="새 게임", style=discord.ButtonStyle.green, emoji="🔄")
    async def restart_button(self, interaction: discord.Interaction, btn: Button):
        self.restart = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="🔄 새 게임을 시작하려면 `/덤불쏭` 명령어를 사용하세요!",
            view=self,
        )
        self.stop()
