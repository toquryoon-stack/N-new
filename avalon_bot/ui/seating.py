"""원정대 자리 배치를 원탁 이미지로 그려주는 모듈 - 아발롬

오프라인으로 아발롬을 할 때는 원으로 둘러앉아 시계 방향으로 리더가
넘어가기 때문에, 디스코드에서도 같은 느낌이 나도록 플레이어를
원형으로 배치한 이미지를 생성한다.
"""

from __future__ import annotations
import io
import math
import os
import re
from typing import List, Optional, TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from game.player import Player

# 폰트에 없는 이모지(예: AI 유저 이름 앞의 🤖)를 그리면 빈 사각형(tofu)이
# 나올 수 있으므로, 그림에 쓰기 전에 미리 제거한다.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "️"
    "]+",
    flags=re.UNICODE,
)


def _clean_text(text: str) -> str:
    cleaned = _EMOJI_PATTERN.sub("", text).strip()
    return cleaned or text


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"

_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")
_FONT_REGULAR_PATH = os.path.join(_FONT_DIR, "NanumGothic-Regular.ttf")
_FONT_BOLD_PATH = os.path.join(_FONT_DIR, "NanumGothic-Bold.ttf")

# ── 색상 ──
_BG = (49, 51, 56, 255)             # 디스코드 다크 배경과 어울리는 색
_TABLE_FILL = (33, 92, 66, 255)     # 원탁(초록 펠트)
_TABLE_EDGE = (20, 60, 43, 255)
_SEAT_DEFAULT = (79, 84, 92, 255)   # 기본 좌석
_SEAT_LEADER = (241, 196, 15, 255)  # 리더 좌석 (금색)
_SEAT_TEAM = (52, 152, 219, 255)    # 원정대에 뽑힌 좌석 (파랑)
_SEAT_AI = (149, 165, 166, 255)     # AI 표시 테두리
_TEXT_LIGHT = (255, 255, 255, 255)
_TEXT_DARK = (30, 30, 30, 255)
_ARROW_COLOR = (236, 240, 241, 230)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = _FONT_BOLD_PATH if bold else _FONT_REGULAR_PATH
    return ImageFont.truetype(path, size)


def _seat_positions(n: int, cx: int, cy: int, radius: float):
    """좌석 좌표를 12시 방향부터 시계 방향으로 계산한다."""
    positions = []
    start_angle = -math.pi / 2  # 12시 방향
    for i in range(n):
        angle = start_angle + (2 * math.pi * i / n)
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        positions.append((x, y, angle))
    return positions


def _draw_clockwise_arrow(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: float):
    """원탁 안쪽에 '시계 방향' 화살표(호)를 그린다."""
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    start_deg, end_deg = -95, 15
    draw.arc(bbox, start=start_deg, end=end_deg, fill=_ARROW_COLOR, width=6)

    end_angle = math.radians(end_deg)
    tip_x = cx + radius * math.cos(end_angle)
    tip_y = cy + radius * math.sin(end_angle)

    tangent = end_angle + math.pi / 2
    head_len = 16
    left = (
        tip_x - head_len * math.cos(tangent - math.radians(150)),
        tip_y - head_len * math.sin(tangent - math.radians(150)),
    )
    right = (
        tip_x - head_len * math.cos(tangent + math.radians(150)),
        tip_y - head_len * math.sin(tangent + math.radians(150)),
    )
    draw.polygon([(tip_x, tip_y), left, right], fill=_ARROW_COLOR)


def render_seating_circle(
    players: List["Player"],
    leader_id: Optional[int] = None,
    team_ids: Optional[List[int]] = None,
    center_label: str = "아발롬",
) -> io.BytesIO:
    """플레이어를 원탁에 둘러앉힌 좌석 배치 이미지를 생성한다.

    Args:
        players: 앉은 순서(player_order)대로 정렬된 플레이어 리스트
        leader_id: 현재 리더(원정대장)의 id - 금색으로 강조
        team_ids: 현재 제안/편성된 원정대원 id 목록 - 파란 테두리로 강조
        center_label: 원탁 가운데 표시할 문구

    Returns:
        PNG 이미지 바이트를 담은 BytesIO (파일 포인터는 처음으로 되감겨 있음)
    """
    team_ids = set(team_ids or [])
    n = len(players)

    size = 900
    cx, cy = size // 2, size // 2
    table_radius = 260
    seat_radius_pos = 370  # 좌석 중심이 배치되는 반지름
    seat_size = 78 if n <= 8 else 68

    img = Image.new("RGBA", (size, size), _BG)
    draw = ImageDraw.Draw(img)

    # ── 원탁 ──
    draw.ellipse(
        [cx - table_radius, cy - table_radius, cx + table_radius, cy + table_radius],
        fill=_TABLE_FILL,
        outline=_TABLE_EDGE,
        width=6,
    )

    _draw_clockwise_arrow(draw, cx, cy, table_radius - 40)

    # ── 원탁 가운데 문구 ──
    title_font = _font(34, bold=True)
    sub_font = _font(20)
    _draw_centered_text(draw, (cx, cy - 14), _truncate(center_label, 14), title_font, _TEXT_LIGHT)
    _draw_centered_text(draw, (cx, cy + 26), "시계 방향으로 진행", sub_font, (220, 220, 220, 255))

    # ── 좌석 ──
    name_font = _font(22, bold=True)
    tag_font = _font(16, bold=True)
    positions = _seat_positions(n, cx, cy, seat_radius_pos)

    for player, (x, y, _angle) in zip(players, positions):
        is_leader = leader_id is not None and player.id == leader_id
        is_team = player.id in team_ids

        if is_leader:
            fill = _SEAT_LEADER
            text_color = _TEXT_DARK
        elif is_team:
            fill = _SEAT_TEAM
            text_color = _TEXT_LIGHT
        else:
            fill = _SEAT_DEFAULT
            text_color = _TEXT_LIGHT

        is_ai = getattr(player, "is_ai", False)
        r = seat_size / 2
        draw.ellipse(
            [x - r, y - r, x + r, y + r],
            fill=fill,
            outline=(255, 255, 255, 255),
            width=4 if is_leader or is_team else 2,
        )

        seat_label = _seat_glyph(player)
        _draw_centered_text(draw, (x, y), seat_label, name_font, text_color)

        if is_leader:
            _draw_centered_text(draw, (x, y - r - 22), "리더", tag_font, _SEAT_LEADER)

        if is_ai:
            _draw_ai_badge(draw, x + r * 0.72, y + r * 0.72)

        name = _truncate(_clean_text(player.name), 8)
        name_y = y + r + 22
        _draw_centered_text(draw, (x, name_y), name, tag_font, _TEXT_LIGHT)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _seat_glyph(player: "Player") -> str:
    """좌석 안에 표시할 짧은 글자 (아이콘 폰트가 없으므로 이름 첫 글자 사용)."""
    name = _clean_text(player.name)
    for ch in name:
        if ch.isalnum():
            return ch
    return name[:1] if name else "?"


def _draw_ai_badge(draw: ImageDraw.ImageDraw, x: float, y: float):
    """AI 플레이어 좌석에 작은 'AI' 배지를 그린다."""
    r = 15
    draw.ellipse([x - r, y - r, x + r, y + r], fill=(44, 62, 80, 255), outline=(255, 255, 255, 255), width=2)
    _draw_centered_text(draw, (x, y), "AI", _font(13, bold=True), _TEXT_LIGHT)


def _draw_centered_text(draw: ImageDraw.ImageDraw, xy, text: str, font, fill):
    x, y = xy
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text((x - w / 2 - bbox[0], y - h / 2 - bbox[1]), text, font=font, fill=fill)
