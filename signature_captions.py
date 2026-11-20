"""Анимированные субтитры в постоянном визуальном стиле для Reels.

Стилизация по загруженному референсу пользователя:
- маленькая белая фраза сверху, крупное нежно-розовое слово ниже;
- курсив с засечками, мягкое появление и лёгкий подъём без скачка;
- выделение смысловых слов по таймкодам распознанной речи;
- заголовок сверху опционален (не копируем текст чужого видео).

Файл не хранит и не копирует исходный сторонний референс.
"""
from __future__ import annotations

import re
from typing import Sequence

WIDTH, HEIGHT = 720, 1280
DEFAULT_ACCENT = "#EBC0C8"
STOP_WORDS = {
    "это", "как", "что", "чтобы", "когда", "тебя", "тебе", "тебя",
    "будет", "просто", "вот", "если", "или", "для", "потому",
    "такая", "такое", "которые", "который", "которую", "когда",
    "видео", "я", "мы", "вы", "они", "она", "мне", "мой",
    "всё", "все", "ещё", "уже", "ну", "да", "нет", "без", "тоже",
}


def ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hh, rem = divmod(centiseconds, 360000)
    mm, rem = divmod(rem, 6000)
    ss, cs = divmod(rem, 100)
    return f"{hh}:{mm:02}:{ss:02}.{cs:02}"


def safe_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\\", "").replace("{", "(").replace("}", ")")).strip()


def ass_color(color: str) -> str:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color or ""):
        color = DEFAULT_ACCENT
    c = color[1:]
    return f"&H00{c[4:6]}{c[2:4]}{c[0:2]}&".upper()


def split_groups(
    words: Sequence[tuple[float, float, str]],
) -> list[list[tuple[float, float, str]]]:
    groups: list[list[tuple[float, float, str]]] = []
    current: list[tuple[float, float, str]] = []
    for start, end, raw in words:
        word = safe_text(raw)
        if not word or end <= start:
            continue
        # Разбивка на 2-4 слова, соответствующая коротким фразам референса.
        if current and (
            len(current) >= 5
            or start - current[-1][1] >= 0.52
            or end - current[0][0] > 2.75
            or sum(len(w[2]) + 1 for w in current) + len(word) > 38
            or bool(re.search(r"[.!?]$", current[-1][2]))
        ):
            groups.append(current)
            current = []
        current.append((float(start), float(end), word))
    if current:
        groups.append(current)
    return groups


def pick_main_word(group: Sequence[tuple[float, float, str]]) -> int:
    def score(pair: tuple[int, tuple[float, float, str]]) -> tuple[float, float]:
        index, (_, _, raw) = pair
        cleaned = re.sub(r"[^\wа-яёА-ЯЁ-]", "", raw).lower()
        weight = min(12, len(cleaned))
        if cleaned in STOP_WORDS:
            weight -= 6
        if len(cleaned) <= 2:
            weight -= 3
        # Небольшое предпочтение словам в конце фразы.
        return weight + 0.3 * index, index
    return max(enumerate(group), key=score)[0]


def event(layer: int, start: float, end: float, style: str, text: str) -> str:
    if end - start < 0.10:
        return ""
    return (
        f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},"
        f"{style},,0,0,0,,{text}\n"
    )


def build_signature_ass(
    words: Sequence[tuple[float, float, str]],
    color: str = DEFAULT_ACCENT,
    hook: str = "",
) -> tuple[str, int]:
    """Возвращает содержимое .ass и число событий.

    Все слова берутся только из исходной речи и используются локально;
    сетевые сервисы не нужны.
    """
    accent = ass_color(color)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {WIDTH}\n"
        f"PlayResY: {HEIGHT}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Whisper,DejaVu Sans,33,&H00FFFFFF,&H00FFFFFF,&H00271728,"
        "&H85000000,0,0,0,0,100,100,0,0,1,1.5,1.0,5,60,60,40,1\n"
        f"Style: Accent,Liberation Serif,74,{accent},{accent},&H00221921,"
        "&H76000000,1,1,0,0,100,100,0,0,1,1.6,2,5,35,35,40,1\n"
        f"Style: Hook,DejaVu Sans,55,{accent},{accent},&H00221921,"
        "&H85000000,1,0,0,0,100,100,0,0,1,2,2,5,50,50,40,1\n"
        "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events: list[str] = []
    groups = split_groups(words)
    # Позиция постоянная: субтитры не скачут по экрану между репликами.
    small_y = 754
    hero_y = 810
    for index, group in enumerate(groups):
        # Одна строка живёт всю ФРАЗУ, а не мигает на каждом слове.
        # Небольшой перекрёстный fade соседних фраз сглаживает смену.
        start = max(0.0, group[0][0] - 0.10)
        end = group[-1][1] + 0.35
        if index + 1 < len(groups):
            following = groups[index + 1][0][0]
            end = min(end, max(start + 0.22, following + 0.075))
        duration_ms = max(1, round((end - start) * 1000))
        if duration_ms < 220:
            continue

        # Для коротких фраз не даём анимации занять всё время показа.
        fade_in = min(280, max(75, round(duration_ms * 0.25)))
        fade_out = min(230, max(70, round(duration_ms * 0.21)))
        rise_ms = min(460, max(180, round(duration_ms * 0.5)))

        main_index = pick_main_word(group)
        main_word = safe_text(group[main_index][2]).strip(" ,.")
        other = safe_text(" ".join(
            w[2] for i, w in enumerate(group) if i != main_index
        ))

        # Никакого скачка на 25 пикселей и резкого увеличения на 14%:
        # всего 7–11 пикселей подъёма и 4–6% изменения масштаба.
        if other:
            small = (
                r"{\an5\move(360,761,360," + str(small_y) + ",0," + str(rise_ms) + ")"
                r"\fad(" + str(fade_in) + "," + str(fade_out) + ")"
                r"\fscx97\fscy97\blur0.35"
                r"\t(0," + str(rise_ms) + r",0.65,\fscx100\fscy100)}"
                + other
            )
            events.append(event(0, start, end, "Whisper", small))

        if main_word:
            word = main_word.upper()
            size = 74 if len(word) <= 10 else 63 if len(word) <= 13 else 52
            hero = (
                r"{\an5\move(360,821,360," + str(hero_y) + ",0," + str(rise_ms) + ")"
                r"\fad(" + str(fade_in) + "," + str(fade_out) + ")"
                r"\fscx94\fscy94\blur0.4"
                r"\t(0," + str(rise_ms) + r",0.65,\fscx100\fscy100)"
                r"\fs" + str(size) + "}" + word
            )
            events.append(event(1, start, end, "Accent", hero))

    hook = safe_text(hook)[:70]
    if hook and groups:
        ends_at = min(5.0, max(1.5, groups[-1][-1][1]))
        # Не вводим на все видео текст чужой рекламной заставки:
        # заголовок указывается владельцем при запуске workflow.
        title = (
            r"{\an5\pos(360,126)\fad(220,240)"
            r"\fscx96\fscy96\t(0,260,\fscx100\fscy100)}"
            + hook.upper()
        )
        events.append(event(2, 0.0, ends_at, "Hook", title))
    events = [line for line in events if line]
    return header + "".join(events), len(events)
