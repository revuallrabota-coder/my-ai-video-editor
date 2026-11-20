"""Первый честный режим «по референсу» для Telegram-бота.

Что реально измеряем: приблизительный ритм заметных смен кадров
(по FFmpeg scene detection). К исходнику применяем соответствующий темп
виртуальных переплановок камеры. Удаляем длинную тишину, сохраняем речь,
генерируем субтитры без платных API.

Чего НЕ делаем: не копируем 1:1 эффекты, B-roll, графику и шрифты
из произвольного видео. Для этого понадобится отдельный AI-анализ.
"""
from __future__ import annotations

import logging
import math
import re
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path

from telegram_editor import (
    base_video,
    burn_subtitles,
    duration_and_audio,
    execute,
    get_keep_ranges,
    write_ass,
)

LOG = logging.getLogger("reference_editor")
REFERENCE_MAX_SECONDS = 125
ANALYSIS_SECONDS = 75
MIN_PERIOD = 0.9
MAX_PERIOD = 4.5


@dataclass(frozen=True)
class ReferenceProfile:
    scene_changes: int
    seconds_per_change: float
    sample_seconds: float
    dynamics: str


def analyze_reference(path: Path) -> ReferenceProfile:
    """Грубая оценка скорости смены планов, не распознавание стиля текста."""
    duration, _ = duration_and_audio(path)
    sample = min(duration, ANALYSIS_SECONDS)
    # Сначала уменьшаем разрешение и частоту кадров, чтобы не нагружать CPU.
    # showinfo пишет таймкоды только на выбранных кадрах.
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "info",
        "-i", str(path), "-t", f"{sample:.3f}",
        "-vf", "fps=4,scale=320:-2,select='gt(scene,0.27)',showinfo",
        "-an", "-f", "null", "-",
    ]
    process = execute(command, allow_failure=True)
    if process.returncode != 0:
        LOG.warning("Не удалось оценить смены кадров: используем безопасный темп.")
        return ReferenceProfile(0, 2.5, sample, "стандартный")

    timestamps: list[float] = []
    for line in process.stderr.splitlines():
        if "showinfo" not in line or "pts_time:" not in line:
            continue
        match = re.search(r"pts_time:\s*([0-9.]+)", line)
        if not match:
            continue
        value = float(match.group(1))
        if 0.2 <= value <= sample:
            timestamps.append(value)

    # Не считать мерцание за отдельные «склейки».
    moments: list[float] = []
    for timestamp in sorted(timestamps):
        if not moments or timestamp - moments[-1] >= 0.42:
            moments.append(timestamp)

    if len(moments) >= 2:
        intervals = [b - a for a, b in zip(moments, moments[1:])]
        cadence = statistics.median(intervals)
    elif len(moments) == 1:
        cadence = sample / 2
    else:
        cadence = 2.5

    cadence = max(MIN_PERIOD, min(MAX_PERIOD, cadence))
    dynamics = "быстрый" if cadence < 1.5 else "спокойный" if cadence > 3.4 else "средний"
    return ReferenceProfile(
        scene_changes=len(moments),
        seconds_per_change=round(cadence, 2),
        sample_seconds=round(sample, 2),
        dynamics=dynamics,
    )


def add_virtual_camera(source: Path, output: Path, cadence: float) -> None:
    """Непрерывное мягкое приближение-отдаление в темпе референса.

    Добавляет аккуратное движение камеры без резких скачков
    и без изменения последовательности речи и кадров.
    """
    # Плавный, непрерывный зум: в отличие от старого ступенчатого
    # переключения, косинусная огибающая имеет нулевую скорость
    # в начале и конце каждого приближения.
    #
    # Амплитуда намеренно небольшая: для лица, рук и маникюра
    # агрессивный зум выглядит нервно.
    period = max(45, min(165, int(round(30 * cadence * 1.6))))
    amplitude = 0.065 if cadence < 1.6 else 0.050 if cadence < 3.0 else 0.040
    zoom = f"1.02+{amplitude:.3f}*(1-cos(2*PI*on/{period}))/2"
    vf = (
        "scale=900:1600,setsar=1,fps=30,"
        f"zoompan=z='{zoom}':"
        "x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
        "d=1:s=720x1280:fps=30,"
        "format=yuv420p"
    )
    execute([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-vf", vf,
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "copy", "-movflags", "+faststart", str(output),
    ])


def montage_by_reference(
    original: Path,
    reference: Path,
    output: Path,
    color: str = "#EBC0C8",
    audio_profile: str = "balanced",
    subtitle_style: str = "signature",
    hook: str = "",
) -> dict:
    """Монтаж с нарезкой тишины, ритмом референса и живыми субтитрами."""
    profile = analyze_reference(reference)
    source_duration, source_has_audio = duration_and_audio(original)
    if not source_has_audio:
        raise ValueError("Для разговорного монтажа нужен исходный ролик с речью.")
    kept = get_keep_ranges(original, source_duration, source_has_audio)
    with tempfile.TemporaryDirectory(prefix="reference_render_") as tmp:
        folder = Path(tmp)
        joined = folder / "joined.mp4"
        dynamic = folder / "dynamic.mp4"
        subtitles = folder / "subtitles.ass"
        base_video(original, joined, kept, source_has_audio, audio_profile=audio_profile)
        add_virtual_camera(joined, dynamic, profile.seconds_per_change)
        count = write_ass(dynamic, subtitles, color, style=subtitle_style, hook=hook)
        if count:
            burn_subtitles(dynamic, subtitles, output)
        else:
            dynamic.replace(output)
    return {
        "before": round(source_duration, 1),
        "after": round(sum(s.end - s.start for s in kept), 1),
        "subtitle_events": count,
        "reference_scene_changes": profile.scene_changes,
        "reference_pace_seconds": profile.seconds_per_change,
        "reference_dynamics": profile.dynamics,
    }
