"""Ненавязчивые фильтры Reels, сохраняющие видимый оттенок маникюра.

Только проверенный whitelist фильтров FFmpeg, без пользовательского кода.
"""
from __future__ import annotations

FILTERS: dict[str,str] = {
    "none": "",
    "warm": "colorbalance=rs=0.032:gs=0.004:bs=-0.023",
    "soft": "eq=contrast=0.98:saturation=1.025:gamma=1.015",
    "cool": "colorbalance=rs=-0.018:gs=0.002:bs=0.025",
    "contrast": "eq=contrast=1.085:saturation=1.045",
    "clean": "eq=contrast=1.035:brightness=0.007:saturation=1.018",
    "film": "eq=contrast=1.04:saturation=0.94:gamma=0.985,colorbalance=rs=0.013:bs=-0.012",
    "matte": "eq=contrast=0.95:saturation=0.97:gamma=1.03",
}

def video_filter_chain(name: str) -> str:
    """Возвращает безопасную FFmpeg цепочку или объяснимую ошибку."""
    try:
        return FILTERS[name]
    except (KeyError, TypeError):
        raise ValueError("Неизвестный видеофильтр: " + str(name)) from None
