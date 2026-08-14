"""용의자/피해자 보드를 이미지로 렌더링

실물 "덤불쏭" 보드 컴포넌트(파란 배경 위에 검은 용의자 인형 3개 +
빨간 피해자 인형 1개)를 본떠서, 현재 게임 상태(고발 현황, 발견자가
확인하지 않은 용의자, 범인 공개 여부)를 이미지로 그려 보여준다.
"""

from __future__ import annotations
import io
from typing import TYPE_CHECKING, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from game.game import Game

# ── 색상 ──
BG_COLOR = (58, 158, 217)
FIGURE_COLOR = (26, 26, 30)
VICTIM_COLOR = (196, 58, 44)
WHITE = (255, 255, 255)
GOLD = (241, 196, 15)

# 플레이어 색상 (game/player.py의 PLAYER_COLORS 순서와 동일: 빨강,파랑,초록,노랑,보라)
PLAYER_COLORS_RGB = [
    (231, 76, 60),
    (52, 120, 246),
    (46, 204, 113),
    (241, 196, 15),
    (155, 89, 182),
]

_FONT_CANDIDATES = [
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "arialbd.ttf",
    "Arial Bold.ttf",
    "malgunbd.ttf",  # 윈도우 맑은 고딕 볼드 (한글 지원)
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_person(size=(160, 240)) -> Image.Image:
    """사람 모양 실루엣을 그린 투명 배경 이미지를 반환한다 (검정색,
    나중에 필요한 색으로 합성해서 사용)."""
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fill = (0, 0, 0, 255)

    # 머리
    head_r = int(w * 0.19)
    head_cx, head_cy = w // 2, int(h * 0.16)
    d.ellipse(
        [head_cx - head_r, head_cy - head_r, head_cx + head_r, head_cy + head_r],
        fill=fill,
    )

    # 팔 (몸통과 살짝 떨어져서, 이미지 속 인형처럼 틈이 보이게)
    arm_top = int(h * 0.28)
    arm_bottom = int(h * 0.62)
    arm_w = int(w * 0.16)
    d.rounded_rectangle(
        [int(w * 0.03), arm_top, int(w * 0.03) + arm_w, arm_bottom],
        radius=arm_w // 2, fill=fill,
    )
    d.rounded_rectangle(
        [w - int(w * 0.03) - arm_w, arm_top, w - int(w * 0.03), arm_bottom],
        radius=arm_w // 2, fill=fill,
    )

    # 몸통 (어깨는 넓고 허리는 좁게)
    torso_top = int(h * 0.27)
    torso_bottom = int(h * 0.58)
    d.polygon(
        [
            (int(w * 0.22), torso_top),
            (int(w * 0.78), torso_top),
            (int(w * 0.66), torso_bottom),
            (int(w * 0.34), torso_bottom),
        ],
        fill=fill,
    )
    # 몸통 모서리를 둥글게 보정
    d.ellipse(
        [int(w * 0.22) - 4, torso_top - 4, int(w * 0.22) + 24, torso_top + 24],
        fill=fill,
    )
    d.ellipse(
        [int(w * 0.78) - 24, torso_top - 4, int(w * 0.78) + 4, torso_top + 24],
        fill=fill,
    )

    # 다리 (틈을 두고 두 개)
    leg_top = int(h * 0.56)
    leg_bottom = int(h * 0.94)
    leg_w = int(w * 0.2)
    d.rounded_rectangle(
        [int(w * 0.28), leg_top, int(w * 0.28) + leg_w, leg_bottom],
        radius=leg_w // 2, fill=fill,
    )
    d.rounded_rectangle(
        [int(w * 0.72) - leg_w, leg_top, int(w * 0.72), leg_bottom],
        radius=leg_w // 2, fill=fill,
    )

    return img


def _tint(img: Image.Image, color) -> Image.Image:
    """검정 실루엣 이미지에 색을 입힌다 (알파는 유지)."""
    r, g, b, a = img.split()
    colored = Image.new("RGBA", img.size, color + (0,))
    colored.putalpha(a)
    return colored


def render_board(
    game: Game,
    show_values: bool = False,
    murderer_idx: Optional[int] = None,
) -> io.BytesIO:
    """현재 용의자/피해자/고발 현황을 이미지로 그려 반환한다.

    Args:
        game: 현재 게임 상태
        show_values: True면 각 용의자 위에 실제 타일 번호를 표시 (공개 후)
        murderer_idx: 공개 후 범인 인덱스 (있으면 강조 표시)
    """
    W, H = 900, 700
    canvas = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    person_template = _draw_person()
    suspect_sprite = _tint(person_template, FIGURE_COLOR)

    num_font = _load_font(40)

    # ── 용의자 3명 배치 ──
    suspect_w, suspect_h = 190, 260
    suspect_sprite_resized = suspect_sprite.resize((suspect_w, suspect_h))
    gap = 60
    total_w = suspect_w * 3 + gap * 2
    start_x = (W - total_w) // 2
    top_y = 90

    positions = []
    for i in range(3):
        x = start_x + i * (suspect_w + gap)
        positions.append(x)

        is_murderer = (murderer_idx == i)
        is_unseen = (not show_values and game.unseen_idx == i)

        # 범인 강조 배경 (공개 후)
        if is_murderer:
            pad = 18
            draw.rounded_rectangle(
                [x - pad, top_y - pad, x + suspect_w + pad, top_y + suspect_h + pad],
                radius=24, outline=(220, 30, 30), width=8,
            )

        canvas.paste(suspect_sprite_resized, (x, top_y), suspect_sprite_resized)

        # 번호/값 배지
        if show_values and game.suspects and i < len(game.suspects):
            tile = game.suspects[i]
            label = "❌" if tile.is_blank else str(tile.value)
        else:
            label = str(i + 1)

        badge_r = 30
        badge_cx = x + suspect_w // 2
        badge_cy = top_y - 20
        badge_color = (220, 30, 30) if is_murderer else WHITE
        text_color = WHITE if is_murderer else FIGURE_COLOR
        draw.ellipse(
            [badge_cx - badge_r, badge_cy - badge_r, badge_cx + badge_r, badge_cy + badge_r],
            fill=badge_color, outline=FIGURE_COLOR, width=3,
        )
        _draw_centered_text(draw, (badge_cx, badge_cy), label, num_font, text_color)

        # 발견자가 확인하지 않은 용의자 표시 (실물 게임처럼, 안 뒤집은 카드가 표시남)
        if is_unseen:
            mark_cx, mark_cy = x + suspect_w - 10, top_y - 10
            _draw_magnifier(draw, (mark_cx, mark_cy), 22, GOLD)

    # ── 고발 마커 (플레이어 색 원, 용의자 발밑에서 위로 쌓임 = 실제 스택과 동일) ──
    suspect_bottom = top_y + suspect_h
    chip_base_y = suspect_bottom + 50

    for i, x in enumerate(positions):
        stack = game.accusation_stacks.get(i, [])
        if not stack:
            continue
        # 칩이 많이 쌓이면 겹치지 않게 살짝 작게 그린다
        chip_r = 15 if len(stack) <= 3 else 11
        spacing = chip_r * 2 - 4
        cx = x + suspect_w // 2
        for j, pid in enumerate(stack):
            player = game.players.get(pid)
            if not player:
                continue
            color = PLAYER_COLORS_RGB[player.color_index % len(PLAYER_COLORS_RGB)]
            cy = chip_base_y - j * spacing  # 마지막(맨 위)이 위로 쌓임
            is_top = (j == len(stack) - 1)
            outline_color = GOLD if is_top else WHITE
            outline_w = 4 if is_top else 2
            draw.ellipse(
                [cx - chip_r, cy - chip_r, cx + chip_r, cy + chip_r],
                fill=color, outline=outline_color, width=outline_w,
            )

    # ── 피해자 (눕혀서, 아래쪽) ──
    victim_w = 150
    victim_sprite = _tint(person_template, VICTIM_COLOR)
    victim_sprite = victim_sprite.resize(
        (victim_w, int(victim_w * person_template.height / person_template.width))
    )
    victim_sprite = victim_sprite.rotate(-90, expand=True)
    vx = (W - victim_sprite.width) // 2
    vy = max(chip_base_y + 60, H - victim_sprite.height - 40)
    canvas.paste(victim_sprite, (vx, vy), victim_sprite)

    # 피해자 배지 ("V" = Victim, 용의자 번호 배지와 같은 스타일)
    badge_r = 26
    badge_cx, badge_cy = W // 2, vy - 20
    draw.ellipse(
        [badge_cx - badge_r, badge_cy - badge_r, badge_cx + badge_r, badge_cy + badge_r],
        fill=VICTIM_COLOR, outline=WHITE, width=3,
    )
    _draw_centered_text(draw, (badge_cx, badge_cy), "V", num_font, WHITE)

    return _to_png_bytes(canvas)


def _draw_centered_text(draw: ImageDraw.ImageDraw, center, text, font, color):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = center
    draw.text((x - tw / 2 - bbox[0], y - th / 2 - bbox[1]), text, font=font, fill=color)


def _draw_magnifier(draw: ImageDraw.ImageDraw, center, radius, color):
    """돋보기 모양 아이콘을 그린다 (발견자가 확인하지 않은 용의자 표시용)."""
    cx, cy = center
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        outline=color, width=5,
    )
    hx, hy = cx + radius * 0.7, cy + radius * 0.7
    draw.line([hx, hy, hx + radius * 0.7, hy + radius * 0.7], fill=color, width=6)


def _to_png_bytes(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
