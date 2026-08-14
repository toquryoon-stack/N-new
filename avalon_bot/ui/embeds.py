"""Discord Embed 빌더 - 아발롬 게임 UI"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
import discord

if TYPE_CHECKING:
    from game.game import Game
    from game.player import Player
    from game.quest import Quest

from game.enums import Role, Team, Vote, QuestVote, QuestResult
from game.roles import ROLE_EMOJI, ROLE_DESCRIPTION, get_team, get_night_info
import config as cfg


# ── 색상 상수 ──
COLOR_LOBBY = 0x2ECC71       # 초록 - 로비
COLOR_NIGHT = 0x2C3E50       # 진남 - 밤
COLOR_TEAM = 0x3498DB        # 파랑 - 원정대
COLOR_VOTE = 0xE67E22        # 주황 - 투표
COLOR_QUEST_OK = 0x27AE60    # 녹색 - 퀘스트 성공
COLOR_QUEST_FAIL = 0xE74C3C  # 빨강 - 퀘스트 실패
COLOR_ASSASSIN = 0x8E44AD    # 보라 - 암살
COLOR_GOOD_WIN = 0xF1C40F    # 금색 - 선 승리
COLOR_EVIL_WIN = 0xC0392B    # 암적 - 악 승리

# ── 디스코드 "ansi" 코드블록 색상 (데스크톱 클라이언트에서 실제 색으로 렌더링됨) ──
ANSI_RESET = "\x1b[0m"
ANSI_BOLD_RED = "\x1b[1;31m"
ANSI_BOLD_BLUE = "\x1b[1;34m"


def _ansi_block(text: str) -> str:
    return "```ansi\n" + text + "\n```"


class EmbedBuilder:
    """게임 상태별 Embed 생성"""

    # ================================================================
    #  로비
    # ================================================================

    @staticmethod
    def lobby(game: Game) -> discord.Embed:
        embed = discord.Embed(
            title="🏰 더 레지스탕스: 아발롬",
            description=(
                "선과 악의 치열한 두뇌 싸움!\n"
                "아서 왕의 충신이 되어 퀘스트를 성공시키거나,\n"
                "모드레드의 하수인이 되어 퀘스트를 방해하세요!\n\n"
                f"👥 플레이어: **{game.player_count}명** / {cfg.MIN_PLAYERS}~{cfg.MAX_PLAYERS}명"
            ),
            color=COLOR_LOBBY,
        )

        player_lines = []
        for p in game.player_list:
            prefix = "👑 " if p.user == game.host else ""
            ai_tag = " 🤖" if p.is_ai else ""
            player_lines.append(f"{prefix}{p.name}{ai_tag}")

        embed.add_field(
            name="참가자",
            value="\n".join(player_lines) if player_lines else "_아직 아무도 없습니다..._",
            inline=False,
        )

        if game.player_count >= cfg.MIN_PLAYERS:
            good, evil = cfg.TEAM_COMPOSITION.get(game.player_count, (0, 0))
            embed.add_field(
                name="⚔️ 진영 구성",
                value=f"선의 진영 {good}명 vs 악의 진영 {evil}명",
                inline=False,
            )
            embed.set_footer(text="호스트가 게임 시작 버튼을 눌러주세요!")
        else:
            need = cfg.MIN_PLAYERS - game.player_count
            embed.set_footer(text=f"최소 {cfg.MIN_PLAYERS}명이 필요합니다. {need}명 더 참가해주세요!")

        return embed

    # ================================================================
    #  밤 단계 (역할 확인)
    # ================================================================

    @staticmethod
    def night_role_dm(player: Player, all_players: List[Player]) -> discord.Embed:
        role = player.role
        team = get_team(role) if role else None
        emoji = ROLE_EMOJI.get(role, "❓")
        team_color = COLOR_QUEST_OK if team == Team.GOOD else COLOR_QUEST_FAIL

        embed = discord.Embed(
            title=f"{emoji} 당신의 역할",
            color=team_color,
        )

        night_info = get_night_info(player, all_players)
        embed.description = night_info

        team_name = "선의 진영 (아서 왕)" if team == Team.GOOD else "악의 진영 (모드레드)"
        embed.add_field(
            name="소속",
            value=f"**{team_name}**",
            inline=False,
        )

        if team == Team.GOOD:
            embed.set_footer(text="퀘스트를 성공시켜 악을 물리치세요!")
        else:
            embed.set_footer(text="정체를 숨기고 퀘스트를 방해하세요!")

        return embed

    @staticmethod
    def night_announce(game: Game) -> discord.Embed:
        embed = discord.Embed(
            title="🌙 밤이 되었습니다...",
            description=(
                "역할이 배정되었습니다.\n"
                "아래 버튼을 눌러 자신의 역할을 확인하세요!\n\n"
                "잠시 후 첫 번째 퀘스트가 시작됩니다."
            ),
            color=COLOR_NIGHT,
        )

        good_count, evil_count = cfg.TEAM_COMPOSITION[game.player_count]
        embed.add_field(
            name="⚔️ 진영 구성",
            value=f"선 {good_count}명 vs 악 {evil_count}명",
            inline=True,
        )
        special_roles = "멀린, 퍼시벌, 모르가나, 암살자"
        if evil_count == 3:
            special_roles += ", 모드레드"
        embed.add_field(
            name="🧙 특수 역할",
            value=special_roles,
            inline=True,
        )

        return embed

    # ================================================================
    #  퀘스트 보드
    # ================================================================

    @staticmethod
    def quest_board(game: Game) -> discord.Embed:
        embed = discord.Embed(
            title="📋 퀘스트 보드",
            color=COLOR_TEAM,
        )

        board_line = ""
        for i, q in enumerate(game.quests):
            if q.result == QuestResult.SUCCESS:
                icon = "🔵"
            elif q.result == QuestResult.FAIL:
                icon = "🔴"
            elif i == game.current_quest_idx:
                icon = "⬜"  # 현재
            else:
                icon = "⚪"

            double = " (실패2)" if q.requires_double_fail else ""
            board_line += f"{icon} 퀘스트 {q.quest_number} [{q.team_size}명{double}]\n"

        embed.description = board_line

        embed.add_field(
            name="현재 점수",
            value=f"🔵 성공 **{game.success_count}** / 🔴 실패 **{game.fail_count}**",
            inline=True,
        )

        if game.rejection_count > 0:
            embed.add_field(
                name="⚠️ 연속 거부",
                value=f"**{game.rejection_count}** / {cfg.MAX_REJECTIONS} (5회시 악 승리!)",
                inline=True,
            )

        return embed

    # ================================================================
    #  원정대 편성
    # ================================================================

    @staticmethod
    def team_build(game: Game) -> discord.Embed:
        quest = game.current_quest
        leader = game.leader

        embed = discord.Embed(
            title=f"⚔️ 퀘스트 {quest.quest_number} - 원정대 편성",
            description=(
                f"👑 리더 **{leader.name}**이(가) "
                f"원정대 **{quest.team_size}명**을 선택합니다."
            ),
            color=COLOR_TEAM,
        )

        # 플레이어 목록
        player_lines = []
        for p in game.player_list:
            is_leader = " 👑" if p.id == leader.id else ""
            ai_tag = " 🤖" if p.is_ai else ""
            player_lines.append(f"• {p.name}{is_leader}{ai_tag}")

        embed.add_field(
            name=f"플레이어 ({game.player_count}명)",
            value="\n".join(player_lines),
            inline=False,
        )

        if quest.requires_double_fail:
            embed.set_footer(text="⚠️ 이 퀘스트는 실패 2개가 필요합니다!")
        else:
            embed.set_footer(text="리더가 원정대를 선택해주세요!")

        return embed

    @staticmethod
    def team_proposed(game: Game) -> discord.Embed:
        quest = game.current_quest
        leader = game.leader

        team_names = [game.players[pid].name for pid in game.current_team_ids]

        embed = discord.Embed(
            title=f"📣 원정대 제안 - 퀘스트 {quest.quest_number}",
            description=(
                f"👑 리더 **{leader.name}**의 원정대:\n\n"
                + "\n".join(f"⚔️ **{name}**" for name in team_names)
            ),
            color=COLOR_VOTE,
        )

        embed.add_field(
            name="📮 투표",
            value="모든 플레이어가 이 원정대에 찬성/반대 투표를 합니다!",
            inline=False,
        )

        if game.rejection_count > 0:
            embed.add_field(
                name="⚠️ 연속 거부",
                value=f"현재 {game.rejection_count}회 (5회시 악의 자동 승리!)",
                inline=False,
            )

        return embed

    # ================================================================
    #  투표 결과
    # ================================================================

    @staticmethod
    def team_vote_result(
        game: Game,
        approved: bool,
        approve_count: int,
        reject_count: int,
    ) -> discord.Embed:
        quest = game.current_quest

        if approved:
            embed = discord.Embed(
                title="✅ 원정대 승인!",
                description=f"찬성 **{approve_count}** vs 반대 **{reject_count}**",
                color=COLOR_QUEST_OK,
            )
        else:
            embed = discord.Embed(
                title="❌ 원정대 거부!",
                description=f"찬성 **{approve_count}** vs 반대 **{reject_count}**",
                color=COLOR_QUEST_FAIL,
            )

        # 개별 투표 공개 (찬성 O=파랑, 반대 X=빨강)
        vote_lines = []
        for pid in game.player_order:
            p = game.players[pid]
            v = quest.team_votes.get(pid)
            if v == Vote.APPROVE:
                vote_lines.append(f"{ANSI_BOLD_BLUE}O {p.name}{ANSI_RESET}")
            elif v == Vote.REJECT:
                vote_lines.append(f"{ANSI_BOLD_RED}X {p.name}{ANSI_RESET}")

        embed.add_field(
            name="투표 결과",
            value=_ansi_block("\n".join(vote_lines)),
            inline=False,
        )

        if not approved:
            embed.add_field(
                name="⚠️ 연속 거부",
                value=f"{game.rejection_count} / {cfg.MAX_REJECTIONS}",
                inline=True,
            )
            embed.set_footer(text="다음 리더가 새로운 원정대를 편성합니다.")

        return embed

    # ================================================================
    #  퀘스트 결과
    # ================================================================

    @staticmethod
    def quest_result(
        game: Game,
        result: QuestResult,
        success_count: int,
        fail_count: int,
    ) -> discord.Embed:
        quest = game.current_quest

        if result == QuestResult.SUCCESS:
            embed = discord.Embed(
                title=f"🔵 퀘스트 {quest.quest_number} 성공!",
                description="원정대가 퀘스트를 성공적으로 수행했습니다!",
                color=COLOR_QUEST_OK,
            )
        else:
            embed = discord.Embed(
                title=f"🔴 퀘스트 {quest.quest_number} 실패!",
                description="원정대 안에 배신자가 있었습니다!",
                color=COLOR_QUEST_FAIL,
            )

        embed.add_field(
            name="퀘스트 카드",
            value=f"성공 **{success_count}** / 실패 **{fail_count}**",
            inline=True,
        )

        # 전체 점수
        embed.add_field(
            name="전체 점수",
            value=f"🔵 성공 **{game.success_count}** / 🔴 실패 **{game.fail_count}**",
            inline=True,
        )

        team_names = [game.players[pid].name for pid in quest.team_member_ids]
        embed.add_field(
            name="원정대원",
            value=", ".join(team_names),
            inline=False,
        )

        return embed

    # ================================================================
    #  AI 행동 알림
    # ================================================================

    @staticmethod
    def ai_team_propose(leader: Player, team_names: List[str]) -> discord.Embed:
        embed = discord.Embed(
            title="🤖 AI 원정대 편성",
            description=(
                f"👑 **{leader.name}**이(가) 원정대를 편성했습니다:\n\n"
                + "\n".join(f"⚔️ **{name}**" for name in team_names)
            ),
            color=COLOR_TEAM,
        )
        return embed

    @staticmethod
    def ai_vote_notice(player: Player) -> discord.Embed:
        embed = discord.Embed(
            description=f"🤖 **{player.name}**이(가) 투표했습니다.",
            color=COLOR_VOTE,
        )
        return embed

    # ================================================================
    #  암살자 단계
    # ================================================================

    @staticmethod
    def assassin_phase(game: Game) -> discord.Embed:
        assassin = game.get_assassin()

        embed = discord.Embed(
            title="🗡️ 암살자의 시간!",
            description=(
                "선의 진영이 퀘스트 3개를 성공시켰습니다!\n"
                "하지만 아직 끝이 아닙니다...\n\n"
                f"🗡️ **{assassin.name if assassin else '???'}**이(가) "
                f"멀린을 지목합니다.\n"
                "멀린을 맞추면 악의 역전승!"
            ),
            color=COLOR_ASSASSIN,
        )

        # 선 플레이어 목록 (암살 대상 후보)
        good_players = game.good_players
        candidate_lines = [f"• {p.name}" for p in good_players]
        embed.add_field(
            name="🎯 선의 진영 플레이어",
            value="\n".join(candidate_lines),
            inline=False,
        )

        return embed

    # ================================================================
    #  게임 종료
    # ================================================================

    @staticmethod
    def game_over_good(game: Game, assassin_hit: bool, target: Optional[Player] = None) -> discord.Embed:
        if assassin_hit:
            # 암살 성공 → 악 승리
            embed = discord.Embed(
                title="🔴 악의 진영 승리!",
                description=(
                    f"🗡️ 암살자가 **{target.name if target else '???'}**을(를) 지목했습니다.\n"
                    "**멀린이 암살당했습니다!**\n\n"
                    "악의 진영이 역전승을 거뒀습니다!"
                ),
                color=COLOR_EVIL_WIN,
            )
        else:
            # 암살 실패 → 선 승리
            merlin = game.get_merlin()
            embed = discord.Embed(
                title="🔵 선의 진영 승리!",
                description=(
                    f"🗡️ 암살자가 **{target.name if target else '???'}**을(를) 지목했지만...\n"
                    f"**멀린은 {merlin.name if merlin else '???'}이었습니다!**\n\n"
                    "멀린이 살아남았습니다! 선의 진영 승리!"
                ),
                color=COLOR_GOOD_WIN,
            )

        # 역할 공개
        _add_role_reveal(embed, game)
        return embed

    @staticmethod
    def game_over_evil_quests(game: Game) -> discord.Embed:
        embed = discord.Embed(
            title="🔴 악의 진영 승리!",
            description="퀘스트 3개가 실패했습니다!\n악의 진영이 승리합니다!",
            color=COLOR_EVIL_WIN,
        )
        _add_role_reveal(embed, game)
        return embed

    @staticmethod
    def game_over_rejection(game: Game) -> discord.Embed:
        embed = discord.Embed(
            title="🔴 악의 진영 승리!",
            description=(
                f"원정대가 {cfg.MAX_REJECTIONS}회 연속 거부되었습니다!\n"
                "혼란 속에서 악의 진영이 승리합니다!"
            ),
            color=COLOR_EVIL_WIN,
        )
        _add_role_reveal(embed, game)
        return embed

    @staticmethod
    def game_over_cancelled() -> discord.Embed:
        embed = discord.Embed(
            title="🛑 게임 취소",
            description="게임이 취소되었습니다.",
            color=0x95A5A6,
        )
        return embed

    # ================================================================
    #  규칙 안내
    # ================================================================

    @staticmethod
    def rules() -> discord.Embed:
        embed = discord.Embed(
            title="📖 더 레지스탕스: 아발롬 - 규칙",
            color=COLOR_LOBBY,
        )

        embed.add_field(
            name="🎯 목표",
            value=(
                "**선**: 퀘스트 3개를 성공시키고 멀린을 지켜라!\n"
                "**악**: 퀘스트 3개를 실패시키거나 멀린을 찾아라!"
            ),
            inline=False,
        )

        embed.add_field(
            name="🧙 역할",
            value=(
                "**선의 진영:**\n"
                "🧙 멀린 - 악의 정체를 알지만 들키면 안 됨\n"
                "🛡️ 퍼시벌 - 멀린이 누군지 알지만 모르가나와 구분 불가\n"
                "⚔️ 충신 - 특별한 능력 없음\n\n"
                "**악의 진영:**\n"
                "🗡️ 암살자 - 마지막에 멀린을 지목 가능\n"
                "🧝‍♀️ 모르가나 - 퍼시벌에게 멀린으로 보임\n"
                "👹 모드레드 - 멀린에게도 정체가 보이지 않음 (악 3명일 때 등장)\n"
                "👤 하수인 - 특별한 능력 없음"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔄 게임 흐름",
            value=(
                "1️⃣ 리더가 원정대 편성\n"
                "2️⃣ 모두가 찬성/반대 투표 (과반수)\n"
                "3️⃣ 승인시 → 원정대가 퀘스트 수행 (비밀 투표)\n"
                "4️⃣ 거부시 → 다음 리더 (5회 연속 거부 = 악 승리)\n"
                "5️⃣ 성공 3개 → 암살자가 멀린 지목 (맞추면 악 역전승)\n"
                "5️⃣ 실패 3개 → 악 승리"
            ),
            inline=False,
        )

        embed.add_field(
            name="📊 인원별 구성",
            value=(
                "5명: 선3/악2, 퀘스트 2-3-2-3-3\n"
                "6명: 선4/악2, 퀘스트 2-3-4-3-4\n"
                "7명: 선4/악3, 퀘스트 2-3-3-4*-4\n"
                "8명: 선5/악3, 퀘스트 3-4-4-5*-5\n"
                "9명: 선6/악3, 퀘스트 3-4-4-5*-5\n"
                "10명: 선6/악4, 퀘스트 3-4-4-5*-5\n"
                "\\* = 실패 2개 필요"
            ),
            inline=False,
        )

        return embed


# ── 헬퍼 ──

def _add_role_reveal(embed: discord.Embed, game: Game) -> None:
    """역할 공개 필드를 Embed에 추가한다."""
    good_lines = []
    evil_lines = []
    for p in game.player_list:
        role = p.role
        emoji = ROLE_EMOJI.get(role, "❓") if role else "❓"
        role_name = role.value if role else "???"
        ai_tag = " 🤖" if p.is_ai else ""
        line = f"{emoji} {p.name}{ai_tag} - **{role_name}**"
        if p.is_good:
            good_lines.append(line)
        else:
            evil_lines.append(line)

    embed.add_field(
        name="🔵 선의 진영",
        value="\n".join(good_lines) if good_lines else "없음",
        inline=True,
    )
    embed.add_field(
        name="🔴 악의 진영",
        value="\n".join(evil_lines) if evil_lines else "없음",
        inline=True,
    )
