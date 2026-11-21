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
    from signature_captions import split_groups
    groups = split_groups(words)
    # Начало смысловых коротких фраз + отчётливые паузы.
    starts = [float(group[0][0]) for group in groups if group]
    for previous, current in zip(words, words[1:]):
        if current[0] - previous[1] >= 0.38:
            starts.append(float(current[0]))
    candidates = sorted(x for x in set(starts) if 1.0 <= x <= duration - 1.7)
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


def editorial_zoom_expression(
    words: list[tuple[float, float, str]],
    duration: float,
    amplitude: float = 0.17,
) -> str:
    """Монтажная смена планов: приблизить и УДЕРЖИВАТЬ до следующей фразы.

    Старый алгоритм делал циклические переходы вперед-назад. Здесь камера
    один раз меняет крупность на границе выбранной фразы и остаётся на
    новом плане несколько секунд. Движение между планами занимает около
    0.36 с. Переходы чередуют общий и крупный план.
    """
    if duration < 1.5:
        return "1"
    from signature_captions import split_groups
    groups = split_groups(words)
    phrase_beginnings = sorted({
        max(0.0, float(g[0][0])) for g in groups if g
    })
    candidates = [t for t in phrase_beginnings if 0.55 <= t < duration - .6]
    if not candidates:
        candidates = [min(1.0, duration * .26)]
    selected: list[float] = []
    for t in candidates:
        if not selected or t - selected[-1] >= 3.25:
            selected.append(t)
        if len(selected) >= 24:
            break
    # Применяем smoothstep только к моменту смены плана.
    ramps: list[str] = []
    for idx, t in enumerate(selected):
        frame = round(t*30)
        x = f"max(0,min(1,(on-{frame})/11))"
        smooth = f"({x}*{x}*(3-2*{x}))"
        sign = "+" if idx % 2 == 0 else "-"
        ramps.append(f"{sign}{amplitude:.3f}*{smooth}")
    return "1"+"".join(ramps)


def side_pan_expressions(
    words: list[tuple[float, float, str]],
    duration: float,
) -> tuple[str, str]:
    """Eased left/right reframing with occasional held closeups.

    No random shaking and no repetitive sine oscillation. Transitions
    start on sentence boundaries; crop stays safely within frame.
    """
    from signature_captions import split_groups
    groups = split_groups(words)
    beginnings = sorted({
        float(g[0][0]) for g in groups if g and 0.7 < g[0][0] < duration - .5
    })
    changes: list[float] = []
    for t in beginnings:
        if not changes or t - changes[-1] >= 4.6:
            changes.append(t)
        if len(changes) >= 16:
            break
    if not changes and duration > 3:
        changes = [min(2.0, duration*.35)]
    ramps = []
    position = 0.0
    for index, t in enumerate(changes):
        # Center -> right -> left -> center, with ~1.2s soft transitions.
        target = (0.28, -0.28, 0.0)[index%3]
        delta = target - position
        position = target
        frame = round(t * 30)
        x = f"max(0,min(1,(on-{frame})/36))"
        smooth = f"({x}*{x}*(3-2*{x}))"
        ramps.append(f"{delta:+.3f}*{smooth}")
    pan_ratio = "0.5" + "".join(ramps)
    # Always keep a modest crop margin for side movements.
    # Cut to slightly closer shot on selected phrase boundaries.
    zoom = "1.16+1.05*(" + editorial_zoom_expression(words,duration,.16) + "-1)"
    return zoom, f"(iw-iw/zoom)*({pan_ratio})"


def add_virtual_camera(
    source: Path,
    output: Path,
    cadence: float,
    camera_style: str = "cinematic_pan",
    words: list[tuple[float, float, str]] | None = None,
    *,
    quality: str = "high",
    subtitles_ass: Path | None = None,
    intermediate: bool = False,
) -> None:
    """Smooth virtual camera with optional subtitle burn in SAME encode.

    cinematic_pan: sideways ease + held editorial closeups, no shakes.
    Other camera modes remain available for per-video selection.
    """
    from export_profiles import get_export_profile
    profile = get_export_profile(quality)
    if camera_style not in (
        "cinematic_pan","editorial","soft_punch","enhanced","gentle","off",
    ):
        raise ValueError("Неизвестный режим камеры.")
    if camera_style == "off":
        if subtitles_ass is not None:
            burn_subtitles(source, subtitles_ass, output, quality=quality)
        else:
            execute([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-i",str(source),"-map","0:v:0","-map","0:a:0?",
                "-c:v","copy","-c:a","copy","-movflags","+faststart",
                str(output),
            ])
        return
    x_expr = "(iw-iw/zoom)/2"
    if camera_style == "gentle":
        zoom = "min(1.025,1+on*0.00012)"
    elif camera_style == "cinematic_pan":
        duration, _ = duration_and_audio(source)
        zoom, x_expr = side_pan_expressions(words or [], duration)
    elif camera_style == "editorial":
        duration, _ = duration_and_audio(source)
        zoom = editorial_zoom_expression(words or [], duration, .17)
    elif words:
        duration, _ = duration_and_audio(source)
        windows = speech_zoom_windows(words, duration)
        amplitude = 0.20 if camera_style == "enhanced" else 0.16
        zoom = smooth_zoom_expression(windows, amplitude)
    else:
        if camera_style == "enhanced":
            p = "mod(on,270)"
            entrance = _smoothstep(p,12,27)
            exit_ = _smoothstep(p,173,30)
            zoom = f"1+0.18*({entrance}-{exit_})"
        else:
            p = "mod(on,390)"
            entrance = _smoothstep(p,24,24)
            exit_ = _smoothstep(p,211,30)
            zoom = f"1+0.11*({entrance}-{exit_})"

    vf = (
        f"scale={profile.expanded_dimensions}:flags=lanczos,"
        "setsar=1,fps=30,"
        f"zoompan=z='{zoom}':"
        f"x='{x_expr}':y='(ih-ih/zoom)/2':"
        f"d=1:s={profile.zoom_size}:fps=30,format=yuv420p"
    )
    if subtitles_ass is not None:
        # Prevent another lossy video-generation pass for subtitle rendering.
        vf += f",ass={subtitles_ass}"
    execute([
        "ffmpeg","-hide_banner","-loglevel","error","-y",
        "-i",str(source),"-vf",vf,
        "-map","0:v:0","-map","0:a:0?",
        "-c:v","libx264","-preset",profile.preset,
        "-crf",str(min(14, profile.crf) if intermediate else profile.crf),
        "-pix_fmt","yuv420p",
        "-c:a","copy","-movflags","+faststart",str(output),
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
    caption_animation: str = "word_pop",
    sound_effects: str = "off",
    emoji_mode: str = "off",
    hook_position: str = "start",
    quality: str = "high",
    subtitle_delay: float = 0.30,
    small_font_profile: str = "modern",
    caption_variant: str = "editorial",
    background_style: str = "occasional",
    animation_style: str = "float",
    subtitle_sfx: str = "off",
    insert_style: str = "off",
    insert_density: str = "balanced",
    insert_sound: str = "on",
    private_assets = None,
    top_title: str = "",
    top_title_mode: str = "auto",
    pause_removal: str = "tight",
    subject_layout: str = "standard",
    talk_scene: str = "off",
) -> dict:
    """Монтаж с точной синхронизацией речи, динамичным кадром и титрами."""
    from reels_effects import apply_effects, validate_effects
    validate_effects(sound_effects, emoji_mode, hook_position)
    from portrait_caption_layer import check_layout, choose_text_side, protect_subject
    subject_layout = check_layout(subject_layout)
    from talking_scene_styles import validate_talk_scene, render_scene, append_scene_ornaments
    talk_scene = validate_talk_scene(talk_scene)
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
    # Remove awkward gaps BEFORE camera, text and time remapping; the
    # word timestamps are mapped through the same edit decision.
    from telegram_editor import get_speech_keep_ranges,get_keep_ranges
    kept = (get_speech_keep_ranges(words_override,source_duration,pause_removal)
            if words_override is not None
            else get_keep_ranges(original,source_duration,source_has_audio))
    with tempfile.TemporaryDirectory(prefix="reference_render_") as tmp:
        folder = Path(tmp)
        joined = folder / "joined.mp4"
        dynamic = folder / "dynamic.mp4"
        subtitles = folder / "subtitles.ass"
        subtitled = folder / "subtitled.mp4"  # legacy intermediary; no longer encoded
        base_video(
            original, joined, kept, source_has_audio,
            audio_profile=audio_profile, speed=speed, filter_style=filter_style,
            quality=quality, intermediate=True,
        )
        from speech_review import map_words_to_ranges, shift_word_timestamps
        from telegram_editor import transcribe_words

        if words_override is not None:
            words = map_words_to_ranges(words_override, kept, speed)
        else:
            words = transcribe_words(joined)
        # Добавляем небольшую задержку самих титров: надписи не обгоняют
        # голос. Скорость исходного видео и речи остаётся равной 1.0.
        joined_duration, _ = duration_and_audio(joined)
        words = shift_word_timestamps(words, subtitle_delay, joined_duration)
        subject_side = choose_text_side(joined) if talk_scene == "off" and subject_layout == "beside" else "center"
        # Render title timings from the joined timeline, then burn those
        # titles while making the actual camera move (one less lossy pass).
        count = write_ass(
            joined, subtitles, color, style=subtitle_style, hook=hook,
            caption_position="studio" if talk_scene!="off" else caption_position,
            font_profile=font_profile,
            words_override=words,
            caption_animation=caption_animation,
            hook_position=hook_position,
            small_font_profile=small_font_profile,
            caption_variant=caption_variant,
            background_style=background_style,
            animation_style=animation_style,
            top_title=top_title, top_title_mode=top_title_mode,
            subject_side=subject_side,
        )
        if talk_scene != "off":
            # The title treatment belongs to a separate designed canvas.
            # Existing camera effects remain inside its arched video window.
            clean_camera = folder / "talk_camera.mp4"
            studio_clean = folder / "talk_canvas.mp4"
            add_virtual_camera(
                joined, clean_camera, profile.seconds_per_change,
                camera_style=camera_style, words=words, quality=quality,
                subtitles_ass=None, intermediate=True,
            )
            render_scene(clean_camera, studio_clean, talk_scene, quality=quality)
            if count:
                append_scene_ornaments(subtitles,words,talk_scene)
                burn_subtitles(studio_clean, subtitles, dynamic, quality=quality)
            else:
                studio_clean.replace(dynamic)
        else:
            add_virtual_camera(
                joined, dynamic, profile.seconds_per_change,
                camera_style=camera_style, words=words,
                quality=quality, subtitles_ass=subtitles if count else None,
                intermediate=(emoji_mode == "on" or subject_layout != "standard"),
            )
            if count and subject_layout != "standard":
                # Camera moves must be identical in the uncaptioned foreground
                # and captioned image, or the person would leave ghost outlines.
                clean_camera = folder / "camera_without_captions.mp4"
                protected = folder / "captions_behind_subject.mp4"
                add_virtual_camera(
                    joined, clean_camera, profile.seconds_per_change,
                    camera_style=camera_style, words=words, quality=quality,
                    subtitles_ass=None, intermediate=True,
                )
                protect_subject(clean_camera, dynamic, protected, quality=quality)
                dynamic = protected
        effect_stats = apply_effects(
            dynamic, output, words,
            sound=sound_effects, emoji=emoji_mode,
            caption_position=caption_position, quality=quality,
            caption_sound=subtitle_sfx,
            insert_style=insert_style, insert_density=insert_density,
            insert_sound=insert_sound,
            private_assets=private_assets,
            font_profile=font_profile, small_font_profile=small_font_profile,
            animation_style=animation_style,
        )
    return {
        "before": round(source_duration, 1),
        "after": round(sum(s.end - s.start for s in kept) / speed, 1),
        "subtitle_events": count,
        "subtitle_delay": round(subtitle_delay, 2),
        **effect_stats,
        "reference_scene_changes": profile.scene_changes,
        "reference_pace_seconds": profile.seconds_per_change,
        "reference_dynamics": profile.dynamics,
    }
