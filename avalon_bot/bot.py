"""더 레지스탕스: 아발롬 디스코드 봇 - 메인 엔트리포인트"""

from __future__ import annotations
import asyncio
import logging
import random
from typing import Optional

import discord
from discord import app_commands

import config as cfg
from game.game import Game, GameManager
from game.enums import GameState, Vote, QuestVote, QuestResult, Role
from game.roles import get_night_info, ROLE_EMOJI
from game.ai import AIStrategy, reset_ai_names
from ui.embeds import EmbedBuilder
from ui.views import (
    LobbyView,
    TeamSelectView,
    TeamVoteView,
    RoleCheckView,
    QuestVoteChannelView,
    AssassinSelectView,
    GameOverView,
    ConfirmView,
)

# ── 로깅 ──
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("avalon")

# ── 봇 설정 ──
intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
manager = GameManager()

# AI 딜레이
AI_DELAY = 1.5


# ================================================================
#  슬래시 커맨드
# ================================================================

@tree.command(name="아발롬", description="더 레지스탕스: 아발롬 게임을 시작합니다!")
async def start_game_command(interaction: discord.Interaction):
    channel_id = interaction.channel_id

    existing = manager.get_game(channel_id)
    if existing and existing.state != GameState.GAME_OVER:
        await interaction.response.send_message(
            "⚠️ 이 채널에서 이미 게임이 진행 중입니다!", ephemeral=True
        )
        return

    reset_ai_names()
    game = manager.create_game(channel_id, interaction.user)
    game.add_player(interaction.user)

    lobby_view = LobbyView(game)
    embed = EmbedBuilder.lobby(game)
    await interaction.response.send_message(embed=embed, view=lobby_view)

    timed_out = await lobby_view.wait()

    if timed_out or not lobby_view.started:
        if timed_out:
            await interaction.followup.send("⏰ 로비 시간이 초과되었습니다.")
        manager.remove_game(channel_id)
        return

    channel = interaction.channel
    await run_game(channel, game)


@tree.command(name="아발롬규칙", description="아발롬 게임 규칙을 확인합니다.")
async def rules_command(interaction: discord.Interaction):
    embed = EmbedBuilder.rules()
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ================================================================
#  진행 확인 헬퍼
# ================================================================

async def send_and_confirm(channel, game, **send_kwargs):
    """메시지를 보내고 모든 인간 플레이어가 확인할 때까지 대기."""
    human_ids = set()
    for p in game.player_list:
        if not p.is_ai:
            human_ids.add(p.id)
    if not human_ids:
        await channel.send(**send_kwargs)
        await asyncio.sleep(AI_DELAY)
        return
    view = ConfirmView(human_ids)
    await channel.send(view=view, **send_kwargs)
    await view.all_confirmed.wait()


# ================================================================
#  게임 루프
# ================================================================

async def run_game(channel: discord.TextChannel, game: Game):
    """전체 게임 루프"""
    try:
        # ── 1) 밤 단계: 역할 배정 ──
        game.start_game()

        embed = EmbedBuilder.night_announce(game)
        await send_and_confirm(channel, game, embed=embed)

        # 채널에 역할 확인 버튼 게시 (ephemeral)
        await send_role_check(channel, game)
        await asyncio.sleep(2)

        # ── 2) 퀘스트 루프 ──
        while True:
            # 퀘스트 보드 표시
            embed = EmbedBuilder.quest_board(game)
            await send_and_confirm(channel, game, embed=embed)

            # ── 원정대 편성 + 투표 루프 ──
            team_approved = False
            while not team_approved:
                game.start_team_build()

                # 원정대 편성
                embed = EmbedBuilder.team_build(game)
                await channel.send(embed=embed)

                team_ids = await build_team(channel, game)
                if team_ids is None:
                    # 타임아웃 → 자동 편성
                    team_ids = _auto_team(game)

                game.set_team(team_ids)

                # 원정대 제안 공개
                embed = EmbedBuilder.team_proposed(game)
                await send_and_confirm(channel, game, embed=embed)

                # 팀 투표
                game.start_team_vote()
                await team_vote_phase(channel, game)

                approved, approve_count, reject_count = game.resolve_team_vote()
                embed = EmbedBuilder.team_vote_result(
                    game, approved, approve_count, reject_count
                )
                await send_and_confirm(channel, game, embed=embed)

                if approved:
                    team_approved = True
                else:
                    # 거부 → 연속 거부 체크
                    if game.check_rejection_limit():
                        embed = EmbedBuilder.game_over_rejection(game)
                        game.state = GameState.GAME_OVER
                        view = GameOverView()
                        await channel.send(embed=embed, view=view)
                        manager.remove_game(channel.id)
                        return

                    game.advance_leader()
                    await send_and_confirm(
                        channel, game,
                        content=f"👑 다음 리더: **{game.leader.name}**"
                    )

            # ── 퀘스트 수행 ──
            game.start_quest()
            await quest_phase(channel, game)

            result, s_count, f_count = game.resolve_quest()
            embed = EmbedBuilder.quest_result(game, result, s_count, f_count)
            await send_and_confirm(channel, game, embed=embed)

            # ── 승패 체크 ──
            if game.check_evil_wins_quests():
                embed = EmbedBuilder.game_over_evil_quests(game)
                game.state = GameState.GAME_OVER
                view = GameOverView()
                await channel.send(embed=embed, view=view)
                manager.remove_game(channel.id)
                return

            if game.check_good_wins_quests():
                # 선 퀘스트 3승 → 암살자 단계
                await assassin_phase(channel, game)
                return

            # ── 다음 퀘스트 ──
            game.advance_leader()
            if not game.advance_quest():
                # 더 이상 퀘스트 없음 (이론상 도달 불가)
                break

            await asyncio.sleep(1)

    except Exception as e:
        log.error(f"게임 루프 에러: {e}", exc_info=True)
        await channel.send(f"❌ 게임 중 오류가 발생했습니다: {e}")
        manager.remove_game(channel.id)


# ================================================================
#  역할 확인 (ephemeral)
# ================================================================

async def send_role_check(channel: discord.TextChannel, game: Game):
    """채널에 역할 확인 버튼을 게시한다. 클릭 시 ephemeral로 역할 정보 전송."""
    role_view = RoleCheckView(game)
    await channel.send(
        "🔍 아래 버튼을 눌러 **자신의 역할**을 확인하세요! (본인에게만 보입니다)",
        view=role_view,
    )


# ================================================================
#  원정대 편성
# ================================================================

async def build_team(channel: discord.TextChannel, game: Game) -> Optional[list]:
    """리더가 원정대를 편성한다."""
    leader = game.leader

    if leader.is_ai:
        # AI 리더
        await asyncio.sleep(AI_DELAY)
        team_ids = AIStrategy.propose_team(
            leader=leader,
            all_players=game.player_list,
            team_size=game.current_quest.team_size,
            quest_history=game.quest_history,
        )
        team_names = [game.players[pid].name for pid in team_ids]
        embed = EmbedBuilder.ai_team_propose(leader, team_names)
        await channel.send(embed=embed)
        return team_ids
    else:
        # 인간 리더
        select_view = TeamSelectView(game, timeout=90)
        msg = await channel.send(
            f"👑 **{leader.name}**, 원정대를 편성해주세요!",
            view=select_view,
        )

        timed_out = await select_view.wait()
        if timed_out or not select_view.done:
            await channel.send(
                f"⏰ {leader.name} 시간 초과! 자동으로 편성합니다."
            )
            return None
        return select_view.selected_ids


def _auto_team(game: Game) -> list:
    """자동 원정대 편성 (타임아웃 시)"""
    size = game.current_quest.team_size
    ids = list(game.player_order)
    random.shuffle(ids)
    return ids[:size]


# ================================================================
#  팀 투표
# ================================================================

async def team_vote_phase(channel: discord.TextChannel, game: Game):
    """모든 플레이어가 원정대에 투표한다."""

    # AI 먼저 투표
    for p in game.player_list:
        if p.is_ai:
            vote = AIStrategy.vote_team(
                player=p,
                team_ids=game.current_team_ids,
                all_players=game.player_list,
                rejection_count=game.rejection_count,
                quest_history=game.quest_history,
            )
            game.cast_team_vote(p.id, vote)

    # 인간 투표가 필요한지 확인
    human_count = sum(1 for p in game.player_list if not p.is_ai)

    if human_count == 0:
        # 전원 AI
        await asyncio.sleep(AI_DELAY)
        return

    # 인간 투표 뷰
    vote_view = TeamVoteView(game, timeout=60)
    msg = await channel.send(
        "📮 원정대에 대해 투표해주세요! (찬성/반대)",
        view=vote_view,
    )

    timed_out = await vote_view.wait()

    if timed_out or not vote_view.done:
        # 타임아웃: 투표 안 한 인간은 자동 찬성
        for p in game.player_list:
            if not p.is_ai and p.id not in game.current_quest.team_votes:
                game.cast_team_vote(p.id, Vote.APPROVE)
        await channel.send("⏰ 시간 초과! 미투표자는 자동 찬성 처리됩니다.")


# ================================================================
#  퀘스트 수행
# ================================================================

async def quest_phase(channel: discord.TextChannel, game: Game):
    """원정대원이 퀘스트를 수행한다 (비밀 투표 - 채널 ephemeral)."""
    team_ids = game.current_team_ids
    quest = game.current_quest

    # AI 먼저 처리
    for pid in team_ids:
        p = game.players[pid]
        if p.is_ai:
            vote = AIStrategy.quest_vote(
                player=p,
                quest_number=quest.quest_number,
                success_count=game.success_count,
                fail_count=game.fail_count,
            )
            game.cast_quest_vote(pid, vote)

    # 인간 원정대원이 있는지 확인
    human_team_ids = [
        pid for pid in team_ids if not game.players[pid].is_ai
    ]

    if human_team_ids:
        # 채널에 퀘스트 투표 뷰 게시
        team_names = [game.players[pid].name for pid in team_ids]
        vote_view = QuestVoteChannelView(game, team_ids, timeout=60)
        await channel.send(
            f"🏔️ **퀘스트 {quest.quest_number}** - 원정대가 퀘스트를 수행합니다!\n"
            f"원정대원: {', '.join(team_names)}\n"
            "원정대원은 아래 버튼으로 투표해주세요! (본인에게만 보입니다)",
            view=vote_view,
        )

        # 모든 인간이 투표하거나 타임아웃될 때까지 대기
        await vote_view.done.wait()

        # 투표 결과를 게임에 반영
        for pid, success in vote_view.votes.items():
            qvote = QuestVote.SUCCESS if success else QuestVote.FAIL
            game.cast_quest_vote(pid, qvote)

        # 타임아웃 시 미투표자 자동 성공
        if vote_view.timed_out:
            for pid in human_team_ids:
                if pid not in vote_view.votes:
                    game.cast_quest_vote(pid, QuestVote.SUCCESS)
            await channel.send("⏰ 시간 초과! 미투표 원정대원은 자동 성공 처리됩니다.")
    else:
        # 전원 AI
        await asyncio.sleep(AI_DELAY)

    # 모두 투표했는지 최종 확인
    if not game.all_quest_voted():
        for pid in team_ids:
            if pid not in quest.quest_votes:
                game.cast_quest_vote(pid, QuestVote.SUCCESS)

    await channel.send("📜 모든 원정대원이 투표를 완료했습니다!")


# ================================================================
#  암살자 단계
# ================================================================

async def assassin_phase(channel: discord.TextChannel, game: Game):
    """선이 퀘스트 3승 → 암살자가 멀린을 지목한다."""
    game.start_assassin_phase()

    embed = EmbedBuilder.assassin_phase(game)
    await send_and_confirm(channel, game, embed=embed)

    assassin = game.get_assassin()
    if assassin is None:
        # 암살자 없음 (이론상 불가)
        game.state = GameState.GAME_OVER
        embed = EmbedBuilder.game_over_good(game, assassin_hit=False)
        view = GameOverView()
        await channel.send(embed=embed, view=view)
        manager.remove_game(channel.id)
        return

    if assassin.is_ai:
        # AI 암살자
        await asyncio.sleep(AI_DELAY * 2)
        target_id = AIStrategy.choose_merlin(
            assassin=assassin,
            all_players=game.player_list,
            quest_history=game.quest_history,
        )
        target = game.players.get(target_id)
        await send_and_confirm(
            channel, game,
            content=f"🗡️ **{assassin.name}**이(가) **{target.name if target else '???'}**을(를) 멀린으로 지목합니다!"
        )
    else:
        # 인간 암살자
        select_view = AssassinSelectView(game, timeout=90)
        await channel.send(
            f"🗡️ **{assassin.name}**, 멀린이라고 생각되는 사람을 지목하세요!",
            view=select_view,
        )

        timed_out = await select_view.wait()
        if timed_out or not select_view.done:
            # 타임아웃: 랜덤 지목
            target_id = random.choice(game.good_players).id
            await channel.send(
                f"⏰ 시간 초과! 자동으로 지목합니다."
            )
        else:
            target_id = select_view.target_id

    await asyncio.sleep(2)

    is_merlin, target = game.assassinate(target_id)
    embed = EmbedBuilder.game_over_good(game, assassin_hit=is_merlin, target=target)
    view = GameOverView()
    await channel.send(embed=embed, view=view)
    manager.remove_game(channel.id)


# ================================================================
#  봇 이벤트
# ================================================================

@bot.event
async def on_ready():
    await tree.sync()
    log.info(f"✅ {bot.user.name} 준비 완료! (ID: {bot.user.id})")
    log.info(f"📡 {len(bot.guilds)}개 서버에 연결됨")


# ================================================================
#  실행
# ================================================================

if __name__ == "__main__":
    if not cfg.DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN이 설정되지 않았습니다!")
        print("   .env 파일에 DISCORD_TOKEN=your_token_here를 추가하세요.")
    else:
        bot.run(cfg.DISCORD_TOKEN)
