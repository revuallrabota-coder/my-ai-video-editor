"""Одно слово за раз: плавная анимация Reels на основе таймкодов речи.

Без повторов, без нескольких фраз одновременно, без разъезжающихся
строк. Слова берутся из Whisper или из подтверждённого пользователем
текста. Все стили/цвета/положения по-прежнему выбираются отдельно.
"""
from __future__ import annotations

from typing import Sequence

from signature_captions import ass_color, ass_time, safe_text
from font_presets import choose_font

Word = tuple[float, float, str]


def word_events(
    words: Sequence[Word],
    position: str = "middle",
) -> list[tuple[float, float, str]]:
    """Одно непересекающееся событие для каждого достаточно длинного слова."""
    if position not in ("top", "middle", "bottom"):
        raise ValueError("Неверное положение субтитров.")
    ordered = sorted(
        ((max(0., float(a)), float(b), safe_text(w))
         for a, b, w in words if w and b > a),
        key=lambda x: (x[0], x[1])
    )
    events: list[tuple[float, float, str]] = []
    for i, (a, b, word) in enumerate(ordered):
        if not word:
            continue
        if events and a < events[-1][1]:
            previous_start, _, previous_text = events[-1]
            if a - previous_start >= 0.075:
                events[-1] = (previous_start, a, previous_text)
            else:
                # Явная ошибка таймкодов: пропускаем микродубли, не
                # запускаем два слова одновременно.
                continue
        if i + 1 < len(ordered):
            following = ordered[i + 1][0]
            if following > a + 0.085:
                b = min(max(b, a + 0.09), following - 0.005)
            else:
                b = min(b, a + 0.09)
        else:
            b = min(b + 0.12, a + 1.25)
        if b - a < 0.07:
            continue
        events.append((a, b, word))
    return events


def build_word_pop_ass(
    words: Sequence[Word],
    *,
    style: str = "signature",
    color: str = "auto",
    caption_position: str = "middle",
    font_profile: str = "elegant",
    hook: str = "",
) -> tuple[str, int]:
    """ASS-слой: мягкое всплытие слова точно в момент произнесения."""
    if style not in ("signature", "contrast", "classic"):
        raise ValueError("Неизвестный стиль субтитров.")
    font = choose_font(font_profile)
    positions = {"top": 360, "middle": 780, "bottom": 1055}
    if caption_position not in positions:
        raise ValueError("Неизвестная позиция текста.")
    if color == "auto":
        color = ("#F0443E" if style == "contrast" else
                 "#FFFFFF" if style == "classic" else "#EBC0C8")
    primary = ass_color(color)
    # Выбор пользовательского шрифта сохраняется и в режиме classic.
    face, italic, bold = font.name, font.italic, font.bold
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        "PlayResX: 720\nPlayResY: 1280\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Word,{face},{font.size},{primary},{primary},{font.outline_color},"
        f"&H71000000,{bold},{italic},0,0,{font.scale_x},{font.scale_y},0,0,"
        f"1,{font.outline},{font.shadow},5,45,45,40,1\n"
        f"Style: Hook,{face},52,{primary},{primary},&H00251B24,"
        f"&H71000000,{bold},{italic},0,0,{font.scale_x},{font.scale_y},"
        "0,0,1,1.8,1,5,52,52,40,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    y = positions[caption_position]
    lines = []
    for begin, end, word in word_events(words, caption_position):
        length_ms = max(1, round((end - begin) * 1000))
        # Очень короткие слова анимируются быстрее, поэтому не пропадают
        # в 250-миллисекундном fade-in, как в старой реализации.
        fade_in = min(155, max(24, round(length_ms * .24)))
        fade_out = min(95, max(18, round(length_ms * .15)))
        motion = min(310, max(70, round(length_ms * .63)))
        size = min(92, font.size + 2) if len(word) <= 9 else max(49, font.size - 10) if len(word) <= 12 else 51
        # Один лёгкий pop и подъём с zero-overlap по таймкодам.
        text = (
            r"{\an5\move(360,"+str(y+14)+",360,"+str(y)
            +",0,"+str(motion)+")"
            r"\fad("+str(fade_in)+","+str(fade_out)+")"
            r"\fscx87\fscy87\blur0.3"
            r"\t(0,"+str(motion)+r",0.72,\fscx100\fscy100)"
            r"\fs"+str(size)+"}"
            +word.upper()
        )
        lines.append(
            f"Dialogue: 0,{ass_time(begin)},{ass_time(end)},Word,,0,0,0,,{text}\n"
        )

    hook = safe_text(hook)[:70]
    if hook:
        video_end = max((end for _, end, _ in words), default=2.0)
        end = min(max(1.5, video_end), 4.5)
        text = (
            r"{\an5\pos(360,146)\fad(250,220)"
            r"\fscx93\fscy93\t(0,300,\fscx100\fscy100)}"+hook.upper()
        )
        lines.append(
            f"Dialogue: 1,{ass_time(0)},{ass_time(end)},Hook,,0,0,0,,{text}\n"
        )
    return header+"".join(lines), len(lines)
