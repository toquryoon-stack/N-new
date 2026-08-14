"""용의자/피해자 보드를 이미지로 렌더링

실물 "덤불쏭" 보드 컴포넌트(파란 배경 위에 검은 용의자 인형 3개 +
빨간 피해자 인형 1개)를 단순화해서 본떠, 현재 게임 상태(고발 현황,
발견자가 확인하지 않은 용의자, 범인 공개 여부)를 이미지로 그려
보여준다.
"""

from __future__ import annotations
import io
from typing import TYPE_CHECKING, Optional, Tuple

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
    "malgunbd.ttf",  # 윈도우 맑은 고딕 볼드 (한글 지원, 윈도우 기본 폰트)
    "malgun.ttf",
    "NanumGothicBold.ttf",
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "arialbd.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_person(size=(160, 240)) -> Image.Image:
    """단순화된 사람 실루엣을 그린 투명 배경 이미지를 반환한다 (검정색,
    나중에 필요한 색으로 합성해서 사용). 팔 없이, 머리 + 몸통 + 다리가
    끊김 없이 매끈하게 이어진다."""
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fill = (0, 0, 0, 255)

    # 머리
    head_r = int(w * 0.20)
    head_cx, head_cy = w // 2, int(h * 0.17)
    d.ellipse(
        [head_cx - head_r, head_cy - head_r, head_cx + head_r, head_cy + head_r],
        fill=fill,
    )

    # 몸통 (둥근 사각형 하나로 단순하게, 머리와 다리 쪽으로 살짝 겹쳐서 이음매 없이)
    torso_top = int(h * 0.22)
    torso_bottom = int(h * 0.62)
    d.rounded_rectangle(
        [int(w * 0.30), torso_top, int(w * 0.70), torso_bottom],
        radius=int(w * 0.20), fill=fill,
    )

    # 다리 (틈을 두고 두 개, 몸통과 겹치게 시작해서 매끈하게 연결)
    leg_top = int(h * 0.55)
    leg_bottom = int(h * 0.95)
    leg_w = int(w * 0.20)
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
    W, H = 900, 760
    canvas = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    person_template = _draw_person()
    suspect_sprite = _tint(person_template, FIGURE_COLOR)

    num_font = _load_font(40)
    tag_font = _load_font(18)

    # ── 용의자 3명 배치 ──
    suspect_w, suspect_h = 190, 230
    suspect_sprite_resized = suspect_sprite.resize((suspect_w, suspect_h))
    gap = 60
    total_w = suspect_w * 3 + gap * 2
    start_x = (W - total_w) // 2
    top_y = 80

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
            label = "X" if tile.is_blank else str(tile.value)
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

    # ── 고발 마커 (플레이어 색 이름표, 용의자 발밑에서 위로 쌓임 = 실제 스택과 동일) ──
    suspect_bottom = top_y + suspect_h
    tag_base_y = suspect_bottom + 55
    tag_h = 30
    tag_spacing = tag_h + 6
    tag_max_w = suspect_w + 30

    for i, x in enumerate(positions):
        stack = game.accusation_stacks.get(i, [])
        if not stack:
            continue
        cx = x + suspect_w // 2
        for j, pid in enumerate(stack):
            player = game.players.get(pid)
            if not player:
                continue
            color = PLAYER_COLORS_RGB[player.color_index % len(PLAYER_COLORS_RGB)]
            cy = tag_base_y - j * tag_spacing  # 마지막(맨 위)이 위로 쌓임
            is_top = (j == len(stack) - 1)
            _draw_name_tag(
                draw, (cx, cy), player.name, color, tag_font,
                max_width=tag_max_w, height=tag_h,
                outline=GOLD if is_top else None,
                outline_width=3 if is_top else 0,
            )

    # ── 피해자 (눕혀서, 아래쪽) ──
    victim_w = 150
    victim_sprite = _tint(person_template, VICTIM_COLOR)
    victim_sprite = victim_sprite.resize(
        (victim_w, int(victim_w * person_template.height / person_template.width))
    )
    victim_sprite = victim_sprite.rotate(-90, expand=True)
    vx = (W - victim_sprite.width) // 2
    vy = max(tag_base_y + 70, H - victim_sprite.height - 40)
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


def _draw_name_tag(
    draw: ImageDraw.ImageDraw,
    center: Tuple[float, float],
    text: str,
    color,
    font,
    max_width: int = 170,
    height: int = 30,
    outline=None,
    outline_width: int = 0,
):
    """플레이어 색 배경 + 흰 글씨 이름표를 그린다 (고발 마커).
    너무 긴 이름은 말줄임표로 잘라 폭을 맞춘다."""
    cx, cy = center
    pad_x = 12

    display_text = text
    while True:
        bbox = draw.textbbox((0, 0), display_text, font=font)
        tw = bbox[2] - bbox[0]
        if tw <= max_width - pad_x * 2 or len(display_text) <= 1:
            break
        display_text = display_text[:-1]
    if display_text != text:
        display_text = display_text.rstrip() + "…"
        bbox = draw.textbbox((0, 0), display_text, font=font)
        tw = bbox[2] - bbox[0]
    else:
        tw = bbox[2] - bbox[0]

    tag_w = min(max_width, max(tw + pad_x * 2, height))

    x0, y0 = cx - tag_w / 2, cy - height / 2
    x1, y1 = cx + tag_w / 2, cy + height / 2
    kwargs = {}
    if outline:
        kwargs["outline"] = outline
        kwargs["width"] = outline_width
    draw.rounded_rectangle([x0, y0, x1, y1], radius=height / 2, fill=color, **kwargs)
    _draw_centered_text(draw, (cx, cy), display_text, font, WHITE)


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
