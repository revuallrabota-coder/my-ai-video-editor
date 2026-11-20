"""Контрастные субтитры по ОБЩИМ приёмам из присланного ролика.

Отдельный шаблон: крупные красные смысловые слова, небольшая белая
строка, плавное проявление и умеренное изменение масштаба.
Водяные знаки/логотипы сторонних сервисов НЕ воспроизводятся.
"""
from __future__ import annotations

from typing import Sequence

from signature_captions import ass_color, ass_time, event, pick_main_word, safe_text, split_groups

RED = "#F0443E"


def build_contrast_ass(
    words: Sequence[tuple[float, float, str]],
    hook: str = "",
    accent_color: str = RED,
    caption_position: str = "middle",
    font_profile: str = "elegant",
) -> tuple[str, int]:
    red = ass_color(accent_color)
    if caption_position not in ("top", "middle", "bottom"):
        raise ValueError("Неизвестное положение субтитров.")
    fonts = {"elegant": ("Liberation Serif", "1"), "clean": ("Liberation Sans", "0"), "bold": ("DejaVu Sans", "0")}
    if font_profile not in fonts:
        raise ValueError("Неизвестный шрифт.")
    fontname, italic = fonts[font_profile]
    vertical_shift = {"top": -365, "middle": 0, "bottom": 185}[caption_position]
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        "PlayResX: 720\nPlayResY: 1280\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Small,Liberation Sans,34,&H00FFFFFF,&H00FFFFFF,&H00212223,"
        "&H99000000,0,0,0,0,100,100,0,0,1,1.8,1.0,5,60,60,40,1\n"
        f"Style: Strong,{fontname},69,{red},{red},&H00222222,"
        f"&H99000000,1,{italic},0,0,100,100,0,0,1,2.0,1.0,5,40,40,40,1\n"
        f"Style: Title,Liberation Sans,65,{red},{red},&H00222222,"
        "&H99000000,1,0,0,0,100,100,0,0,1,1,1,5,52,52,40,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    groups = split_groups(words)
    events: list[str] = []
    for i, group in enumerate(groups):
        start = max(0.0, group[0][0] - 0.10)
        end = group[-1][1] + 0.30
        if i + 1 < len(groups):
            end = min(end, max(start + 0.20, groups[i + 1][0][0] + 0.05))
        length_ms = int((end - start) * 1000)
        if length_ms < 230:
            continue
        fadein = min(265, int(length_ms * .25))
        fadeout = min(210, int(length_ms * .20))
        motion = min(390, int(length_ms * .50))
        highlight = pick_main_word(group)
        main = safe_text(group[highlight][2]).strip(" ,.!?").upper()
        small = safe_text(" ".join(w[2] for j, w in enumerate(group) if j != highlight))
        if main:
            font_size = 69 if len(main) <= 10 else 60 if len(main) <= 13 else 48
            text = (
                r"{\an5\move(360,"+str(766+vertical_shift)+",360,"+str(755+vertical_shift)+",0,"+str(motion)+")"
                r"\fad("+str(fadein)+","+str(fadeout)+")"
                r"\fscx95\fscy95"
                r"\t(0,"+str(motion)+r",0.7,\fscx100\fscy100)"
                r"\fs"+str(font_size)+"}"+main
            )
            events.append(event(1,start,end,"Strong",text))
        if small:
            text=(
                r"{\an5\move(360,"+str(829+vertical_shift)+",360,"+str(822+vertical_shift)+",0,"+str(motion)+")"
                r"\fad("+str(fadein)+","+str(fadeout)+")"
                r"\fscx97\fscy97"
                r"\t(0,"+str(motion)+r",0.7,\fscx100\fscy100)}"+small
            )
            events.append(event(0,start,end,"Small",text))

    title = safe_text(hook)[:70]
    if title:
        # Только собственный текст пользователя, без "Cheat Code".
        duration = min(5.0, max(1.7, groups[-1][-1][1] if groups else 2.5))
        text=(
            r"{\an5\pos(360,185)\fad(300,300)"
            r"\fscx95\fscy95\t(0,450,\fscx100\fscy100)}"
            +title.upper()
        )
        events.append(event(2,0.0,duration,"Title",text))
    events = [x for x in events if x]
    return header+"".join(events),len(events)
