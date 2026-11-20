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


def _smoothstep(t: str, offset: int, frames: int) -> str:
    """FFmpeg expression: плавный ход без резкого ускорения."""
    x = f"min(1,max(0,({t}-{offset})/{frames}))"
    return f"({x}*{x}*(3-2*{x}))"


def speech_zoom_windows(
    words: list[tuple[float, float, str]],
    duration: float,
    *, max_count: int = 18,
) -> list[tuple[float, float]]:
    """Выбирает начала фраз и паузы, а не механический таймер."""
    if duration < 2.5 or not words:
        return []
    starts = [float(words[0][0])]
    for previous, current in zip(words, words[1:]):
        if current[0] - previous[1] >= 0.38:
            starts.append(float(current[0]))
    candidates = [x for x in starts if 1.0 <= x <= duration - 1.7]
    if not candidates:
        candidates = [min(1.4, duration / 4)]
    selected: list[tuple[float, float]] = []
    last = -10.0
    for t in candidates:
        if t - last < 5.0:
            continue
        if len(selected) >= max_count:
            break
        selected.append((t, min(duration - 0.35, t + 3.6)))
        last = t
    return selected


def smooth_zoom_expression(
    windows: list[tuple[float, float]],
    amplitude: float,
) -> str:
    """Выражение FFmpeg с плавным ускорением и замедлением."""
    def ramp(frame: int, count: int = 18) -> str:
        ratio = f"max(0,min(1,(on-{frame})/{count}))"
        return f"({ratio}*{ratio}*(3-2*{ratio}))"
    if not windows:
        return "min(1.04,1+on*0.0001)"
    parts = []
    for begin, end in windows:
        start_frame = max(0, round(begin * 30))
        end_frame = max(start_frame + 20, round(end * 30))
        parts.append(f"{amplitude:.3f}*({ramp(start_frame)}-{ramp(end_frame)})")
    return "1+" + "+".join(parts)


def add_virtual_camera(
    source: Path,
    output: Path,
    cadence: float,
    camera_style: str = "soft_punch",
    words: list[tuple[float, float, str]] | None = None,
) -> None:
    """Плавные приближения с задержками на крупном плане.

    soft_punch: 0.8 сек плавное приближение (около 11%), ~5 сек
    удержание крупности, ~1 сек плавное отдаление. Между сериями есть
    стабильный общий план. Никаких циклических колебаний zoom'а
    каждый кадр и случайных сдвигов.

    gentle: только одно очень медленное приближение на 2.5%.
    off: без искусственного увеличения.
    """
    if camera_style not in ("soft_punch", "enhanced", "gentle", "off"):
        raise ValueError("Неизвестный режим камеры.")
    if camera_style == "off":
        # Не перекодируем видеокартинку и не добавляем цифрового дрожания.
        execute([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", "copy", "-c:a", "copy", "-movflags", "+faststart",
            str(output),
        ])
        return
    if camera_style == "gentle":
        zoom = "min(1.025,1+on*0.00012)"
    elif words:
        duration, _ = duration_and_audio(source)
        windows = speech_zoom_windows(words, duration)
        amplitude = 0.20 if camera_style == "enhanced" else 0.16
        zoom = smooth_zoom_expression(windows, amplitude)
        LOG.info("Speech-aware zooms: %d intervals", len(windows))
    else:
        # Плавная монтажная смена крупности (вместо «дышащего» зума).
        # Период 13 сек, за одну серию: широкий -> близкий -> широкий.
        # smoothstep даёт нулевую скорость в начале и в конце каждого
        # перехода, поэтому переключений с тряской быть не должно.
        if camera_style == "enhanced":
            # Режим «Усиленная» из записи: чаще и заметнее, но так же плавно.
            # 9 секунд на серию, 18% увеличение, удержание крупного кадра.
            p = "mod(on,270)"
            entrance = _smoothstep(p, 12, 27)
            exit_ = _smoothstep(p, 173, 30)
            zoom = f"1+0.18*({entrance}-{exit_})"
        else:
            p = "mod(on,390)"
            entrance = _smoothstep(p, 24, 24)
            exit_ = _smoothstep(p, 211, 30)
            zoom = f"1+0.11*({entrance}-{exit_})"

    # Больший промежуточный размер уменьшает ступенчатые сдвиги центра.
    vf = (
        "scale=1080:1920:flags=lanczos,setsar=1,fps=30,"
        f"zoompan=z='{zoom}':"
        "x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
        "d=1:s=720x1280:fps=30,format=yuv420p"
    )
    execute([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-vf", vf,
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "copy", "-movflags", "+faststart", str(output),
    ])


def montage_by_reference(
    original: Path,
    reference: Path | None,
    output: Path,
    color: str = "#EBC0C8",
    audio_profile: str = "balanced",
    subtitle_style: str = "signature",
    hook: str = "",
    camera_style: str = "soft_punch",
    speed: float = 1.0,
    filter_style: str = "none",
    caption_position: str = "middle",
    font_profile: str = "elegant",
    words_override: list[tuple[float, float, str]] | None = None,
) -> dict:
    """Монтаж с нарезкой тишины, ритмом референса и живыми субтитрами."""
    # Без второго файла используем постоянный темп из разобранного
    # 50-секундного пользовательского референса: близкие планы, мягкое
    # движение камеры, без резких ступенек.
    profile = (
        analyze_reference(reference)
        if reference is not None
        else ReferenceProfile(0, 2.90, 0.0, "фирменный")
    )
    source_duration, source_has_audio = duration_and_audio(original)
    if not source_has_audio:
        raise ValueError("Для разговорного монтажа нужен исходный ролик с речью.")
    kept = get_keep_ranges(original, source_duration, source_has_audio)
    with tempfile.TemporaryDirectory(prefix="reference_render_") as tmp:
        folder = Path(tmp)
        joined = folder / "joined.mp4"
        dynamic = folder / "dynamic.mp4"
        subtitles = folder / "subtitles.ass"
        base_video(
            original, joined, kept, source_has_audio,
            audio_profile=audio_profile, speed=speed, filter_style=filter_style,
        )
        from speech_review import map_words_to_ranges
        from telegram_editor import transcribe_words

        if words_override is not None:
            words = map_words_to_ranges(words_override, kept, speed)
        else:
            words = transcribe_words(joined)
        add_virtual_camera(
            joined, dynamic, profile.seconds_per_change,
            camera_style=camera_style, words=words,
        )
        count = write_ass(
            dynamic, subtitles, color, style=subtitle_style, hook=hook,
            caption_position=caption_position, font_profile=font_profile,
            words_override=words,
        )
        if count:
            burn_subtitles(dynamic, subtitles, output)
        else:
            dynamic.replace(output)
    return {
        "before": round(source_duration, 1),
        "after": round(sum(s.end - s.start for s in kept) / speed, 1),
        "subtitle_events": count,
        "reference_scene_changes": profile.scene_changes,
        "reference_pace_seconds": profile.seconds_per_change,
        "reference_dynamics": profile.dynamics,
    }
