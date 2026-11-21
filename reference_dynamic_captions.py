"""Читаемые субтитры Reels по таймкодам речи, с безопасными полями.

Все текстовые слои и подложки используют ОДИН и тот же центр и время.
Ни один длинный акцент не должен пересекать края изображения 9:16.
"""
from __future__ import annotations

import math
import re
import subprocess
from functools import lru_cache
from typing import Sequence

from font_presets import FontSpec, choose_font
from signature_captions import (
    ass_color, ass_time, pick_main_word, safe_text, split_groups,
)
from word_captions import word_events

Word = tuple[float, float, str]
PLAY_WIDTH, PLAY_HEIGHT = 720, 1280
TEXT_SAFE_WIDTH = 508
CENTER_X = PLAY_WIDTH // 2

COLOR_PALETTES = {
    "editorial": ("#F0443E", "#FFFFFF"),
    "luxe": ("#D8BFA0", "#FFF4E5"),
    "minimal": ("#FFFFFF", "#EFEFEF"),
    "neon": ("#D7FF6C", "#F3F7E7"),
    "pop": ("#FF7BB6", "#FFF3F9"),
    "old_money": ("#CEB68A", "#FFF3E1"),
    "vintage": ("#D79B6D", "#F4DFC7"),
    "street": ("#DEEF5A", "#F5F5F0"),
    "elegant": ("#F0DBDC", "#FFFFFF"),
}


@lru_cache(maxsize=24)
def _font_file(family: str) -> str | None:
    """Use exact installed font metrics where available, never download fonts."""
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{file}", family],
            capture_output=True, text=True, timeout=4, check=True,
        )
        value = result.stdout.strip()
        from pathlib import Path
        if value and Path(value).is_file():
            return value
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _estimated_width(text: str, size: int, font: FontSpec) -> float:
    """Conservative fallback if Pillow/fontconfig is not installed."""
    capital = sum(c.isupper() for c in text if c.isalpha())
    latin = sum(c.isascii() and c.isalpha() for c in text)
    others = sum(c.isalpha() for c in text) - capital
    spaces = text.count(" ")
    punctuation = max(0, len(text) - capital - others - spaces)
    return size * (0.75 * capital + 0.57 * others + 0.60 * latin * 0.0
                   + 0.30 * spaces + 0.36 * punctuation) * font.scale_x / 100


def _measure_width(text: str, size: int, font: FontSpec) -> float:
    try:
        from PIL import ImageFont
        path = _font_file(font.name)
        if path:
            rendered = ImageFont.truetype(path, size=size)
            return rendered.getlength(text) * font.scale_x / 100
    except (ImportError, OSError, ValueError):
        pass
    return _estimated_width(text, size, font)


def fit_caption_size(
    text: str,
    requested: int,
    font: FontSpec,
    *,
    max_width: int = TEXT_SAFE_WIDTH,
) -> int:
    """Choose actual ASS font size to keep any word/phrase inside safe margins."""
    if not text.strip():
        return 30
    candidate = min(90, max(28, int(requested)))
    # Conservative correction for slight libass/Pillow font measurement differences.
    budget = max_width * 0.91
    for size in range(candidate, 23, -1):
        if _measure_width(text, size, font) <= budget:
            return size
    return 24


def _rounded_plate(half_width: int, half_height: int, radius: int = 20) -> str:
    """Closed libass vector shape, centered on the exact subtitle position."""
    w, h = max(45, half_width), max(23, half_height)
    r = min(radius, w // 2, h // 2)
    return (
        f"m {-w+r} {-h} l {w-r} {-h} "
        f"b {w} {-h} {w} {-h+r//2} {w} {-h+r} "
        f"l {w} {h-r} b {w} {h-r//2} {w} {h} {w-r} {h} "
        f"l {-w+r} {h} b {-w} {h} {-w} {h-r//2} {-w} {h-r} "
        f"l {-w} {-h+r} b {-w} {-h+r//2} {-w} {-h} {-w+r} {-h}"
    )


def _wrap_two_lines(text: str, font: FontSpec, requested: int) -> tuple[str, int, float, int]:
    """Wrap only long small phrases. Do not break a single Russian word."""
    size = fit_caption_size(text, requested, font)
    if len(text.split()) < 2 or size >= 28:
        return text, size, _measure_width(text, size, font), 1
    tokens = text.split()
    candidates = [
        (" ".join(tokens[:i]), " ".join(tokens[i:]))
        for i in range(1, len(tokens))
    ]
    left, right = min(
        candidates,
        key=lambda pair: max(
            _measure_width(pair[0], requested, font),
            _measure_width(pair[1], requested, font)
        ),
    )
    size = min(
        fit_caption_size(left, requested, font),
        fit_caption_size(right, requested, font),
    )
    if size < 28:
        return text, 24, _measure_width(text, 24, font), 1
    return left + r"\N" + right, size, max(
        _measure_width(left, size, font),
        _measure_width(right, size, font),
    ), 2


def build_reference_dynamic_ass(
    words: Sequence[Word],
    *,
    color: str = "auto",
    caption_position: str = "middle",
    font_profile: str = "bold",
    small_font_profile: str = "modern",
    caption_variant: str = "editorial",
    background_style: str = "occasional",
    animation_style: str = "float",
) -> tuple[str, int]:
    if caption_position not in ("top", "middle", "bottom"):
        raise ValueError("Недопустимое положение субтитров.")
    if caption_variant not in COLOR_PALETTES:
        raise ValueError("Неизвестный вариант оформления субтитров.")
    if background_style not in ("off", "occasional", "frequent", "always"):
        raise ValueError("Недопустимый режим подложки субтитров.")
    if animation_style not in ("float", "pop", "slide"):
        raise ValueError("Недопустимая анимация текста.")

    big_font = choose_font(font_profile)
    small_font = choose_font(small_font_profile)
    accent_hex, small_hex = COLOR_PALETTES[caption_variant]
    primary = ass_color(accent_hex if color == "auto" else color)
    white = ass_color(small_hex)

    # The whole readable composition stays in the central 70% of the frame.
    # y changes by <=14 px: no more scattered words across the salon background.
    ybase = {"top": 400, "middle": 713, "bottom": 866}[caption_position]

    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        "PlayResX: 720\nPlayResY: 1280\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Main,{big_font.name},69,{primary},{primary},&H0020191C,"
        f"&H99000000,{big_font.bold},{big_font.italic},0,0,"
        f"{big_font.scale_x},{big_font.scale_y},0,0,"
        f"1,{big_font.outline},0.8,5,64,64,40,1\n"
        f"Style: Tiny,{small_font.name},36,{white},{white},&H0020191C,"
        f"&H89000000,{small_font.bold},{small_font.italic},0,0,"
        f"{small_font.scale_x},{small_font.scale_y},0,0,"
        "1,1.0,0.5,5,64,64,40,1\n"
        "Style: Plate,DejaVu Sans,12,&H00FFFFFF,&H00FFFFFF,&H00101010,"
        "&H73000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n"
        "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    # Pick one emphasized semantic word per 2–3 word group. Every other word
    # appears as one small subtitle, without a duplicated distant "context".
    groups = split_groups(words)
    main_indexes: set[int] = set()
    offset = 0
    for group in groups:
        main_indexes.add(offset + pick_main_word(group))
        offset += len(group)
    events = word_events(words)
    readable: list[tuple[float, float, str, bool]] = []
    i = 0
    while i < len(events):
        start, end, word = events[i]
        if i in main_indexes:
            readable.append((start, end, word, True))
            i += 1
            continue
        parts = [word]
        j = i + 1
        while j < len(events) and j not in main_indexes and len(parts) < 3:
            nxt_start, nxt_end, nxt_word = events[j]
            if nxt_start - end > 0.16 or nxt_end - start > 1.05:
                break
            parts.append(nxt_word)
            end = nxt_end
            j += 1
        readable.append((start, end, " ".join(parts), False))
        i = j

    lines: list[str] = []
    for index, (begin, end, raw, strong) in enumerate(readable):
        if end - begin < 0.07:
            continue
        clean = safe_text(raw)
        if not clean:
            continue
        shown = clean.upper() if strong else clean
        # Short accent = punchy but not huge. Even a 16-letter word is fitted.
        desired = (74, 65, 70, 61)[index % 4] if strong else (37, 34, 39)[index % 3]
        face = big_font if strong else small_font
        shown, size, measured, line_count = _wrap_two_lines(shown, face, desired)
        # Guard against font substitutions with wider real glyph metrics.
        if measured > TEXT_SAFE_WIDTH * 0.91:
            size = fit_caption_size(shown.replace(r"\N", " "), size, face)
            measured = min(measured, TEXT_SAFE_WIDTH * 0.91)
        y = ybase + (-9, 0, 9)[index % 3]
        lifetime = max(100, int((end - begin)*1000))
        rise = min(235, max(60, int(lifetime*0.48)))
        fade = min(130, max(25, int(lifetime*0.22)))
        fade_out = min(105, max(20, int(lifetime*0.20)))
        if fade + fade_out >= lifetime:
            fade = int(lifetime*0.22)
            fade_out = int(lifetime*0.18)
        delta = 11 if strong else 7
        if animation_style == "float":
            movement = (
                rf"\move({CENTER_X},{y+delta},{CENTER_X},{y},0,{rise})"
            )
        elif animation_style == "slide":
            movement = (
                rf"\move({CENTER_X+delta},{y},{CENTER_X},{y},0,{rise})"
            )
        else:
            movement = rf"\pos({CENTER_X},{y})"
        scale = 94 if strong else 97
        fade_tag = rf"\fad({fade},{fade_out})"
        text_tag = (
            r"{\an5" + movement + fade_tag
            + rf"\fscx{scale}\fscy{scale}"
            + rf"\t(0,{rise},0.65,\fscx100\fscy100)"
            + rf"\fs{size}\q2\blur0.35" + "}"
        )
        # Put backing behind the ACTUAL event at the SAME x/y and begin/end.
        # 6–12 px padding, with max width capped inside Reels safe margins.
        plate = (
            background_style == "always"
            or background_style == "frequent" and index % 2 == 0
            or background_style == "occasional" and (index % 3 == 0)
        )
        if plate:
            half_w = min(268, int(math.ceil(measured / 2)) + 18)
            half_h = int(size * (0.73 if line_count == 1 else 1.12)) + 9
            shape = (
                r"{\an5" + movement + fade_tag
                + r"\p1\1c&H181616&\1a&H84&}"
                + _rounded_plate(half_w, half_h)
            )
            lines.append(
                f"Dialogue: 0,{ass_time(begin)},{ass_time(end)},Plate,,0,0,0,,{shape}\n"
            )
        style = "Main" if strong else "Tiny"
        lines.append(
            f"Dialogue: 2,{ass_time(begin)},{ass_time(end)},{style},,0,0,0,,"
            + text_tag + shown + "\n"
        )
    return header + "".join(lines), len(lines)
