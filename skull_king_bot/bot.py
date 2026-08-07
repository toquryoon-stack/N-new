"""스컬킹 디스코드 봇 - 메인 엔트리포인트

슬래시 커맨드로 게임을 생성하고, 디스코드 채널 + DM으로 게임을 진행한다.
"""

from __future__ import annotations
import asyncio
import logging
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config as cfg
from game.enums import GameMode, GameState, CardType, PirateName, TigressChoice
from game.game import Game, GameManager
from game.ai import AIStrategy
from game.trick import PlayedCard
from ui.embeds import EmbedBuilder
from ui.views import (
    ModeSelectView,
    LobbyView,
    BiddingView,
    CardSelectView,
    TigressChoiceView,
    RosieSelectView,
    BahijDiscardView,
    HarryBidView,
    RascalWagerView,
    GameOverView,
    NextRoundView,
)

# ── 로깅 설정 ──
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("skull_king")

# ── 봇 설정 ──
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
game_manager = GameManager()


# ================================================================
#  슬래시 커맨드: /스컬킹
# ================================================================

@bot.tree.command(name="스컬킹", description="스컬킹 카드 게임을 시작합니다!")
async def skull_king_command(interaction: discord.Interaction):
    """게임 생성 커맨드"""
    channel_id = interaction.channel_id

    # 이미 진행 중인 게임 확인
    existing = game_manager.get_game(channel_id)
    if existing and existing.state != GameState.GAME_OVER:
        await interaction.response.send_message(
            "❌ 이 채널에서 이미 게임이 진행 중입니다!", ephemeral=True
        )
        return

    # 모드 선택
    mode_embed = EmbedBuilder.mode_select()
    mode_view = ModeSelectView()
    await interaction.response.send_message(embed=mode_embed, view=mode_view)

    timed_out = await mode_view.wait()
    if timed_out or mode_view.selected_mode is None:
        await interaction.edit_original_response(
            content="⏰ 시간 초과! 게임 생성이 취소되었습니다.",
            embed=None, view=None,
        )
        return

    mode = mode_view.selected_mode

    # 게임 생성
    game = game_manager.create_game(channel_id, interaction.user, mode)
    game.add_player(interaction.user)  # 호스트 자동 참가

    # 로비 표시
    await _show_lobby(interaction, game)


# ================================================================
#  로비 관리
# ================================================================

async def _show_lobby(interaction: discord.Interaction, game: Game):
    """로비 Embed + 버튼 표시"""
    embed = EmbedBuilder.lobby(game)

    async def on_join(inter: discord.Interaction):
        if game.add_player(inter.user):
            embed = EmbedBuilder.lobby(game)
            await inter.response.edit_message(embed=embed)
        else:
            if inter.user.id in game.players:
                await inter.response.send_message("이미 참가하고 있습니다!", ephemeral=True)
            else:
                await inter.response.send_message("❌ 참가할 수 없습니다. (정원 초과 또는 게임 진행 중)", ephemeral=True)

    async def on_leave(inter: discord.Interaction):
        if inter.user.id == game.host.id:
            await inter.response.send_message("호스트는 퇴장할 수 없습니다!", ephemeral=True)
            return
        if game.remove_player(inter.user.id):
            embed = EmbedBuilder.lobby(game)
            await inter.response.edit_message(embed=embed)
        else:
            await inter.response.send_message("참가하지 않은 상태입니다!", ephemeral=True)

    async def on_add_ai(inter: discord.Interaction):
        if inter.user.id != game.host.id:
            await inter.response.send_message("호스트만 AI를 추가할 수 있습니다!", ephemeral=True)
            return
        ai_player = game.add_ai_player()
        if ai_player:
            embed = EmbedBuilder.lobby(game)
            await inter.response.edit_message(embed=embed)
        else:
            await inter.response.send_message("❌ AI를 추가할 수 없습니다. (정원 초과)", ephemeral=True)

    async def on_remove_ai(inter: discord.Interaction):
        if inter.user.id != game.host.id:
            await inter.response.send_message("호스트만 AI를 제거할 수 있습니다!", ephemeral=True)
            return
        if game.remove_ai_player():
            embed = EmbedBuilder.lobby(game)
            await inter.response.edit_message(embed=embed)
        else:
            await inter.response.send_message("❌ 제거할 AI가 없습니다!", ephemeral=True)

    async def on_start(inter: discord.Interaction):
        if inter.user.id != game.host.id:
            await inter.response.send_message("호스트만 게임을 시작할 수 있습니다!", ephemeral=True)
            return
        if not game.can_start():
            await inter.response.send_message(
                f"❌ 최소 {cfg.MIN_PLAYERS}명이 필요합니다! (현재 {game.player_count}명)\n"
                f"💡 **AI 추가** 버튼으로 AI 상대를 추가해 보세요!",
                ephemeral=True,
            )
            return

        # 게임 시작!
        await inter.response.edit_message(
            content="🏴‍☠️ **게임이 시작됩니다!**",
            embed=None, view=None,
        )
        await _start_game(inter.channel, game)

    lobby_view = LobbyView(game, on_join, on_leave, on_start, on_add_ai, on_remove_ai)
    await interaction.edit_original_response(embed=embed, view=lobby_view)


# ================================================================
#  게임 시작 & 라운드 루프
# ================================================================

async def _start_game(channel: discord.abc.Messageable, game: Game):
    """게임을 시작하고 라운드를 순차 진행한다."""
    for round_num in range(1, cfg.TOTAL_ROUNDS + 1):
        await _run_round(channel, game)

        if game.is_game_over():
            break

        # 다음 라운드 진행 확인 (호스트만)
        if round_num < cfg.TOTAL_ROUNDS:
            next_view = NextRoundView()
            next_msg = await channel.send(
                f"▶️ **다음 라운드로 진행하려면 버튼을 누르세요!**",
                view=next_view,
            )
            await next_view.wait()
            try:
                await next_msg.delete()
            except discord.NotFound:
                pass

    # 게임 종료
    await _end_game(channel, game)


async def _run_round(channel: discord.abc.Messageable, game: Game):
    """하나의 라운드를 진행한다."""
    round_num = game.start_new_round()
    log.info(f"라운드 {round_num} 시작 (채널: {game.channel_id})")

    await channel.send(f"🎯 **라운드 {round_num} 시작!** (카드 {round_num}장)")

    # ── DM으로 손패 전달 (AI 제외) ──
    for player in game.player_list:
        if player.is_ai:
            continue
        try:
            hand_embed = EmbedBuilder.hand(player, round_num)
            await player.user.send(embed=hand_embed)
        except discord.Forbidden:
            await channel.send(
                f"⚠️ {player.mention}님에게 DM을 보낼 수 없습니다! "
                f"DM 설정을 확인해 주세요."
            )

    # ── 비딩 단계 ──
    await _bidding_phase(channel, game)

    # ── 트릭 진행 ──
    for trick_num in range(1, round_num + 1):
        await _play_trick(channel, game)

    # ── 라운드 종료 & 점수 ──
    scores = game.end_round()
    score_embed = EmbedBuilder.round_scores(game, scores)
    await channel.send(embed=score_embed)


# ================================================================
#  비딩 단계
# ================================================================

async def _bidding_phase(channel: discord.abc.Messageable, game: Game):
    """모든 플레이어의 비딩을 동시에 받는다."""
    progress_msg = await channel.send(embed=EmbedBuilder.bidding_progress(game))

    # 각 플레이어에게 DM으로 비딩 요청 (동시 진행)
    tasks = [
        _request_bid(channel, game, player, progress_msg)
        for player in game.player_list
    ]
    await asyncio.gather(*tasks)

    # 비딩 결과 공개
    await progress_msg.edit(embed=EmbedBuilder.bidding_result(game))


async def _request_bid(
    channel: discord.abc.Messageable,
    game: Game,
    player,
    progress_msg: discord.Message,
):
    """한 플레이어에게 비딩을 요청한다 (DM 또는 AI 자동)."""

    # ── AI 자동 비딩 ──
    if player.is_ai:
        await asyncio.sleep(random.uniform(0.5, 1.5))  # 자연스러운 딜레이
        bid = AIStrategy.calculate_bid(player.hand, game.current_round, game.mode)
        game.set_bid(player.id, bid)
        try:
            await progress_msg.edit(embed=EmbedBuilder.bidding_progress(game))
        except discord.NotFound:
            pass
        return

    # ── 사람 플레이어 DM 비딩 ──
    try:
        bid_embed = EmbedBuilder.bidding_prompt(player, game.current_round)
        bid_view = BiddingView(max_bid=game.current_round)
        await player.user.send(embed=bid_embed, view=bid_view)

        timed_out = await bid_view.wait()

        if timed_out or bid_view.selected_bid is None:
            # 타임아웃 → 0으로 자동 비딩
            game.set_bid(player.id, 0)
            try:
                await player.user.send("⏰ 시간 초과! 자동으로 **0**으로 비딩되었습니다.")
            except discord.Forbidden:
                pass
        else:
            game.set_bid(player.id, bid_view.selected_bid)

        # 진행 상황 업데이트
        try:
            await progress_msg.edit(embed=EmbedBuilder.bidding_progress(game))
        except discord.NotFound:
            pass

    except discord.Forbidden:
        game.set_bid(player.id, 0)
        await channel.send(
            f"⚠️ {player.mention}님에게 DM을 보낼 수 없어 0으로 자동 비딩되었습니다."
        )


# ================================================================
#  트릭 진행
# ================================================================

async def _play_trick(channel: discord.abc.Messageable, game: Game):
    """하나의 트릭을 진행한다."""
    trick_num = game.start_trick()

    # 트릭 상태 메시지
    status_msg = await channel.send(
        embed=EmbedBuilder.trick_status(game, game.trick_cards)
    )

    # 각 플레이어 순서대로 카드 선택
    while not game.is_trick_complete():
        player = game.current_turn_player

        # DM으로 카드 선택 요청
        played_card = await _request_card(channel, game, player)

        # 타이그리스 처리 (확장판)
        if played_card and played_card.card.card_type == CardType.TIGRESS:
            await _handle_tigress(player, played_card)

        # 채널 상태 업데이트
        try:
            await status_msg.edit(
                embed=EmbedBuilder.trick_status(game, game.trick_cards)
            )
        except discord.NotFound:
            pass

        # 다음 턴
        if not game.advance_turn():
            break

    # 트릭 판정
    result = game.resolve_trick()

    # 결과 표시
    result_embed = EmbedBuilder.trick_result(result, game.trick_cards)
    await channel.send(embed=result_embed)

    # 해적 능력 처리 (확장판)
    if result.pirate_ability and game.mode == GameMode.LEGENDARY:
        await _handle_pirate_ability(channel, game, result)

    # 잠시 대기 (가독성)
    await asyncio.sleep(2)


async def _request_card(
    channel: discord.abc.Messageable,
    game: Game,
    player,
) -> Optional[PlayedCard]:
    """한 플레이어에게 카드 선택을 요청한다 (DM 또는 AI 자동)."""
    valid_indices = game.get_valid_cards(player.id)

    # ── AI 자동 카드 선택 ──
    if player.is_ai:
        await asyncio.sleep(random.uniform(0.8, 2.0))  # 자연스러운 딜레이
        card_index = AIStrategy.choose_card(
            player=player,
            valid_indices=valid_indices,
            round_number=game.current_round,
            current_trick=game.current_trick,
            trick_cards=game.trick_cards,
            lead_suit=game.lead_suit,
            mode=game.mode,
        )
        played = game.play_card(player.id, card_index)
        return played

    # ── 사람 플레이어 DM 카드 선택 ──
    try:
        card_embed = EmbedBuilder.card_select_prompt(
            player, valid_indices, game.current_round, game.current_trick
        )
        card_view = CardSelectView(player.hand, valid_indices)
        await player.user.send(embed=card_embed, view=card_view)

        timed_out = await card_view.wait()

        if timed_out or card_view.selected_index is None:
            # 타임아웃 → 첫 번째 유효 카드 자동 선택
            auto_index = valid_indices[0] if valid_indices else 0
            played = game.play_card(player.id, auto_index)
            try:
                await player.user.send(
                    f"⏰ 시간 초과! 자동으로 {played.card.short_display}을(를) 냈습니다."
                )
            except discord.Forbidden:
                pass
            return played
        else:
            played = game.play_card(player.id, card_view.selected_index)
            return played

    except discord.Forbidden:
        # DM 불가 → 자동 선택
        auto_index = valid_indices[0] if valid_indices else 0
        played = game.play_card(player.id, auto_index)
        await channel.send(
            f"⚠️ {player.mention}님에게 DM을 보낼 수 없어 자동으로 카드를 냈습니다."
        )
        return played


async def _handle_tigress(player, played_card: PlayedCard):
    """타이그리스 카드 선택 처리"""
    # ── AI 자동 선택 ──
    if player.is_ai:
        bid = player.bid if player.bid is not None else 0
        tricks_needed = bid - player.tricks_won
        choice = AIStrategy.choose_tigress(player, tricks_needed)
        played_card.card.tigress_choice = choice
        return

    # ── 사람 플레이어 ──
    try:
        tigress_embed = EmbedBuilder.tigress_choice_prompt()
        tigress_view = TigressChoiceView()
        await player.user.send(embed=tigress_embed, view=tigress_view)

        timed_out = await tigress_view.wait()
        if timed_out or tigress_view.choice is None:
            played_card.card.tigress_choice = TigressChoice.ESCAPE
            await player.user.send("⏰ 시간 초과! 자동으로 **탈출**로 사용됩니다.")
        else:
            played_card.card.tigress_choice = tigress_view.choice
    except discord.Forbidden:
        played_card.card.tigress_choice = TigressChoice.ESCAPE


# ================================================================
#  해적 능력 처리
# ================================================================

async def _handle_pirate_ability(
    channel: discord.abc.Messageable,
    game: Game,
    result,
):
    """확장판 해적 능력을 처리한다."""
    winner_id, pirate_name = result.pirate_ability
    winner = game.players.get(winner_id)
    if not winner:
        return

    try:
        if pirate_name == PirateName.ROSIE:
            await _handle_rosie(channel, game, winner)
        elif pirate_name == PirateName.BAHIJ:
            await _handle_bahij(channel, game, winner)
        elif pirate_name == PirateName.JUANITA:
            await _handle_juanita(game, winner)
        elif pirate_name == PirateName.HARRY:
            await _handle_harry(channel, game, winner)
        elif pirate_name == PirateName.RASCAL:
            await _handle_rascal(channel, game, winner)
    except Exception as e:
        log.error(f"해적 능력 처리 오류: {e}")
        await channel.send(f"⚠️ 해적 능력 처리 중 오류가 발생했습니다.")


async def _handle_rosie(channel, game: Game, winner):
    """로지: 다음 리드 플레이어 지목"""
    # ── AI ──
    if winner.is_ai:
        target_id = AIStrategy.choose_rosie_target(game.player_order, winner.id)
        game.set_rosie_lead(target_id)
        target = game.players.get(target_id)
        target_name = target.name if target else "?"
        await channel.send(f"☠️ 로지 능력: 🤖 {winner.name}이(가) **{target_name}**님을 리드로 지목!")
        return

    # ── 사람 ──
    view = RosieSelectView(game.player_list)
    try:
        await winner.user.send(
            "☠️ **로지 들레이니** 능력! 다음 트릭의 리드 플레이어를 선택하세요:",
            view=view,
        )
        await view.wait()
        if view.result is not None:
            game.set_rosie_lead(view.result)
            target = game.players.get(view.result)
            target_name = target.name if target else "?"
            await channel.send(f"☠️ 로지 능력: **{target_name}**님이 다음 트릭을 리드합니다!")
    except discord.Forbidden:
        pass


async def _handle_bahij(channel, game: Game, winner):
    """바히즈: 2장 드로우 + 2장 버리기"""
    drawn = game.bahij_draw(winner.id)
    if not drawn:
        return

    # ── AI ──
    if winner.is_ai:
        discard_indices = AIStrategy.choose_bahij_discards(len(winner.hand))
        game.bahij_discard(winner.id, discard_indices)
        await channel.send(f"☠️ 바히즈 능력: 🤖 {winner.name}이(가) 카드를 교체했습니다!")
        return

    # ── 사람 ──
    drawn_display = ", ".join(c.short_display for c in drawn)
    try:
        await winner.user.send(f"☠️ **바히즈** 능력! 드로우한 카드: {drawn_display}")

        # 버릴 카드 선택
        discard_view = BahijDiscardView(winner.hand)
        await winner.user.send("버릴 카드 2장을 선택하세요:", view=discard_view)

        timed_out = await discard_view.wait()
        if timed_out or discard_view.result is None:
            indices = [len(winner.hand) - 1, len(winner.hand) - 2]
            game.bahij_discard(winner.id, indices)
            await winner.user.send("⏰ 시간 초과! 자동으로 카드를 버렸습니다.")
        else:
            game.bahij_discard(winner.id, discard_view.result)

        await channel.send(f"☠️ 바히즈 능력: **{winner.name}**님이 카드를 교체했습니다!")
    except discord.Forbidden:
        indices = [len(winner.hand) - 1, len(winner.hand) - 2]
        game.bahij_discard(winner.id, indices)


async def _handle_juanita(game: Game, winner):
    """후아니타: 미사용 카드 확인"""
    # AI는 내부적으로 확인만 함 (표시 불필요)
    if winner.is_ai:
        return

    remaining = game.get_remaining_cards_info()
    embed = EmbedBuilder.juanita_cards(remaining)
    try:
        await winner.user.send(embed=embed)
    except discord.Forbidden:
        pass


async def _handle_harry(channel, game: Game, winner):
    """해리: 비딩 ±1 변경"""
    current_bid = winner.bid if winner.bid is not None else 0

    # ── AI ──
    if winner.is_ai:
        delta = AIStrategy.choose_harry_delta(current_bid, winner.tricks_won, game.current_round)
        if delta != 0:
            game.modify_bid(winner.id, delta)
            await channel.send(f"☠️ 해리 능력: 🤖 {winner.name}이(가) 비딩을 변경했습니다!")
        return

    # ── 사람 ──
    view = HarryBidView(current_bid, game.current_round)
    try:
        await winner.user.send(
            f"☠️ **해리** 능력! 현재 비딩: **{current_bid}** | 변경하시겠습니까?",
            view=view,
        )
        await view.wait()
        if view.result is not None and view.result != 0:
            game.modify_bid(winner.id, view.result)
            new_bid = current_bid + view.result
            await channel.send(f"☠️ 해리 능력: **{winner.name}**님이 비딩을 변경했습니다!")
    except discord.Forbidden:
        pass


async def _handle_rascal(channel, game: Game, winner):
    """라스칼: 추가 베팅"""
    # ── AI ──
    if winner.is_ai:
        wager = AIStrategy.choose_rascal_wager(
            winner.bid if winner.bid is not None else 0,
            winner.tricks_won,
        )
        game.set_rascal_wager(winner.id, wager)
        await channel.send(f"☠️ 라스칼 능력: 🤖 {winner.name}이(가) **{wager}점** 추가 베팅!")
        return

    # ── 사람 ──
    view = RascalWagerView()
    try:
        await winner.user.send(
            "☠️ **라스칼** 능력! 추가 베팅을 선택하세요:",
            view=view,
        )
        await view.wait()
        if view.result is not None:
            game.set_rascal_wager(winner.id, view.result)
            await channel.send(
                f"☠️ 라스칼 능력: **{winner.name}**님이 **{view.result}점** 추가 베팅!"
            )
    except discord.Forbidden:
        pass


# ================================================================
#  게임 종료
# ================================================================

async def _end_game(channel: discord.abc.Messageable, game: Game):
    """게임을 종료하고 최종 결과를 표시한다."""
    rankings = game.end_game()
    result_embed = EmbedBuilder.final_result(rankings)

    game_over_view = GameOverView()
    await channel.send(embed=result_embed, view=game_over_view)

    await game_over_view.wait()

    if game_over_view.action == "restart":
        # 같은 설정으로 새 게임
        new_game = game_manager.create_game(game.channel_id, game.host, game.mode)
        for player in game.player_list:
            new_game.add_player(player.user)
        await channel.send("🔄 **같은 멤버로 새 게임을 시작합니다!**")
        await _start_game(channel, new_game)
    else:
        game_manager.remove_game(game.channel_id)
        await channel.send("👋 게임이 종료되었습니다. 수고하셨습니다!")


# ================================================================
#  봇 이벤트
# ================================================================

@bot.event
async def on_ready():
    """봇 준비 완료"""
    log.info(f"✅ {bot.user.name} 로그인 완료!")
    try:
        synced = await bot.tree.sync()
        log.info(f"📋 슬래시 커맨드 {len(synced)}개 동기화 완료")
    except Exception as e:
        log.error(f"슬래시 커맨드 동기화 실패: {e}")


# ================================================================
#  실행
# ================================================================

def main():
    if not cfg.DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN이 설정되지 않았습니다!")
        print("   .env 파일에 DISCORD_TOKEN=your_token_here 를 추가하세요.")
        return

    bot.run(cfg.DISCORD_TOKEN)


if __name__ == "__main__":
    main()
