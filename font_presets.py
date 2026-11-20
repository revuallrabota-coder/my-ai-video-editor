"""Готовые шрифтовые профили для вертикальных Reels с кириллицей.

Примеры из присланных роликов интерпретируются как визуальные категории:
'bebas' — вытянутый конденсированный заголовок (не выдаём подмену за Bebas Neue);
'platform' — широкий жирный акцент, по духу Platform;
'bubble' — округлый стикер с контуром;
'script' — декоративная подпись;
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
    "script": FontSpec("Lobster Two", 78, 1, 1, 100, 100, 1.6),
    "modern": FontSpec("Lato", 73, 1, 0, 100, 100, 1.3),
}

def choose_font(name: str) -> FontSpec:
    try:
        return PRESETS[name]
    except KeyError:
        raise ValueError(f"Неизвестный шрифт: {name}") from None
