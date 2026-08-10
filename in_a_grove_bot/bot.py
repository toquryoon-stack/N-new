"""덤불쏭 디스코드 봇 - 메인 엔트리포인트"""

from __future__ import annotations
import asyncio
import logging
from typing import Optional

import discord
from discord import app_commands

import config as cfg
from game.game import Game, GameManager
from game.ai import AIStrategy, reset_ai_names
from game.enums import GameState
from ui.embeds import EmbedBuilder
from ui.views import (
    LobbyView,
    TileCheckView,
    DiscovererStartView,
    SuspectPeekView,
    AccusationView,
    NextRoundView,
    GameOverView,
)

# ── 로깅 ──
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("in_a_grove")

# ── 봇 설정 ──
intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
manager = GameManager()

# AI 딜레이 (자연스러운 느낌)
AI_DELAY = 1.5


# ================================================================
#  슬래시 커맨드
# ================================================================

@tree.command(name="덤불쏭", description="덤불쏭 게임을 시작합니다!")
async def start_game_command(interaction: discord.Interaction):
    """게임 로비를 생성한다."""
    channel_id = interaction.channel_id

    # 이미 진행 중인 게임이 있는지 확인
    existing = manager.get_game(channel_id)
    if existing and existing.state != GameState.GAME_OVER:
        await interaction.response.send_message(
            "⚠️ 이 채널에서 이미 게임이 진행 중입니다!", ephemeral=True
        )
        return

    # 새 게임 생성
    reset_ai_names()
    game = manager.create_game(channel_id, interaction.user)
    game.add_player(interaction.user)

    lobby_view = LobbyView(game)
    embed = EmbedBuilder.lobby(game)

    await interaction.response.send_message(embed=embed, view=lobby_view)

    # 로비 대기
    timed_out = await lobby_view.wait()

    if timed_out or not lobby_view.started:
        if timed_out:
            await interaction.followup.send("⏰ 로비 시간이 초과되었습니다. 게임이 취소됩니다.")
        manager.remove_game(channel_id)
        return

    # 게임 시작!
    channel = interaction.channel
    await run_game(channel, game)


@tree.command(name="덤불쏭규칙", description="덤불쏭 게임 규칙을 확인합니다.")
async def rules_command(interaction: discord.Interaction):
    """게임 규칙 안내"""
    embed = EmbedBuilder.rules()
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ================================================================
#  게임 루프
# ================================================================

async def run_game(channel: discord.TextChannel, game: Game):
    """전체 게임 루프를 실행한다."""
    try:
        while True:
            # ── 1) 라운드 시작 ──
            game.start_round()
            embed = EmbedBuilder.round_start(game)
            await channel.send(embed=embed)
            await asyncio.sleep(1)

            # ── 2) 타일 전달 ──
            game.pass_tiles()
            await channel.send("🔄 타일이 오른쪽 플레이어에게 전달되었습니다!")
            await asyncio.sleep(0.5)

            # ── 3) 타일 확인 안내 (원래 타일 + 전달받은 타일을 한 메시지로) ──
            await send_tile_check_prompt(channel, game)
            await asyncio.sleep(1)

            # ── 4) 발견자 수사 ──
            await discoverer_phase(channel, game)
            await asyncio.sleep(1)

            # ── 5) 고발 단계 ──
            await accusation_phase(channel, game)
            await asyncio.sleep(1)

            # ── 6) 공개 & 판정 ──
            result = game.reveal_and_judge()
            embed = EmbedBuilder.reveal_suspects(game, result)
            await channel.send(embed=embed)
            await asyncio.sleep(2)

            # ── 7) 결과 적용 ──
            player_results = game.apply_results(result)
            embed = EmbedBuilder.round_results(game, result, player_results)
            await channel.send(embed=embed)

            # ── 8) 게임 종료 체크 ──
            over_info = game.check_game_over()
            if over_info:
                game.state = GameState.GAME_OVER
                embed = EmbedBuilder.game_over(game, over_info)
                view = GameOverView()
                await channel.send(embed=embed, view=view)
                manager.remove_game(channel.id)
                return

            # ── 9) 다음 라운드 대기 ──
            next_view = NextRoundView(host_id=game.host.id)
            await channel.send(
                "▶️ 다음 라운드를 시작하려면 호스트가 버튼을 눌러주세요!",
                view=next_view,
            )

            timed_out = await next_view.wait()
            if timed_out or not next_view.proceed:
                game.state = GameState.GAME_OVER
                await channel.send("🛑 게임이 종료되었습니다.")
                manager.remove_game(channel.id)
                return

    except Exception as e:
        log.error(f"게임 루프 에러: {e}", exc_info=True)
        await channel.send(f"❌ 게임 중 오류가 발생했습니다: {e}")
        manager.remove_game(channel.id)


# ================================================================
#  타일 확인 (채널 버튼, 본인에게만 보이는 응답)
# ================================================================

async def send_tile_check_prompt(channel: discord.TextChannel, game: Game):
    """채널에 타일 확인 버튼을 올린다. 원래 받은 타일과 전달받은 타일을
    한 메시지(본인에게만 보이는 응답)로 함께 보여준다. 사람 플레이어가
    없으면 생략한다."""
    if not any(not p.is_ai for p in game.player_list):
        return

    view = TileCheckView(game)
    await channel.send(
        "🃏 아래 버튼을 눌러 본인만 볼 수 있는 타일 정보를 확인하세요!",
        view=view,
    )


# ================================================================
#  발견자 수사
# ================================================================

async def discoverer_phase(channel: discord.TextChannel, game: Game):
    """발견자가 용의자 2명을 확인하고, 교체를 결정한다."""
    discoverer = game.discoverer

    await channel.send(
        f"🔍 {discoverer.color_emoji} **{discoverer.name}**이(가) 현장을 수사합니다..."
    )

    if discoverer.is_ai:
        # ── AI 발견자 ──
        await asyncio.sleep(AI_DELAY)
        chosen = AIStrategy.choose_suspects_to_view()
        viewed = game.set_discoverer_viewed(chosen)

        await channel.send(
            f"🤖 {discoverer.name}이(가) 용의자 2명을 확인했습니다."
        )

        # AI 교체 결정
        await asyncio.sleep(AI_DELAY)
        swap_idx = AIStrategy.decide_swap_victim(
            viewed_suspects=viewed,
            victim_tile=game.victim,
            known_tiles=discoverer.known_tiles,
        )

        if swap_idx is not None:
            game.swap_victim(swap_idx)
            await channel.send(
                f"🔄 {discoverer.name}이(가) 용의자와 피해자를 교체했습니다!"
            )
        else:
            await channel.send(
                f"⏭️ {discoverer.name}이(가) 교체 없이 넘어갑니다."
            )

    else:
        # ── 인간 발견자: 채널 버튼으로 시작 → 본인에게만 보이는 응답으로 진행 ──
        start_view = DiscovererStartView(game, discoverer.id, timeout=150)
        await channel.send(
            f"🔍 {discoverer.color_emoji} **{discoverer.name}**님, "
            "아래 버튼을 눌러 수사를 시작하세요! (본인만 결과를 볼 수 있습니다)",
            view=start_view,
        )

        timed_out = await start_view.wait()
        if timed_out or not start_view.done:
            await channel.send(
                f"⏰ {discoverer.name} 시간 초과! 자동으로 수사합니다."
            )
            chosen = AIStrategy.choose_suspects_to_view()
            game.set_discoverer_viewed(chosen)
            await channel.send(
                f"🔍 {discoverer.name}이(가) 용의자 2명을 확인했습니다. (자동)"
            )
        elif start_view.swapped:
            await channel.send(
                f"🔄 {discoverer.color_emoji} {discoverer.name}이(가) 용의자와 피해자를 교체했습니다!"
            )
        else:
            await channel.send(
                f"⏭️ {discoverer.color_emoji} {discoverer.name}이(가) 교체 없이 넘어갑니다."
            )

    game.state = GameState.DISCOVERING


# ================================================================
#  고발 단계
# ================================================================

async def accusation_phase(channel: discord.TextChannel, game: Game):
    """발견자부터 시계방향으로 고발을 진행한다."""
    game.start_accusation()

    embed = EmbedBuilder.accusation_phase(game)
    await channel.send(embed=embed)

    is_first_accuser = True  # 발견자(첫 고발자)는 이미 수사 단계에서 2명을 확인했음

    while not game.all_accused():
        accuser = game.current_accuser

        # 발견자 이후의 모든 고발자는, 고발 전 직전에 고발된 용의자를
        # 제외한 나머지 2명을 반드시 확인해야 한다 (원작 규칙).
        if not is_first_accuser:
            if accuser.is_ai:
                game.view_suspects_for_next_accuser()
                await asyncio.sleep(AI_DELAY)
            else:
                peek_view = SuspectPeekView(game, accuser.id, timeout=60)
                await channel.send(
                    f"🔍 {accuser.color_emoji} **{accuser.name}**님, 아래 버튼을 눌러 "
                    "남은 용의자 2명을 확인하세요! (본인만 볼 수 있습니다)",
                    view=peek_view,
                )
                timed_out = await peek_view.wait()
                if timed_out or not peek_view.done:
                    # 확인을 안 했어도 game 쪽에는 최신 정보가 없으므로
                    # AI 로직과 동일하게 정보 없이 진행한다.
                    await channel.send(
                        f"⏰ {accuser.name} 확인 시간 초과! 정보 없이 고발을 진행합니다."
                    )
                    accuser.known_suspect_indices = []

        if accuser.is_ai:
            # ── AI 고발 ──
            suspects_info = _get_ai_suspect_info(game, accuser)
            chosen_idx = AIStrategy.choose_accusation(
                player=accuser,
                suspects=suspects_info,
                known_tiles=accuser.known_tiles,
                accusation_stacks=game.accusation_stacks,
                player_count=game.player_count,
            )
            game.make_accusation(accuser.id, chosen_idx)

            embed = EmbedBuilder.ai_accusation(accuser, chosen_idx)
            await channel.send(embed=embed)

        else:
            # ── 인간 고발 ──
            embed = EmbedBuilder.accusation_turn(game)
            accuse_view = AccusationView(game, timeout=60)
            msg = await channel.send(embed=embed, view=accuse_view)

            timed_out = await accuse_view.wait()
            if timed_out or not accuse_view.done:
                # 타임아웃: 랜덤 고발
                import random
                chosen_idx = random.randint(0, 2)
                game.make_accusation(accuser.id, chosen_idx)
                await channel.send(
                    f"⏰ {accuser.color_emoji} {accuser.name} 시간 초과! "
                    f"자동으로 **용의자 {chosen_idx + 1}**을(를) 고발합니다."
                )
            else:
                chosen_idx = accuse_view.chosen_idx
                game.make_accusation(accuser.id, chosen_idx)
                await channel.send(
                    f"⚖️ {accuser.color_emoji} **{accuser.name}**이(가) "
                    f"**용의자 {chosen_idx + 1}**을(를) 고발했습니다!"
                )

        is_first_accuser = False

        # 다음 고발자
        if not game.advance_accuser():
            break

        await asyncio.sleep(0.5)

    await channel.send("✅ 모든 플레이어가 고발을 완료했습니다!")


def _get_ai_suspect_info(game: Game, ai_player) -> list:
    """AI가 알고 있는 용의자 정보를 구성한다 (확인한 용의자만 채워짐)."""
    suspects_info = [None, None, None]
    for idx in ai_player.known_suspect_indices:
        if 0 <= idx < 3:
            suspects_info[idx] = game.suspects[idx]
    return suspects_info


# ================================================================
#  봇 이벤트
# ================================================================

@bot.event
async def on_ready():
    """봇 준비 완료"""
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
