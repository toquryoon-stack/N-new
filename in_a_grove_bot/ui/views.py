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
#  진행 확인 뷰 (모든 사람 플레이어가 확인해야 다음 메시지로 진행)
# ================================================================

class AckView(View):
    """진행 상황 메시지에 붙는 [확인] 버튼. 게임에 참가한 모든 사람
    플레이어(AI 제외)가 눌러야 다음 메시지로 넘어간다."""

    def __init__(self, game: Game, timeout: float = 25):
        super().__init__(timeout=timeout)
        self.game = game
        self.pending_ids = {p.id for p in game.player_list if not p.is_ai}
        self.acked_ids: set = set()
        self._update_label()

    def _update_label(self):
        self.children[0].label = f"✅ 확인 ({len(self.acked_ids)}/{len(self.pending_ids)})"

    @button(label="✅ 확인", style=discord.ButtonStyle.green)
    async def ack_button(self, interaction: discord.Interaction, btn: Button):
        if interaction.user.id not in self.pending_ids:
            await interaction.response.send_message(
                "이 게임의 참가자가 아닙니다!", ephemeral=True
            )
            return
        if interaction.user.id in self.acked_ids:
            await interaction.response.send_message(
                "이미 확인하셨습니다!", ephemeral=True
            )
            return

        self.acked_ids.add(interaction.user.id)

        if len(self.acked_ids) >= len(self.pending_ids):
            btn.disabled = True
            btn.label = "✅ 모두 확인 완료"
            await interaction.response.edit_message(view=self)
            self.stop()
        else:
            self._update_label()
            await interaction.response.edit_message(view=self)


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
#  타일 확인 뷰 (채널에서 버튼으로, 본인에게만 보이는 응답)
# ================================================================

class TileCheckView(View):
    """채널의 버튼을 눌러, 원래 받은 타일과 전달받은 타일을 한 메시지로
    본인에게만 보이게 확인 (ephemeral). 모든 사람 플레이어가 한 번씩
    확인하면(=확인이 곧 진행 확인) 다음 메시지로 넘어간다."""

    def __init__(self, game: Game, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.game = game
        self.pending_ids = {p.id for p in game.player_list if not p.is_ai}
        self.viewed_ids: set = set()
        self._update_label()

    def _update_label(self):
        self.children[0].label = (
            f"🃏 내 타일 확인 ({len(self.viewed_ids)}/{len(self.pending_ids)})"
        )

    @button(label="내 타일 확인", style=discord.ButtonStyle.blurple, emoji="🃏")
    async def check_button(self, interaction: discord.Interaction, btn: Button):
        player = self.game.players.get(interaction.user.id)
        if not player or player.is_ai:
            await interaction.response.send_message(
                "이 게임에 참가하지 않았습니다!", ephemeral=True
            )
            return

        from .embeds import EmbedBuilder
        embed = EmbedBuilder.my_tiles(player, self.game)
        await interaction.response.send_message(embed=embed, ephemeral=True)

        if interaction.user.id in self.viewed_ids:
            return
        self.viewed_ids.add(interaction.user.id)

        if len(self.viewed_ids) >= len(self.pending_ids):
            btn.disabled = True
            btn.label = "🃏 모두 확인 완료"
            await interaction.message.edit(view=self)
            self.stop()
        else:
            self._update_label()
            await interaction.message.edit(view=self)


# ================================================================
#  발견자 수사 뷰 (채널에서 시작 → 본인에게만 보이는 응답으로 진행)
# ================================================================

class DiscovererStartView(View):
    """발견자가 채널 버튼으로 수사를 시작하고, 이후 본인만 보이는
    응답(ephemeral)으로 용의자 확인 및 교체 여부를 결정한다."""

    def __init__(self, game: Game, discoverer_id: int, timeout: float = 150):
        super().__init__(timeout=timeout)
        self.game = game
        self.discoverer_id = discoverer_id
        self.done = False
        self.chosen_indices: List[int] = []
        self.swapped = False

    @button(label="수사 시작", style=discord.ButtonStyle.blurple, emoji="🔍")
    async def start_button(self, interaction: discord.Interaction, btn: Button):
        if interaction.user.id != self.discoverer_id:
            await interaction.response.send_message(
                "발견자만 수사를 시작할 수 있습니다!", ephemeral=True
            )
            return

        btn.disabled = True
        await interaction.message.edit(view=self)

        from .embeds import EmbedBuilder
        discoverer = self.game.players[self.discoverer_id]

        # 1) 용의자 2명 선택 (본인에게만 보임)
        select_view = SuspectSelectView(timeout=60)
        await interaction.response.send_message(
            "🔍 **발견자 수사** - 확인할 용의자 2명을 선택하세요:",
            view=select_view,
            ephemeral=True,
        )

        timed_out = await select_view.wait()
        if timed_out or not select_view.done:
            chosen = [0, 1]
            await interaction.followup.send(
                "⏰ 시간 초과! 자동으로 용의자 1, 2를 선택합니다.", ephemeral=True
            )
        else:
            chosen = select_view.selected_indices
        self.chosen_indices = chosen

        viewed = self.game.set_discoverer_viewed(chosen)

        # 결과 확인 (본인에게만 보임)
        embed = EmbedBuilder.discoverer_view_dm(discoverer, viewed, self.game)
        await interaction.followup.send(embed=embed, ephemeral=True)

        # 2) 교체 여부 (본인에게만 보임)
        swap_view = SwapVictimView(viewed_indices=chosen, timeout=60)
        await interaction.followup.send(
            "🔄 용의자와 피해자를 교체하시겠습니까?",
            view=swap_view,
            ephemeral=True,
        )

        timed_out = await swap_view.wait()
        if timed_out or not swap_view.done:
            await interaction.followup.send("⏰ 시간 초과! 교체 없이 넘어갑니다.", ephemeral=True)
            swap_idx = None
        else:
            swap_idx = swap_view.swap_idx

        if swap_idx is not None:
            self.game.swap_victim(swap_idx)
            self.swapped = True
            embed = EmbedBuilder.swap_result_dm(True, self.game)
        else:
            self.swapped = False
            embed = EmbedBuilder.swap_result_dm(False, self.game)
        await interaction.followup.send(embed=embed, ephemeral=True)

        self.done = True
        self.stop()


# ================================================================
#  고발자 확인 뷰 (발견자 이후의 모든 고발자가, 고발 전 필수로 확인)
# ================================================================

class SuspectPeekView(View):
    """직전에 고발된 용의자를 제외한 나머지 2명을, 채널 버튼을 눌러
    본인에게만 보이게 확인한다."""

    def __init__(self, game: Game, accuser_id: int, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.game = game
        self.accuser_id = accuser_id
        self.done = False

    @button(label="남은 용의자 확인", style=discord.ButtonStyle.blurple, emoji="🔍")
    async def peek_button(self, interaction: discord.Interaction, btn: Button):
        if interaction.user.id != self.accuser_id:
            await interaction.response.send_message(
                "지금은 당신의 차례가 아닙니다!", ephemeral=True
            )
            return

        viewed = self.game.view_suspects_for_next_accuser()

        from .embeds import EmbedBuilder
        embed = EmbedBuilder.accuser_peek(viewed, self.game)

        btn.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(embed=embed, ephemeral=True)

        self.done = True
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
