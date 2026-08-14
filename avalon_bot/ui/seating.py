"""원정대 자리 배치를 원탁 이미지로 그려주는 모듈 - 아발롬

오프라인으로 아발롬을 할 때는 원으로 둘러앉아 시계 방향으로 리더가
넘어가기 때문에, 디스코드에서도 같은 느낌이 나도록 플레이어를
원형으로 배치한 이미지를 생성한다.
"""

from __future__ import annotations
import io
import logging
import math
import os
import re
from typing import List, Optional, TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("avalon.seating")

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


# 번들 폰트를 열 수 없을 때 시도해볼 시스템 한글 폰트 경로들
# (윈도우: 맑은 고딕, macOS: 애플고딕, 리눅스: 나눔고딕)
_SYSTEM_FONT_FALLBACKS = {
    False: [
        r"C:\Windows\Fonts\malgun.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ],
    True: [
        r"C:\Windows\Fonts\malgunbd.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    ],
}

_font_cache: dict = {}
_font_warning_shown = False


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """폰트를 불러온다. 번들 폰트가 없거나 손상됐어도 게임이 멈추지 않도록,
    시스템 한글 폰트 → PIL 기본 폰트 순서로 대체한다."""
    global _font_warning_shown

    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]

    candidates = [_FONT_BOLD_PATH if bold else _FONT_REGULAR_PATH]
    candidates += _SYSTEM_FONT_FALLBACKS[bold]

    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            font = ImageFont.truetype(path, size)
            _font_cache[key] = font
            return font
        except OSError as e:
            log.warning("폰트를 열지 못했습니다 (%s): %s", path, e)

    if not _font_warning_shown:
        log.warning(
            "사용 가능한 한글 폰트를 찾지 못했습니다. "
            "avalon_bot/assets/fonts/NanumGothic-Regular.ttf, "
            "NanumGothic-Bold.ttf 파일이 있는지 확인해주세요. "
            "일단 기본 폰트로 대체해서 진행합니다 (한글이 깨져 보일 수 있음)."
        )
        _font_warning_shown = True

    try:
        font = ImageFont.load_default(size=size)
    except TypeError:
        # 구버전 Pillow는 load_default()에 size 인자를 받지 않는다
        font = ImageFont.load_default()
    _font_cache[key] = font
    return font


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
    """원탁 가운데에 큼직한 '시계 방향' 화살표(호)만 그린다."""
    width = max(10, int(radius * 0.16))
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    start_deg, end_deg = -110, 70
    draw.arc(bbox, start=start_deg, end=end_deg, fill=_ARROW_COLOR, width=width)

    end_angle = math.radians(end_deg)
    tip_x = cx + radius * math.cos(end_angle)
    tip_y = cy + radius * math.sin(end_angle)

    # 화살촉의 밑변은 진행 방향(tangent)의 "뒤쪽"에 있어야 뾰족한 끝(tip)이
    # 진행 방향을 가리킨다 - 부호를 반대로 하면 화살표가 거꾸로 보인다.
    tangent = end_angle + math.pi / 2
    head_len = width * 1.8
    left = (
        tip_x + head_len * math.cos(tangent - math.radians(150)),
        tip_y + head_len * math.sin(tangent - math.radians(150)),
    )
    right = (
        tip_x + head_len * math.cos(tangent + math.radians(150)),
        tip_y + head_len * math.sin(tangent + math.radians(150)),
    )
    draw.polygon([(tip_x, tip_y), left, right], fill=_ARROW_COLOR)


def render_seating_circle(
    players: List["Player"],
    leader_id: Optional[int] = None,
    team_ids: Optional[List[int]] = None,
) -> io.BytesIO:
    """플레이어를 원탁에 둘러앉힌 좌석 배치 이미지를 생성한다.

    이름/좌석을 크게 키우기 위해 가운데는 시계 방향 화살표만 그리고,
    퀘스트 번호 등 다른 문구는 (임베드 쪽에 이미 있으므로) 넣지 않는다.

    Args:
        players: 앉은 순서(player_order)대로 정렬된 플레이어 리스트
        leader_id: 현재 리더(원정대장)의 id - 금색으로 강조
        team_ids: 현재 제안/편성된 원정대원 id 목록 - 파란 테두리로 강조

    Returns:
        PNG 이미지 바이트를 담은 BytesIO (파일 포인터는 처음으로 되감겨 있음)
    """
    team_ids = set(team_ids or [])
    n = len(players)

    size = 820
    cx, cy = size // 2, size // 2
    table_radius = 130
    seat_radius_pos = 285  # 좌석 중심이 배치되는 반지름
    seat_size = 150 if n <= 6 else (135 if n <= 8 else 120)
    name_max_len = 7 if n <= 8 else 6

    img = Image.new("RGBA", (size, size), _BG)
    draw = ImageDraw.Draw(img)

    # ── 원탁 (가운데는 방향 표시만) ──
    draw.ellipse(
        [cx - table_radius, cy - table_radius, cx + table_radius, cy + table_radius],
        fill=_TABLE_FILL,
        outline=_TABLE_EDGE,
        width=6,
    )
    _draw_clockwise_arrow(draw, cx, cy, table_radius - 28)

    # ── 좌석 (최대한 크게) ──
    name_font = _font(40, bold=True)
    label_font = _font(30, bold=True)
    tag_font = _font(24, bold=True)
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
            width=5 if is_leader or is_team else 3,
        )

        seat_label = _seat_glyph(player)
        _draw_centered_text(draw, (x, y), seat_label, name_font, text_color)

        if is_leader:
            _draw_centered_text(draw, (x, y - r - 30), "리더", tag_font, _SEAT_LEADER)

        if is_ai:
            _draw_ai_badge(draw, x + r * 0.72, y + r * 0.72)

        name = _truncate(_clean_text(player.name), name_max_len)
        name_y = y + r + 30
        _draw_centered_text(draw, (x, name_y), name, label_font, _TEXT_LIGHT)

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
    """AI 플레이어 좌석에 'AI' 배지를 그린다."""
    r = 24
    draw.ellipse([x - r, y - r, x + r, y + r], fill=(44, 62, 80, 255), outline=(255, 255, 255, 255), width=3)
    _draw_centered_text(draw, (x, y), "AI", _font(20, bold=True), _TEXT_LIGHT)


def _draw_centered_text(draw: ImageDraw.ImageDraw, xy, text: str, font, fill):
    x, y = xy
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text((x - w / 2 - bbox[0], y - h / 2 - bbox[1]), text, font=font, fill=fill)
