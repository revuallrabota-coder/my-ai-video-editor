"""Готовые шрифтовые профили для вертикальных Reels с кириллицей.

Примеры из присланных роликов интерпретируются как визуальные категории:
'bebas' — вытянутый конденсированный заголовок (не выдаём подмену за Bebas Neue);
'platform' — широкий жирный акцент, по духу Platform;
'bubble' — округлый стикер с контуром;
'script' — кириллическая декоративная курсивная подпись;
'modern' — современный строгий гротеск.

Все пакеты доступны через Ubuntu apt, нестандартные шрифты
не сохраняются в публичном GitHub и не предоставляются пользователю.
"""
from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class FontSpec:
    name: str
    size: int
    bold: int
    italic: int
    scale_x: int = 100
    scale_y: int = 100
    outline: float = 1.8
    shadow: float = 1.0
    outline_color: str = "&H00251B24"

PRESETS: dict[str, FontSpec] = {
    "elegant": FontSpec("Liberation Serif", 76, 1, 1),
    "clean": FontSpec("DejaVu Sans", 70, 0, 0),
    "bold": FontSpec("DejaVu Sans", 72, 1, 0),
    # Реальная кириллица вместо латинского Bebas Neue без русских букв.
    "bebas": FontSpec("DejaVu Sans Condensed", 88, 1, 0, 72, 112, 1.2),
    "platform": FontSpec("Lato Heavy", 71, 1, 0, 119, 98, 1.5),
    "bubble": FontSpec("Comfortaa", 72, 1, 0, 104, 100, 4.8, 1.7, "&H00171719"),
    "script": FontSpec("Liberation Serif", 81, 1, 1, 110, 98, 1.35),
    "modern": FontSpec("Lato", 73, 1, 0, 100, 100, 1.3),
    # Не требуется внешних/платных шрифтов: используем кириллические аналоги.
    "old_money": FontSpec("Liberation Serif", 79, 1, 0, 98, 100, 1.1, .55),
    "vintage": FontSpec("Liberation Serif", 78, 1, 1, 103, 99, 1.8, .8),
    "street": FontSpec("DejaVu Sans Condensed", 85, 1, 0, 90, 100, 2.6, 1.2),
    "refined": FontSpec("Lato", 72, 0, 0, 100, 100, .9, .55),
    # Дополнительные гарнитуры с настоящей русской кириллицей.
    # Их пакеты устанавливаются на runner (не храним шрифты в GitHub).
    "roboto": FontSpec("Roboto", 70, 1, 0, 100, 100, 1.1, .65),
    "open_sans": FontSpec("Open Sans", 69, 1, 0, 100, 100, 1.0, .6),
    "noto_sans": FontSpec("Noto Sans", 69, 1, 0, 100, 100, .95, .55),
    "ubuntu": FontSpec("Ubuntu", 72, 1, 0, 100, 100, 1.2, .65),
    "carlito": FontSpec("Carlito", 72, 1, 0, 100, 100, 1.0, .55),
    "lato_black": FontSpec("Lato Heavy", 73, 1, 0, 103, 100, 1.3, .75),
    "modern_condensed": FontSpec("DejaVu Sans Condensed", 75, 1, 0, 88, 100, 1.2, .6),

}

def choose_font(name: str) -> FontSpec:
    try:
        return PRESETS[name]
    except KeyError:
        raise ValueError(f"Неизвестный шрифт: {name}") from None
