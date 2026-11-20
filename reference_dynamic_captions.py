"""Dynamic captions modeled on the supplied 93s salon reference.

Original technique, not a copy of the third-party bot's watermark:
variable-size red emphasized words, small floating white phrases,
occasional translucent rounded black backing, varied safe text positions.
Speech timestamps always come from verified/transcribed original audio.
"""
from __future__ import annotations

import re
from typing import Sequence

from font_presets import choose_font
from signature_captions import (
    ass_color, ass_time, pick_main_word, safe_text, split_groups,
)
from word_captions import word_events

Word = tuple[float, float, str]


def _rounded_plate(half_width: int, half_height: int = 46, radius: int = 22) -> str:
    """ASS vector path, correctly rounded corners rather than a hard box."""
    w, h, r = half_width, half_height, radius
    return (
        f"m {-w+r} {-h} l {w-r} {-h} "
        f"b {w} {-h} {w} {-h+r//2} {w} {-h+r} "
        f"l {w} {h-r} b {w} {h-r//2} {w} {h} {w-r} {h} "
        f"l {-w+r} {h} b {-w} {h} {-w} {h-r//2} {-w} {h-r} "
        f"l {-w} {-h+r} b {-w} {-h+r//2} {-w} {-h} {-w+r} {-h}"
    )


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
    """Build independently animated subtitles with intermittent backing."""
    if caption_position not in ("top", "middle", "bottom"):
        raise ValueError("Недопустимое положение субтитров.")
    variants = {
        "editorial": ("#F0443E","#FFFFFF"),
        "luxe": ("#D8BFA0","#FFF4E5"),
        "minimal": ("#FFFFFF","#EFEFEF"),
        "neon": ("#D7FF6C","#F3F7E7"),
        "pop": ("#FF7BB6","#FFF3F9"),
    }
    if caption_variant not in variants:
        raise ValueError("Неизвестный вариант оформления субтитров.")
    if background_style not in ("off","occasional","frequent","always"):
        raise ValueError("Недопустимый режим подложки субтитров.")
    if animation_style not in ("float","pop","slide"):
        raise ValueError("Недопустимая анимация текста.")
    font = choose_font(font_profile)
    tiny_font = choose_font(small_font_profile)
    main_hex, small_hex = variants[caption_variant]
    primary = ass_color(main_hex if color == "auto" else color)
    white = ass_color(small_hex)
    # Безопасная зона Reels: не прячем текст под нижние кнопки/описание.
    ybase = {"top": 410, "middle": 720, "bottom": 860}[caption_position]
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        "PlayResX: 720\nPlayResY: 1280\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Main,{font.name},91,{primary},{primary},&H0020191C,"
        f"&H99000000,1,0,0,0,{font.scale_x},{font.scale_y},0,0,"
        "1,1.2,1.0,5,35,35,40,1\n"
        f"Style: Tiny,{tiny_font.name},35,{white},{white},&H0020191C,"
        f"&H89000000,{tiny_font.bold},{tiny_font.italic},0,0,"
        f"{tiny_font.scale_x},{tiny_font.scale_y},0,0,1,1.0,1.0,5,38,38,40,1\n"
        f"Style: Plate,DejaVu Sans,12,{white},{white},&H00101010,"
        "&H73000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n"
        "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    groups = split_groups(words)
    emphasized: dict[int, tuple[int, str]] = {}
    seq = 0
    for group_id, group in enumerate(groups):
        main = pick_main_word(group)
        others = safe_text(" ".join(w[2] for j,w in enumerate(group) if j != main))
        # Supplemental small white phrases, not always on-screen.
        context = others[:31] if group_id % 2 == 0 else ""
        emphasized[seq+main] = (group_id, context)
        seq += len(group)
    # Маленькие служебные слова не должны мелькать по 0.1-0.2 секунды.
    # Объединяем до трёх подряд в одну читаемую мини-фразу. Крупные
    # смысловые слова остаются отдельными анимированными акцентами.
    timed = word_events(words)
    readable: list[tuple[int, float, float, str]] = []
    i = 0
    while i < len(timed):
        begin, end, word = timed[i]
        start_index = i
        if i in emphasized:
            readable.append((i, begin, end, word))
            i += 1
            continue
        pieces = [word]
        j = i + 1
        while j < len(timed) and j not in emphasized and len(pieces) < 3:
            nxt_start, nxt_end, nxt_word = timed[j]
            if nxt_start - end > 0.19 or nxt_end - begin > 1.0:
                break
            pieces.append(nxt_word)
            end = nxt_end
            j += 1
        readable.append((start_index, begin, end, " ".join(pieces)))
        i = j

    lines: list[str] = []
    for index, begin, end, word in readable:
        if end - begin < 0.065:
            continue
        group_id, contextual = emphasized.get(index, (-1, ""))
        strong = group_id >= 0
        # Deterministic 3-way placement: float up/down and slightly off-center.
        x_offsets = (-85, 20, 85, -35, 55, -60)
        y_offsets = (-90, -20, 36, -48, 70, 0)
        base_x = 360 + x_offsets[(group_id if strong else index) % len(x_offsets)]
        base_y = ybase + y_offsets[(group_id if strong else index) % len(y_offsets)]
        lifetime = max(75, round((end-begin)*1000))
        rise = min(480, max(95, round(lifetime * .68)))
        fade = min(195, max(32, round(lifetime*.27)))
        fade_out = min(145, max(23, round(lifetime*.19)))
        size = (
            (107, 82, 96, 72)[group_id % 4] if strong else
            (34, 42, 32, 45, 36)[index % 5]
        )
        if len(word) > 12:
            size = max(32 if not strong else 37, round(size*.78))
        if len(word) > 17:
            size = min(size, 44 if strong else 33)
        delta = 24 if strong else 12
        scale = 88 if strong else 96
        shown = safe_text(word).strip()[:42]
        if not shown:
            continue
        # Все анимации используют реальные таймкоды произнесённых слов.
        # float — мягко вверх, slide — мягко вбок, pop — без рывка масштаба.
        if animation_style == "slide":
            movement = (r"\move("+str(base_x+min(18,delta))+","+str(base_y)+","
                        +str(base_x)+","+str(base_y)+",0,"+str(rise)+")")
        elif animation_style == "pop":
            movement = r"\pos("+str(base_x)+","+str(base_y)+")"
            scale = 91 if strong else 96
        else:
            movement = (r"\move("+str(base_x)+","+str(base_y+delta)+","
                        +str(base_x)+","+str(base_y)+",0,"+str(rise)+")")
        text = (
            r"{\an5"+movement+
            r"\fad("+str(fade)+","+str(fade_out)+")"
            r"\fscx"+str(scale)+r"\fscy"+str(scale)+r"\blur0.45"
            r"\t(0,"+str(rise)+r",0.65,\fscx100\fscy100)"
            r"\fs"+str(size)+"}"+(shown.upper() if strong else shown)
        )
        style = "Main" if strong else "Tiny"
        # A dark translucent pill only every fourth group, not everywhere.
        use_plate = (
            background_style == "always" or
            (background_style == "frequent" and strong and group_id % 2 == 0) or
            (background_style == "occasional" and strong and group_id % 4 == 2)
        )
        if use_plate:
            w = min(294, max(94, round(len(shown)*size*.39)+34))
            h = 51 if size > 90 else 43
            shape = (
                r"{\an5\pos("+str(base_x)+","+str(base_y)+r")\p1"
                r"\1c&H181616&\1a&H8C&\fad("+str(fade)+","+str(fade_out)+")}"
                +_rounded_plate(w,h)
            )
            lines.append(
                f"Dialogue: 0,{ass_time(begin)},{ass_time(end)},Plate,,0,0,0,,{shape}\n"
            )
        lines.append(
            f"Dialogue: 2,{ass_time(begin)},{ass_time(end)},{style},,0,0,0,,{text}\n"
        )
        if strong and contextual:
            context_y = base_y-61 if base_y > 450 else base_y+66
            other = (
                r"{\an5\move("+str(base_x)+","+str(context_y+11)+","
                +str(base_x)+","+str(context_y)+",0,"+str(rise)+")"
                r"\fad("+str(fade)+","+str(fade_out)+")\fs30}"
                +contextual
            )
            lines.append(
                f"Dialogue: 1,{ass_time(begin)},{ass_time(end)},Tiny,,0,0,0,,{other}\n"
            )
    return header+"".join(lines),len(lines)
