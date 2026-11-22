"""Ненавязчивые фильтры Reels, сохраняющие видимый оттенок маникюра.

Только проверенный whitelist фильтров FFmpeg, без пользовательского кода.
"""
from __future__ import annotations

FILTERS: dict[str,str] = {
    "none": "",
    # A carefully differentiated family of looks. Previously several filters
    # moved saturation by 1-3%, which was almost invisible in rendered Reels.
    # All are applied to original footage BEFORE any graphic/text overlays.
    # Preserve skin and nail polish identity; no gimmick channel swapping.
    "warm": "eq=contrast=1.035:saturation=1.10:brightness=0.012,colorbalance=rs=0.065:gs=0.012:bs=-0.045",
    "soft": "eq=contrast=0.945:saturation=1.035:gamma=1.045",
    "cool": "eq=contrast=1.035:saturation=1.08,colorbalance=rs=-0.05:gs=0.005:bs=0.070",
    "contrast": "eq=contrast=1.155:saturation=1.10",
    "clean": "eq=contrast=1.085:brightness=0.011:saturation=1.075",
    "film": "eq=contrast=1.075:saturation=0.89:gamma=0.995,colorbalance=rs=0.035:bs=-0.025",
    "matte": "eq=contrast=0.92:saturation=0.88:gamma=1.055",
    "old_money": "eq=contrast=0.965:saturation=0.83:gamma=1.035,colorbalance=rs=0.045:bs=-0.035",
    "vintage": "eq=contrast=0.945:saturation=0.80:gamma=1.030,colorbalance=rs=0.080:bs=-0.053",
    "street": "eq=contrast=1.18:saturation=1.13:brightness=-0.007,colorbalance=rs=-0.023:bs=0.030",
    "elegant": "eq=contrast=1.035:saturation=0.985:gamma=1.015",
}

def video_filter_chain(name: str) -> str:
    """Возвращает безопасную FFmpeg цепочку или объяснимую ошибку."""
    try:
        return FILTERS[name]
    except (KeyError, TypeError):
        raise ValueError("Неизвестный видеофильтр: " + str(name)) from None
