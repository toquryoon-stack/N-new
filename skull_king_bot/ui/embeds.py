"""Discord Embed 빌더 - 게임 상태를 시각적으로 표시"""

from __future__ import annotations
from typing import List, Dict, Optional, Tuple, TYPE_CHECKING
import discord

if TYPE_CHECKING:
    from game.game import Game
    from game.player import Player
    from game.cards import Card
    from game.trick import PlayedCard, TrickResult
    from game.enums import GameMode

# 색상 정의
COLOR_LOBBY = 0x3498DB      # 파란색
COLOR_BIDDING = 0xF39C12    # 주황색
COLOR_PLAYING = 0x2ECC71    # 초록색
COLOR_ROUND_END = 0x9B59B6  # 보라색
COLOR_GAME_OVER = 0xE74C3C  # 빨간색
COLOR_HAND = 0x1ABC9C       # 청록색


class EmbedBuilder:
    """게임 Embed 생성기"""

    # ════════════════════════════════════════════
    #  로비
    # ════════════════════════════════════════════

    @staticmethod
    def lobby(game: Game) -> discord.Embed:
        """게임 로비 Embed"""
        mode_emoji = "📜" if game.mode.value == "basic" else "⚔️"
        ai_info = f" (🤖 AI: {game.ai_count}명)" if game.ai_count > 0 else ""
        embed = discord.Embed(
            title="🏴‍☠️ 스컬킹 - 대기실",
            description=(
                f"{mode_emoji} **모드:** {game.mode.display_name}\n"
                f"👑 **호스트:** {game.host.display_name}\n"
                f"👥 **인원:** {game.player_count}/6{ai_info}\n\n"
                "**참가** 버튼으로 참여, **🤖 AI 추가**로 AI 상대를 추가하세요!"
            ),
            color=COLOR_LOBBY,
        )

        # 참가자 목록
        if game.player_list:
            player_names = []
            for p in game.player_list:
                if p.id == game.host.id:
                    prefix = "👑 "
                elif p.is_ai:
                    prefix = "🤖 "
                else:
                    prefix = "🏴‍☠️ "
                player_names.append(f"{prefix}{p.name}")
            embed.add_field(name="참가자", value="\n".join(player_names), inline=False)

        embed.set_footer(text="최소 2명, 최대 6명 | 🤖 AI와 혼자서도 플레이 가능!")
        return embed

    # ════════════════════════════════════════════
    #  손패 (DM)
    # ════════════════════════════════════════════

    @staticmethod
    def hand(player: Player, round_number: int) -> discord.Embed:
        """플레이어 손패 Embed (DM으로 전송)"""
        embed = discord.Embed(
            title=f"🃏 라운드 {round_number} - 당신의 손패",
            color=COLOR_HAND,
        )

        cards_display = "\n".join(
            f"`{i+1}.` {card.short_display}"
            for i, card in enumerate(player.hand)
        )
        embed.description = cards_display if cards_display else "카드가 없습니다."
        embed.set_footer(text="카드 정보는 나만 볼 수 있습니다!")
        return embed

    # ════════════════════════════════════════════
    #  비딩
    # ════════════════════════════════════════════

    @staticmethod
    def bidding_prompt(player: Player, round_number: int) -> discord.Embed:
        """비딩 안내 Embed (DM)"""
        cards_display = " | ".join(card.short_display for card in player.hand)
        embed = discord.Embed(
            title=f"📢 라운드 {round_number} - 비딩",
            description=(
                f"**당신의 카드:** {cards_display}\n\n"
                f"이번 라운드에서 몇 트릭을 가져갈 수 있나요?\n"
                f"0 ~ {round_number} 중 선택하세요."
            ),
            color=COLOR_BIDDING,
        )
        return embed

    @staticmethod
    def bidding_progress(game: Game) -> discord.Embed:
        """비딩 진행 상황 (채널)"""
        embed = discord.Embed(
            title=f"📢 라운드 {game.current_round} - 비딩 진행 중",
            color=COLOR_BIDDING,
        )

        status_lines = []
        done_count = 0
        for p in game.player_list:
            if p.bid is not None:
                status_lines.append(f"✅ {p.name}")
                done_count += 1
            else:
                status_lines.append(f"⏳ {p.name}")

        embed.description = "\n".join(status_lines)
        embed.set_footer(text=f"비딩 완료: {done_count}/{game.player_count}")
        return embed

    @staticmethod
    def bidding_result(game: Game) -> discord.Embed:
        """비딩 결과 공개 (채널)"""
        embed = discord.Embed(
            title=f"📋 라운드 {game.current_round} - 비딩 결과",
            color=COLOR_BIDDING,
        )

        lines = []
        for p in game.player_list:
            bid = p.bid if p.bid is not None else 0
            lines.append(f"🏴‍☠️ **{p.name}** → **{bid}** 트릭")

        embed.description = "\n".join(lines)
        embed.set_footer(text="트릭 시작!")
        return embed

    # ════════════════════════════════════════════
    #  트릭 진행
    # ════════════════════════════════════════════

    @staticmethod
    def trick_status(
        game: Game,
        played_so_far: List[PlayedCard],
    ) -> discord.Embed:
        """트릭 진행 상태 (채널)"""
        embed = discord.Embed(
            title=f"🎴 라운드 {game.current_round} | 트릭 {game.current_trick}",
            color=COLOR_PLAYING,
        )

        # 이미 낸 카드
        if played_so_far:
            played_lines = "\n".join(
                f"  {pc.player_name} → {pc.card.short_display}"
                for pc in played_so_far
            )
            embed.add_field(name="낸 카드", value=played_lines, inline=False)

        # 현재 차례
        current = game.current_turn_player
        embed.add_field(
            name="현재 차례",
            value=f"⏳ **{current.name}**님이 카드를 선택 중...",
            inline=False,
        )

        # 비딩 정보
        bid_lines = " | ".join(
            f"{p.name}: {p.bid}({p.tricks_won})"
            for p in game.player_list
        )
        embed.set_footer(text=f"비딩(획득): {bid_lines}")
        return embed

    @staticmethod
    def card_select_prompt(
        player: Player,
        valid_indices: List[int],
        round_number: int,
        trick_number: int,
    ) -> discord.Embed:
        """카드 선택 안내 (DM)"""
        embed = discord.Embed(
            title=f"🎴 라운드 {round_number} | 트릭 {trick_number} - 카드 선택",
            color=COLOR_PLAYING,
        )

        cards_display = []
        for i, card in enumerate(player.hand):
            marker = "✅" if i in valid_indices else "❌"
            cards_display.append(f"{marker} `{i+1}.` {card.short_display}")

        embed.description = "\n".join(cards_display)
        embed.set_footer(text="✅ 표시된 카드만 낼 수 있습니다")
        return embed

    @staticmethod
    def trick_result(result: TrickResult, played_cards: List[PlayedCard]) -> discord.Embed:
        """트릭 결과 (채널)"""
        embed = discord.Embed(
            title="🏆 트릭 결과",
            color=COLOR_PLAYING,
        )

        # 모든 카드 표시
        cards_lines = "\n".join(
            f"  {pc.player_name} → {pc.card.short_display}"
            for pc in played_cards
        )
        embed.add_field(name="낸 카드", value=cards_lines, inline=False)

        # 결과
        if result.no_winner:
            embed.add_field(name="결과", value=result.description, inline=False)
        else:
            embed.add_field(
                name="승자",
                value=f"🏆 **{result.winner_name}** - {result.description}",
                inline=False,
            )

        # 특수 효과
        effects = []
        if result.shrimp_activated:
            effects.append("🦐 새우 효과 발동!")
        if result.sk_captured_by_mermaid:
            effects.append("🧜‍♀️ 인어가 스컬킹 포획! (+50점)")
        if result.pirates_captured_count > 0:
            effects.append(
                f"💀 스컬킹이 해적 {result.pirates_captured_count}명 포획! "
                f"(+{result.pirates_captured_count * 30}점)"
            )
        if result.loot_alliances:
            effects.append(f"💰 약탈품 동맹 {len(result.loot_alliances)}건 성립!")
        if result.pirate_ability:
            from game.cards import PIRATE_NAME_KR, PIRATE_ABILITY_DESC
            _, pirate = result.pirate_ability
            effects.append(
                f"☠️ {PIRATE_NAME_KR[pirate]} 능력 발동! "
                f"{PIRATE_ABILITY_DESC[pirate]}"
            )

        if effects:
            embed.add_field(name="특수 효과", value="\n".join(effects), inline=False)

        return embed

    # ════════════════════════════════════════════
    #  라운드 종료
    # ════════════════════════════════════════════

    @staticmethod
    def round_scores(
        game: Game,
        scores: Dict[int, Dict[str, int]],
    ) -> discord.Embed:
        """라운드 점수표 (채널)"""
        embed = discord.Embed(
            title=f"📊 라운드 {game.current_round} 결과",
            color=COLOR_ROUND_END,
        )

        lines = []
        for p in game.player_list:
            s = scores.get(p.id, {})
            bid = p.bid if p.bid is not None else 0
            hit = "✅" if bid == p.tricks_won else "❌"

            detail = f"{hit} **{p.name}** | 비딩: {bid} | 획득: {p.tricks_won}"
            detail += f"\n   기본: {s.get('base', 0):+d}"

            # 보너스 표시
            bonuses = []
            if s.get("sk_bonus", 0):
                bonuses.append(f"SK보너스: +{s['sk_bonus']}")
            if s.get("mermaid_bonus", 0):
                bonuses.append(f"인어보너스: +{s['mermaid_bonus']}")
            if s.get("loot_bonus", 0):
                bonuses.append(f"동맹보너스: +{s['loot_bonus']}")
            if s.get("rascal_bonus", 0):
                bonuses.append(f"라스칼: {s['rascal_bonus']:+d}")
            if bonuses:
                detail += " | " + ", ".join(bonuses)

            detail += f"\n   **라운드 합계: {s.get('total', 0):+d}** | 총점: **{p.total_score}**"
            lines.append(detail)

        embed.description = "\n\n".join(lines)

        if not game.is_game_over():
            embed.set_footer(text=f"다음: 라운드 {game.current_round + 1}")
        else:
            embed.set_footer(text="게임 종료!")

        return embed

    # ════════════════════════════════════════════
    #  게임 종료
    # ════════════════════════════════════════════

    @staticmethod
    def final_result(rankings: List[Tuple[Player, int]]) -> discord.Embed:
        """최종 결과 (채널)"""
        embed = discord.Embed(
            title="🏆 스컬킹 - 최종 결과!",
            color=COLOR_GAME_OVER,
        )

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for player, rank in rankings:
            medal = medals.get(rank, f"#{rank}")
            lines.append(f"{medal} **{player.name}** — **{player.total_score}점**")

        embed.description = "\n\n".join(lines)

        # 우승자 강조
        if rankings:
            winner = rankings[0][0]
            embed.set_footer(text=f"축하합니다, {winner.name}님! 바다의 왕!")

        return embed

    # ════════════════════════════════════════════
    #  해적 능력 관련
    # ════════════════════════════════════════════

    @staticmethod
    def juanita_cards(remaining_cards: List[Card]) -> discord.Embed:
        """후아니타 능력: 미사용 카드 목록 (DM)"""
        embed = discord.Embed(
            title="🔍 후아니타 제이드 - 미사용 카드 확인",
            color=COLOR_HAND,
        )

        if remaining_cards:
            cards_display = " | ".join(c.short_display for c in remaining_cards)
            embed.description = f"이번 라운드에 나오지 않은 카드:\n{cards_display}"
        else:
            embed.description = "남은 카드가 없습니다."

        embed.set_footer(text="이 정보는 나만 볼 수 있습니다!")
        return embed

    @staticmethod
    def tigress_choice_prompt() -> discord.Embed:
        """타이그리스 선택 안내 (DM)"""
        embed = discord.Embed(
            title="🐯 타이그리스 - 선택",
            description="타이그리스를 어떻게 사용하시겠습니까?",
            color=COLOR_PLAYING,
        )
        return embed

    @staticmethod
    def mode_select() -> discord.Embed:
        """모드 선택 Embed"""
        embed = discord.Embed(
            title="🏴‍☠️ 스컬킹 - 게임 생성",
            description=(
                "게임 모드를 선택하세요!\n\n"
                "📜 **기본판** - 숫자 카드 + 탈출 + 해적 + 스컬킹 + 🦐새우 (68장)\n"
                "⚔️ **확장판** - 기본판 + 인어, 타이그리스, 약탈품, 크라켄, 백경, 해적 능력 (75장)"
            ),
            color=COLOR_LOBBY,
        )
        return embed
