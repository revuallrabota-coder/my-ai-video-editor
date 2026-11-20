"""Сопоставление исправленной пользователем расшифровки и времени речи.

Без автоматического выдумывания текста. Когда исправлений много, тайминг
является приблизительным: Whisper не выполняет forced alignment.
"""
from __future__ import annotations

import difflib
import re
from typing import Sequence

Word = tuple[float, float, str]


def plain_transcript(words: Sequence[Word]) -> str:
    return " ".join(text.strip() for _, _, text in words if text.strip()).strip()


def _normal(word: str) -> str:
    return re.sub(r"[^\wа-яё-]+", "", word, flags=re.IGNORECASE).lower()


def align_corrected_words(
    original: Sequence[Word], corrected: str, duration: float,
) -> list[Word]:
    """Возвращает ТОЛЬКО слова пользователя, оставляя доступные таймкоды.

    Совпавшие слова используют точные времена из Whisper. Остальные
    слова получают приблизительные времена внутри исправленного блока.
    """
    new_words = corrected.split()
    if not new_words:
        raise ValueError("Исправленный текст пустой.")
    if len(new_words) > 1000 or len(corrected) > 6000:
        raise ValueError("Исправленный текст слишком длинный (максимум 6000 символов).")

    if not original:
        end = max(0.2, float(duration))
        step = end / len(new_words)
        return [(i * step, max(i * step + 0.05, (i + 1) * step), w)
                for i, w in enumerate(new_words)]

    a = [_normal(x[2]) for x in original]
    b = [_normal(x) for x in new_words]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    output: list[Word] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "delete":
            continue
        if tag == "equal":
            output.extend((float(original[i1+k][0]), float(original[i1+k][1]), new_words[j1+k])
                          for k in range(j2-j1))
            continue
        count = j2 - j1
        if not count:
            continue
        left = float(original[i1][0]) if i1 < len(original) else float(original[-1][1])
        if i2 > i1:
            right = float(original[i2 - 1][1])
        elif i1 < len(original):
            right = float(original[i1][1])
        else:
            right = min(float(duration), left + max(0.16, 0.18 * count))
        if right <= left:
            right = left + max(0.15, 0.14 * count)
        step = (right-left) / count
        for j in range(count):
            start = max(0.0, left+j*step)
            output.append((start, max(start+0.04, left+(j+1)*step), new_words[j1+j]))
    return output


def apply_word_fixes(
    original: Sequence[Word],
    replacements: str,
) -> list[Word]:
    """Команда /fix ошибка=правильно; ошибка2=правильно2.

    Удобно для пары ошибок без переписывания всей речи.
    Времена слов сохраняются; совпадающие ошибочные слова заменяются все.
    """
    rules: dict[str, str] = {}
    for part in replacements.split(";"):
        if not part.strip():
            continue
        if "=" not in part:
            raise ValueError("Формат: /fix неверно=верно; другое=правильно")
        wrong, right = (x.strip() for x in part.split("=",1))
        if not _normal(wrong) or not right or len(right) > 80:
            raise ValueError("Укажи слово до и после знака =")
        rules[_normal(wrong)] = right
    if not rules or len(rules) > 20:
        raise ValueError("Можно исправить от 1 до 20 слов за сообщение.")
    fixed: list[Word] = []
    replaced = 0
    for a,b,word in original:
        key = _normal(word)
        if key in rules:
            fixed.append((a,b,rules[key]))
            replaced+=1
        else:
            fixed.append((a,b,word))
    if not replaced:
        raise ValueError("Не нашла указанных ошибочных слов в расшифровке.")
    return fixed


def map_words_to_ranges(
    original: Sequence[Word], kept: Sequence, speed: float = 1.0,
) -> list[Word]:
    """Преобразует таймкоды исходника в склеенное и ускоренное видео."""
    mapped: list[Word] = []
    timeline = 0.0
    for segment in kept:
        a, b = float(segment.start), float(segment.end)
        for start, end, word in original:
            left = max(float(start), a)
            right = min(float(end), b)
            if right <= left + 0.025:
                continue
            t0 = (timeline + left-a) / speed
            t1 = (timeline + right-a) / speed
            mapped.append((max(0.0,t0), max(t0+0.03,t1), word))
        timeline += b-a
    mapped.sort(key=lambda item: (item[0], item[1]))
    return mapped


def shift_word_timestamps(
    words: Sequence[Word],
    delay_seconds: float = 0.30,
    total_duration: float | None = None,
) -> list[Word]:
    """Смещает ТОЛЬКО титры, а не голос/видео. Плюс = позже.

    Применяется после монтажа на финальной временной шкале.
    Не растягивает речь и не меняет скорость воспроизведения.
    """
    delay = float(delay_seconds)
    if not -0.5 <= delay <= 1.5:
        raise ValueError("Смещение субтитров: от -0.5 до +1.5 сек.")
    result: list[Word] = []
    for start, end, word in words:
        a = max(0.0, float(start) + delay)
        b = float(end) + delay
        if total_duration is not None:
            if a >= float(total_duration) - 0.015:
                continue
            b = min(b, float(total_duration))
        if b > a + 0.025 and word.strip():
            result.append((a, b, word))
    return result
