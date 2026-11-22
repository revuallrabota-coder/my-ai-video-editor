"""Единые профили экспорта: Full HD без обязательного понижения до 720p.

Качество не восстанавливает детали, отсутствующие в исходнике. В
платформенном прототипе по умолчанию HQ 1080x1920; более лёгкий 720p
можно выбрать на слабом сервере.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExportProfile:
    name: str
    width: int
    height: int
    crf: int
    preset: str
    audio_bitrate: str = "192k"

    @property
    def dimensions(self) -> str:
        return f"{self.width}:{self.height}"

    @property
    def zoom_size(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def expanded_dimensions(self) -> str:
        return f"{self.width * 4 // 3}:{self.height * 4 // 3}"


PROFILES = {
    "high": ExportProfile("high", 1080, 1920, 16, "fast"),
    "balanced": ExportProfile("balanced", 720, 1280, 20, "fast", "160k"),
}


def get_export_profile(name: str = "high") -> ExportProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError("Экспорт: high (1080p) или balanced (720p).") from exc
