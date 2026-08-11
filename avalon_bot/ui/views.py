"""Discord UI 컴포넌트 - 버튼 & 셀렉트 메뉴 (아발롬)"""

from __future__ import annotations
import asyncio
from typing import Optional, List, TYPE_CHECKING
import discord
from discord.ui import View, Button, Select, button, select

if TYPE_CHECKING:
    from game.game import Game
    from game.player import Player


# ================================================================
#  진행 확인 뷰
# ================================================================

class ConfirmView(View):
    """진행 확인 - 모든 인간 플레이어가 확인해야 다음으로 진행"""

    def __init__(self, human_ids: set, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.human_ids = set(human_ids)
        self.confirmed: set = set()
        self.all_confirmed = asyncio.Event()
        total = len(self.human_ids)
        self.confirm_button.label = f"확인 (0/{total})"

    @button(label="확인 (0/0)", style=discord.ButtonStyle.green, emoji="✅",
            custom_id="progress_confirm")
    async def confirm_button(self, interaction: discord.Interaction,
                             btn: Button):
        uid = interaction.user.id
        if uid not in self.human_ids:
            await interaction.response.send_message("게임 참가자가 아닙니다!", ephemeral=True)
            return
        if uid in self.confirmed:
            await interaction.response.send_message("이미 확인했습니다!", ephemeral=True)
            return

        self.confirmed.add(uid)
        total = len(self.human_ids)
        done = len(self.confirmed)

        if done >= total:
            btn.label = "전원 확인 완료!"
            btn.disabled = True
            await interaction.response.edit_message(view=self)
            self.all_confirmed.set()
            self.stop()
        else:
            btn.label = f"확인 ({done}/{total})"
            await interaction.response.edit_message(view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        self.all_confirmed.set()


# ================================================================
#  로비 뷰
# ================================================================

class LobbyView(View):
    """로비 대기 - 참가/퇴장/AI/시작"""

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

    @button(label="게임 시작", style=discord.ButtonStyle.red, emoji="🏰")
    async def start_button(self, interaction: discord.Interaction, btn: Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message(
                "호스트만 게임을 시작할 수 있습니다!", ephemeral=True
            )
            return
        if not self.game.can_start():
            await interaction.response.send_message(
                f"최소 {self.game.player_count}명 중 {5}명이 필요합니다!", ephemeral=True
            )
            return
        self.started = True
        for item in self.children:
            item.disabled = True
        from .embeds import EmbedBuilder
        await interaction.response.edit_message(
            embed=EmbedBuilder.lobby(self.game), view=self
        )
        self.stop()


# ================================================================
#  원정대 선택 뷰
# ================================================================

class TeamSelectView(View):
    """리더가 원정대 멤버를 선택"""

    def __init__(self, game: Game, timeout: float = 90):
        super().__init__(timeout=timeout)
        self.game = game
        self.selected_ids: List[int] = []
        self.done = False

        quest = game.current_quest
        team_size = quest.team_size

        # 동적으로 셀렉트 메뉴 생성
        options = []
        for p in game.player_list:
            ai_tag = " 🤖" if p.is_ai else ""
            options.append(
                discord.SelectOption(
                    label=f"{p.name}{ai_tag}",
                    value=str(p.id),
                )
            )

        sel = Select(
            placeholder=f"원정대 {team_size}명을 선택하세요",
            min_values=team_size,
            max_values=team_size,
            options=options,
            custom_id="team_select",
        )
        sel.callback = self._select_callback
        self.add_item(sel)

    async def _select_callback(self, interaction: discord.Interaction):
        # 리더만 선택 가능
        if interaction.user.id != self.game.leader.id:
            await interaction.response.send_message(
                "리더만 원정대를 편성할 수 있습니다!", ephemeral=True
            )
            return

        self.selected_ids = [int(v) for v in interaction.data["values"]]
        self.done = True

        names = [self.game.players[pid].name for pid in self.selected_ids]
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ 원정대: {', '.join(names)}",
            view=self,
        )
        self.stop()


# ================================================================
#  팀 투표 뷰 (찬성/반대)
# ================================================================

class TeamVoteView(View):
    """모든 플레이어가 원정대에 대해 투표"""

    def __init__(self, game: Game, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.game = game
        self.votes_received: int = 0
        self.done = False
        self._voted_ids: set = set()

    @button(label="찬성", style=discord.ButtonStyle.green, emoji="👍")
    async def approve_button(self, interaction: discord.Interaction, btn: Button):
        await self._handle_vote(interaction, "approve")

    @button(label="반대", style=discord.ButtonStyle.red, emoji="👎")
    async def reject_button(self, interaction: discord.Interaction, btn: Button):
        await self._handle_vote(interaction, "reject")

    async def _handle_vote(self, interaction: discord.Interaction, vote_type: str):
        pid = interaction.user.id
        if pid not in self.game.players:
            await interaction.response.send_message(
                "게임 참가자가 아닙니다!", ephemeral=True
            )
            return
        if pid in self._voted_ids:
            await interaction.response.send_message(
                "이미 투표했습니다!", ephemeral=True
            )
            return

        from game.enums import Vote
        vote = Vote.APPROVE if vote_type == "approve" else Vote.REJECT
        self.game.cast_team_vote(pid, vote)
        self._voted_ids.add(pid)
        self.votes_received += 1

        remaining = self.game.player_count - self.votes_received
        await interaction.response.send_message(
            f"✅ 투표 완료! (남은 인원: {remaining}명)", ephemeral=True
        )

        if self.game.all_team_voted():
            self.done = True
            for item in self.children:
                item.disabled = True
            # 메시지 업데이트
            try:
                await interaction.message.edit(
                    content="📮 투표 완료! 결과를 집계합니다...",
                    view=self,
                )
            except Exception:
                pass
            self.stop()


# ================================================================
#  역할 확인 뷰 (채널에 표시, ephemeral 응답)
# ================================================================

class RoleCheckView(View):
    """채널에 역할 확인 버튼을 표시, 클릭 시 ephemeral로 역할 정보 전송"""

    def __init__(self, game: Game):
        super().__init__(timeout=None)  # persistent
        self.game = game

    @button(label="내 역할 확인", style=discord.ButtonStyle.primary, emoji="🔍")
    async def check_role(self, interaction: discord.Interaction, btn: Button):
        player_id = interaction.user.id
        # Find the player in the game
        player = None
        for p in self.game.player_list:
            if p.id == player_id:
                player = p
                break
        if not player:
            await interaction.response.send_message(
                "게임 참가자가 아닙니다!", ephemeral=True
            )
            return
        from .embeds import EmbedBuilder
        embed = EmbedBuilder.night_role_dm(player, self.game.player_list)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ================================================================
#  퀘스트 투표 뷰 (채널에 표시, ephemeral 응답)
# ================================================================

class QuestVoteChannelView(View):
    """퀘스트 투표 - 채널에 표시, ephemeral 응답"""

    def __init__(self, game: Game, team_ids: List[int], timeout: float = 60):
        super().__init__(timeout=timeout)
        self.game = game
        self.team_ids = set(team_ids)
        self.human_team_ids = {
            pid for pid in team_ids if not game.players[pid].is_ai
        }
        self.votes: dict = {}  # {player_id: QuestVote}
        self.done = asyncio.Event()
        self.timed_out = False

    @button(label="성공", style=discord.ButtonStyle.green, emoji="✅")
    async def success_button(self, interaction: discord.Interaction, btn: Button):
        await self._cast_vote(interaction, True)

    @button(label="실패", style=discord.ButtonStyle.red, emoji="❌")
    async def fail_button(self, interaction: discord.Interaction, btn: Button):
        await self._cast_vote(interaction, False)

    async def _cast_vote(self, interaction: discord.Interaction, success: bool):
        uid = interaction.user.id
        if uid not in self.team_ids:
            await interaction.response.send_message(
                "퀘스트 팀원이 아닙니다!", ephemeral=True
            )
            return
        if uid in self.votes:
            await interaction.response.send_message(
                "이미 투표했습니다!", ephemeral=True
            )
            return

        player = self.game.players[uid]

        # 선의 진영은 성공만 선택 가능
        if not success and player.is_good:
            await interaction.response.send_message(
                "선의 진영은 성공만 선택할 수 있습니다!", ephemeral=True
            )
            return

        self.votes[uid] = success
        emoji = "✅ 성공" if success else "❌ 실패"
        remaining = len(self.human_team_ids) - sum(
            1 for pid in self.human_team_ids if pid in self.votes
        )
        await interaction.response.send_message(
            f"{emoji} 카드를 냈습니다! (남은 제출: {remaining}명)",
            ephemeral=True,
        )

        # 모든 인간 팀원이 투표 완료
        if all(pid in self.votes for pid in self.human_team_ids):
            for item in self.children:
                item.disabled = True
            try:
                await interaction.message.edit(
                    content="📜 모든 원정대원이 투표를 완료했습니다!",
                    view=self,
                )
            except Exception:
                pass
            self.done.set()
            self.stop()

    async def on_timeout(self):
        self.timed_out = True
        self.done.set()


# ================================================================
#  암살자 선택 뷰
# ================================================================

class AssassinSelectView(View):
    """암살자가 멀린을 지목"""

    def __init__(self, game: Game, timeout: float = 90):
        super().__init__(timeout=timeout)
        self.game = game
        self.target_id: Optional[int] = None
        self.done = False

        # 선 플레이어만 대상
        options = []
        for p in game.good_players:
            ai_tag = " 🤖" if p.is_ai else ""
            options.append(
                discord.SelectOption(
                    label=f"{p.name}{ai_tag}",
                    value=str(p.id),
                    description="이 사람이 멀린인가?",
                )
            )

        sel = Select(
            placeholder="멀린이라고 생각되는 사람을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="assassin_select",
        )
        sel.callback = self._select_callback
        self.add_item(sel)

    async def _select_callback(self, interaction: discord.Interaction):
        assassin = self.game.get_assassin()
        if assassin and interaction.user.id != assassin.id:
            await interaction.response.send_message(
                "암살자만 지목할 수 있습니다!", ephemeral=True
            )
            return

        self.target_id = int(interaction.data["values"][0])
        self.done = True
        target = self.game.players[self.target_id]

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"🗡️ **{target.name}**을(를) 멀린으로 지목했습니다!",
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
            content="🔄 새 게임을 시작하려면 `/아발롬` 명령어를 사용하세요!",
            view=self,
        )
        self.stop()
