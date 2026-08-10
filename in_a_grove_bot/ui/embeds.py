"""Discord Embed 빌더 - 덤불쏭 게임 UI"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
import discord

if TYPE_CHECKING:
    from game.game import Game
    from game.player import Player
    from game.tiles import Tile

from game.player import PLAYER_COLORS, PLAYER_COLOR_NAMES


# ── 색상 상수 ──
COLOR_LOBBY = 0x2ECC71       # 초록 - 로비
COLOR_ROUND = 0x3498DB       # 파랑 - 라운드 정보
COLOR_TILE = 0xE67E22        # 주황 - 타일 정보
COLOR_DISCOVER = 0x9B59B6    # 보라 - 발견자
COLOR_ACCUSE = 0xE74C3C      # 빨강 - 고발
COLOR_REVEAL = 0xF1C40F      # 노랑 - 공개
COLOR_RESULT = 0x1ABC9C      # 청록 - 결과
COLOR_GAMEOVER = 0x95A5A6    # 회색 - 게임 종료


class EmbedBuilder:
    """게임 상태별 Embed 생성"""

    # ================================================================
    #  로비
    # ================================================================

    @staticmethod
    def lobby(game: Game) -> discord.Embed:
        """로비 대기 화면"""
        embed = discord.Embed(
            title="🌿 덤불쏭",
            description=(
                "살인 사건의 진범을 찾아라!\n"
                "용의자 3명 중 범인을 추리하는 블러핑 추리 게임\n\n"
                f"👥 플레이어: **{game.player_count}명** / {2}~{5}명"
            ),
            color=COLOR_LOBBY,
        )

        # 플레이어 목록
        player_lines = []
        for i, p in enumerate(game.player_list):
            prefix = "👑 " if p.user == game.host else ""
            ai_tag = " 🤖" if p.is_ai else ""
            player_lines.append(
                f"{p.color_emoji} {prefix}{p.name}{ai_tag}"
            )

        if player_lines:
            embed.add_field(
                name="참가자",
                value="\n".join(player_lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="참가자",
                value="_아직 아무도 없습니다..._",
                inline=False,
            )

        # 시작 조건
        if game.player_count < 2:
            embed.set_footer(text="최소 2명이 필요합니다. 참가 버튼을 눌러주세요!")
        else:
            embed.set_footer(text="호스트가 게임 시작 버튼을 눌러주세요!")

        return embed

    # ================================================================
    #  라운드 시작
    # ================================================================

    @staticmethod
    def round_start(game: Game) -> discord.Embed:
        """라운드 시작 공지"""
        embed = discord.Embed(
            title=f"🔔 라운드 {game.current_round} 시작!",
            description=(
                "타일이 배분되었습니다.\n"
                "채널의 버튼을 눌러 본인만 볼 수 있는 타일 정보를 확인하세요."
            ),
            color=COLOR_ROUND,
        )

        # 현재 순위
        standings = game.get_standings()
        standing_lines = []
        for p, rank in standings:
            ai_tag = " 🤖" if p.is_ai else ""
            standing_lines.append(
                f"{p.color_emoji} {p.name}{ai_tag}: "
                f"수사 {p.investigation_chips}개 / 무능 {p.inept_chips}개"
            )
        embed.add_field(
            name="📊 현재 칩 현황",
            value="\n".join(standing_lines),
            inline=False,
        )

        # 발견자 표시
        discoverer = game.discoverer
        embed.add_field(
            name="🔍 이번 라운드 발견자",
            value=f"{discoverer.color_emoji} **{discoverer.name}**",
            inline=False,
        )

        embed.set_footer(text="잠시 후 타일이 전달됩니다...")
        return embed

    # ================================================================
    #  타일 정보 (채널 버튼 → 본인에게만 보이는 응답)
    # ================================================================

    @staticmethod
    def my_tiles(player: Player, game: Game) -> discord.Embed:
        """원래 받은 타일과 전달받은 타일을 한 메시지로, 본인에게만 보이게"""
        embed = discord.Embed(
            title=f"🃏 라운드 {game.current_round} - 내 타일 정보",
            color=COLOR_TILE,
        )

        # 자기가 원래 가진 타일
        orig = player.original_tile
        if orig:
            embed.add_field(
                name="원래 내 타일 (→ 전달함)",
                value=f"{orig.emoji} {orig.name}",
                inline=True,
            )

        # 오른쪽에서 받은 타일
        recv = player.received_tile
        if recv:
            embed.add_field(
                name="왼쪽에서 받은 타일",
                value=f"{recv.emoji} **{recv.name}**",
                inline=True,
            )

        # 2인용 고스트 타일
        if game.ghost_tile:
            embed.add_field(
                name="👻 고스트 타일 (공개)",
                value=f"{game.ghost_tile.emoji} **{game.ghost_tile.name}**",
                inline=True,
            )

        embed.add_field(
            name="💡 당신이 아는 정보",
            value=(
                "• 원래 내 타일 = 용의자/피해자가 아닌 타일\n"
                "• 받은 타일 = 마찬가지로 용의자/피해자가 아닌 타일\n"
                "이 정보로 용의자 중 범인을 추리하세요!"
            ),
            inline=False,
        )

        embed.set_footer(text="발견자의 수사가 끝나면 고발이 시작됩니다.")
        return embed

    # ================================================================
    #  발견자 전용 (본인에게만 보이는 응답)
    # ================================================================

    @staticmethod
    def discoverer_view_dm(
        player: Player,
        viewed: List[Tuple[int, Tile]],
        game: Game,
    ) -> discord.Embed:
        """발견자가 용의자 2명을 확인한 결과 (본인에게만 보임)"""
        embed = discord.Embed(
            title="🔍 발견자 수사 결과",
            description="용의자 3명 중 2명을 확인했습니다!",
            color=COLOR_DISCOVER,
        )

        for idx, tile in viewed:
            embed.add_field(
                name=f"용의자 {idx + 1}",
                value=f"{tile.emoji} **{tile.name}**",
                inline=True,
            )

        # 안 본 용의자
        unseen_idx = game.unseen_idx
        if unseen_idx is not None:
            embed.add_field(
                name=f"용의자 {unseen_idx + 1}",
                value="❓ **미확인**",
                inline=True,
            )

        # 피해자 정보
        if game.victim:
            embed.add_field(
                name="🪦 현재 피해자",
                value=f"{game.victim.emoji} **{game.victim.name}**",
                inline=False,
            )

        embed.add_field(
            name="💡 교체 가능",
            value=(
                "확인한 용의자 1명과 피해자를 교체할 수 있습니다.\n"
                "교체하면 다른 플레이어를 혼란시킬 수 있습니다!"
            ),
            inline=False,
        )

        return embed

    @staticmethod
    def swap_result_dm(swapped: bool, game: Game) -> discord.Embed:
        """교체 결과 (본인에게만 보임)"""
        if swapped:
            embed = discord.Embed(
                title="🔄 교체 완료!",
                description="용의자와 피해자를 교체했습니다.",
                color=COLOR_DISCOVER,
            )
        else:
            embed = discord.Embed(
                title="⏭️ 교체 안 함",
                description="교체 없이 넘어갑니다.",
                color=COLOR_DISCOVER,
            )
        return embed

    # ================================================================
    #  고발 단계
    # ================================================================

    @staticmethod
    def accusation_phase(game: Game) -> discord.Embed:
        """고발 단계 시작 공지"""
        embed = discord.Embed(
            title="⚖️ 고발 단계",
            description=(
                "발견자부터 시계방향으로 용의자를 고발합니다.\n"
                "범인이라고 생각하는 용의자에게 수사 칩을 올려주세요!"
            ),
            color=COLOR_ACCUSE,
        )

        # 용의자 표시 (뒷면 - 숫자 비공개)
        suspect_lines = []
        for i in range(3):
            stack = game.accusation_stacks[i]
            stack_display = ""
            if stack:
                names = [game.players[pid].name for pid in stack]
                stack_display = f" ← {', '.join(names)}"
            suspect_lines.append(f"**용의자 {i + 1}** 🎭{stack_display}")

        embed.add_field(
            name="🎭 용의자",
            value="\n".join(suspect_lines),
            inline=False,
        )

        return embed

    @staticmethod
    def accusation_turn(game: Game) -> discord.Embed:
        """현재 고발자 차례 표시"""
        accuser = game.current_accuser
        embed = discord.Embed(
            title="⚖️ 고발 차례",
            description=f"{accuser.color_emoji} **{accuser.name}**의 차례입니다!",
            color=COLOR_ACCUSE,
        )

        # 현재 스택 상황
        suspect_lines = []
        for i in range(3):
            stack = game.accusation_stacks[i]
            chip_display = "🪙" * len(stack) if stack else "_(비어있음)_"
            suspect_lines.append(f"**용의자 {i + 1}** 🎭: {chip_display}")

        embed.add_field(
            name="🎭 현재 고발 상황",
            value="\n".join(suspect_lines),
            inline=False,
        )

        # 누가 고발했는지 표시
        if game.accusation_order:
            done_lines = []
            for pid in game.accusation_order:
                p = game.players[pid]
                done_lines.append(
                    f"{p.color_emoji} {p.name} → 용의자 {p.accusation + 1}"
                )
            embed.add_field(
                name="✅ 이미 고발",
                value="\n".join(done_lines),
                inline=False,
            )

        remaining = game.player_count - len(game.accusation_order)
        embed.set_footer(text=f"남은 고발: {remaining}명")

        return embed

    @staticmethod
    def ai_accusation(player: Player, suspect_idx: int) -> discord.Embed:
        """AI 고발 결과"""
        embed = discord.Embed(
            title="🤖 AI 고발",
            description=(
                f"{player.color_emoji} **{player.name}**이(가) "
                f"**용의자 {suspect_idx + 1}**을(를) 고발했습니다!"
            ),
            color=COLOR_ACCUSE,
        )
        return embed

    # ================================================================
    #  공개 & 판정
    # ================================================================

    @staticmethod
    def reveal_suspects(game: Game, result: dict) -> discord.Embed:
        """용의자 공개"""
        suspects = result["suspects"]
        murderer = result["murderer"]
        murderer_idx = result["murderer_idx"]
        has_five = result["has_five"]

        embed = discord.Embed(
            title="🎭 용의자 공개!",
            color=COLOR_REVEAL,
        )

        # 규칙 설명
        if has_five:
            embed.description = (
                "⚠️ **5번 타일이 있습니다!**\n"
                "→ 가장 **낮은** 숫자가 범인!"
            )
        else:
            embed.description = (
                "→ 가장 **높은** 숫자가 범인!"
            )

        # 용의자 표시
        for i, tile in enumerate(suspects):
            is_murderer = (i == murderer_idx)
            marker = " 🔪 **범인!**" if is_murderer else ""
            stack = game.accusation_stacks[i]
            chip_display = f" (칩 {len(stack)}개)" if stack else ""

            embed.add_field(
                name=f"용의자 {i + 1}{marker}",
                value=f"{tile.emoji} **{tile.name}**{chip_display}",
                inline=True,
            )

        # 피해자
        if game.victim:
            embed.add_field(
                name="🪦 피해자",
                value=f"{game.victim.emoji} **{game.victim.name}**",
                inline=False,
            )

        return embed

    @staticmethod
    def round_results(game: Game, result: dict, player_results: dict) -> discord.Embed:
        """라운드 결과 요약"""
        embed = discord.Embed(
            title=f"📊 라운드 {game.current_round} 결과",
            color=COLOR_RESULT,
        )

        result_lines = []
        for pid, info in player_results.items():
            p = game.players[pid]
            if info["correct"]:
                result_lines.append(
                    f"✅ {p.color_emoji} {p.name}: 정답! "
                    f"수사 칩 -1 (남은 수사칩: {p.investigation_chips})"
                )
            else:
                penalty_text = ""
                if info["penalty_received"] > 0:
                    penalty_text = f" + 무능 칩 +{info['penalty_received']}"
                result_lines.append(
                    f"❌ {p.color_emoji} {p.name}: 오답! "
                    f"수사 칩 -1{penalty_text} "
                    f"(수사: {p.investigation_chips} / 무능: {p.inept_chips})"
                )

        # 고발하지 않은 용의자에 쌓인 것은 없으므로 결과에 안 나온 플레이어 표시
        for pid in game.player_order:
            if pid not in player_results:
                p = game.players[pid]
                result_lines.append(
                    f"⬜ {p.color_emoji} {p.name}: "
                    f"(수사: {p.investigation_chips} / 무능: {p.inept_chips})"
                )

        embed.add_field(
            name="결과",
            value="\n".join(result_lines) if result_lines else "결과 없음",
            inline=False,
        )

        # 틀린 스택 상세
        wrong_stacks = result.get("wrong_stacks", {})
        if wrong_stacks:
            stack_lines = []
            for idx, stack_info in wrong_stacks.items():
                top_p = game.players[stack_info["top_player_id"]]
                chip_count = stack_info["chip_count"]
                stack_lines.append(
                    f"용의자 {idx + 1}: {top_p.name}이(가) "
                    f"무능 칩 {chip_count}개를 받습니다!"
                )
            embed.add_field(
                name="💀 틀린 스택 벌점",
                value="\n".join(stack_lines),
                inline=False,
            )

        # 다음 발견자
        next_discoverer = game.discoverer
        embed.add_field(
            name="🔍 다음 발견자",
            value=f"{next_discoverer.color_emoji} **{next_discoverer.name}**",
            inline=False,
        )

        return embed

    # ================================================================
    #  순위표
    # ================================================================

    @staticmethod
    def standings(game: Game) -> discord.Embed:
        """현재 순위표"""
        embed = discord.Embed(
            title="📊 현재 순위",
            color=COLOR_RESULT,
        )

        ranked = game.get_standings()
        lines = []
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for p, rank in ranked:
            ai_tag = " 🤖" if p.is_ai else ""
            lines.append(
                f"{medals[rank - 1]} {p.color_emoji} {p.name}{ai_tag}: "
                f"수사 {p.investigation_chips} / 무능 {p.inept_chips} "
                f"(총 {p.total_chips})"
            )

        embed.description = "\n".join(lines)
        embed.set_footer(text="총 칩이 적을수록 유리합니다!")
        return embed

    # ================================================================
    #  게임 종료
    # ================================================================

    @staticmethod
    def game_over(game: Game, over_info: dict) -> discord.Embed:
        """게임 종료 화면"""
        embed = discord.Embed(
            title="🏁 게임 종료!",
            description=over_info["reason"],
            color=COLOR_GAMEOVER,
        )

        # 패배자
        loser_id = over_info.get("loser_id")
        if loser_id and loser_id in game.players:
            loser = game.players[loser_id]
            embed.add_field(
                name="💀 패배",
                value=f"{loser.color_emoji} **{loser.name}**",
                inline=True,
            )

        # 승리자
        winner_id = over_info.get("winner_id")
        if winner_id and winner_id in game.players:
            winner = game.players[winner_id]
            embed.add_field(
                name="🏆 승리",
                value=f"{winner.color_emoji} **{winner.name}**",
                inline=True,
            )

        # 최종 순위
        ranked = game.get_standings()
        lines = []
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for p, rank in ranked:
            ai_tag = " 🤖" if p.is_ai else ""
            lines.append(
                f"{medals[rank - 1]} {p.color_emoji} {p.name}{ai_tag}: "
                f"수사 {p.investigation_chips} / 무능 {p.inept_chips} "
                f"(총 {p.total_chips})"
            )

        embed.add_field(
            name="📊 최종 순위",
            value="\n".join(lines),
            inline=False,
        )

        embed.set_footer(text="덤불쏭 게임을 플레이해주셔서 감사합니다!")
        return embed

    # ================================================================
    #  규칙 안내
    # ================================================================

    @staticmethod
    def rules() -> discord.Embed:
        """게임 규칙 안내"""
        embed = discord.Embed(
            title="📖 덤불쏭 - 규칙 안내",
            description="Jun Sasaki의 추리 블러핑 게임 (신판 규칙)",
            color=COLOR_LOBBY,
        )

        embed.add_field(
            name="🎯 목표",
            value=(
                "매 라운드 용의자 3명 중 범인을 맞추세요!\n"
                "수사 칩이 먼저 바닥나거나 총 칩이 8개 이상이면 패배합니다."
            ),
            inline=False,
        )

        embed.add_field(
            name="🃏 타일",
            value=(
                "• 숫자 1~8 + 빈 타일(❌) = 총 9장\n"
                "• 5가 없으면: 가장 **높은** 숫자 = 범인\n"
                "• 5가 있으면: 가장 **낮은** 숫자 = 범인\n"
                "• 빈 타일은 절대 범인이 될 수 없음"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔄 게임 흐름",
            value=(
                "1️⃣ 타일 1장을 받고 확인\n"
                "2️⃣ 오른쪽에 전달, 왼쪽에서 받음\n"
                "3️⃣ 발견자가 용의자 2명 확인 (+ 교체 가능)\n"
                "4️⃣ 발견자부터 시계방향으로 고발\n"
                "5️⃣ 용의자 공개 & 판정"
            ),
            inline=False,
        )

        embed.add_field(
            name="🪙 칩 규칙",
            value=(
                "• **정답**: 수사 칩 1개 제거 (게임에서 영구 제거)\n"
                "• **오답 (아래)**: 수사 칩 1개 잃음\n"
                "• **오답 (맨 위)**: 수사 칩 1개 잃고 + 스택 전체를 무능 칩으로 받음\n"
                "• 수사 칩 0개 → 패배 | 총 칩 8개 이상 → 패배"
            ),
            inline=False,
        )

        return embed
