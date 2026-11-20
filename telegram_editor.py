"""Одноразовый Telegram-видеомонтажёр для GitHub Actions.

Workflow запускается вручную. После появления запущенного задания
владелец отправляет видео в чат с ботом. Видео обрабатывается один раз,
результат возвращается в тот же чат, после чего программа завершается.

Секреты загружаются только из переменных окружения GitHub Actions.
Никаких токенов и видео в Git-репозиторий не записывается.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from telethon import TelegramClient, events


LOG = logging.getLogger("editor")
MAX_BYTES = 1024 * 1024 * 1024  # 1 GiB
MAX_SECONDS = 125  # допуск к номинальным 2 минутам
WAIT_SECONDS = 900
SIZE = "720:1280"  # тестовая версия: разумный размер для бесплатного CPU
DEFAULT_COLOR = "#E8A0C0"


@dataclass
class Segment:
    start: float
    end: float


def execute(command: Sequence[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess:
    process = subprocess.run(
        list(command), capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if process.returncode != 0 and not allow_failure:
        # Не показываем пользователю внутренние аргументы команд или секреты.
        raise RuntimeError("Не удалось обработать видеодорожку. Подробности есть в журнале задания.")
    return process


def media_info(path: Path) -> dict:
    result = execute([
        "ffprobe", "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(path),
    ])
    return json.loads(result.stdout)


def duration_and_audio(path: Path) -> tuple[float, bool]:
    data = media_info(path)
    duration = float(data.get("format", {}).get("duration", 0))
    has_video = any(s.get("codec_type") == "video" for s in data.get("streams", []))
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    if not has_video or duration <= 0:
        raise ValueError("В файле не найдена корректная видеодорожка.")
    if duration > MAX_SECONDS:
        raise ValueError("Пока обрабатываются ролики не длиннее 2 минут.")
    return duration, has_audio


def parse_silences(stderr: str, duration: float) -> list[Segment]:
    gaps: list[Segment] = []
    start = None
    for line in stderr.splitlines():
        match_start = re.search(r"silence_start:\s*([0-9.]+)", line)
        if match_start:
            start = float(match_start.group(1))
        match_end = re.search(r"silence_end:\s*([0-9.]+)", line)
        if match_end and start is not None:
            end = float(match_end.group(1))
            if end - start >= 0.65:
                gaps.append(Segment(max(0.0, start), min(duration, end)))
            start = None
    if start is not None:
        gaps.append(Segment(max(0.0, start), duration))
    return gaps


def ranges_to_keep(silences: list[Segment], duration: float) -> list[Segment]:
    """Убирает только длительные тихие промежутки, с запасом для дыхания."""
    removed: list[Segment] = []
    for gap in silences:
        a = max(0.0, gap.start + 0.18)
        b = min(duration, gap.end - 0.18)
        if b - a >= 0.35:
            removed.append(Segment(a, b))
    removed.sort(key=lambda s: s.start)
    kept: list[Segment] = []
    cursor = 0.0
    for gap in removed:
        if gap.start > cursor + 0.28:
            kept.append(Segment(cursor, gap.start))
        cursor = max(cursor, gap.end)
    if duration - cursor > 0.28:
        kept.append(Segment(cursor, duration))
    if not kept:
        return [Segment(0.0, duration)]
    kept_duration = sum(x.end - x.start for x in kept)
    # Если распознавание тишины ошибочно сочло почти всё видео тишиной,
    # не превращаем исходное выступление в пару секунд.
    if kept_duration < duration * 0.35 or len(kept) > 85:
        return [Segment(0.0, duration)]
    return kept


def get_keep_ranges(path: Path, duration: float, has_audio: bool) -> list[Segment]:
    if not has_audio:
        return [Segment(0.0, duration)]
    result = execute([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-vn", "-af", "silencedetect=noise=-32dB:d=0.65",
        "-f", "null", "-",
    ], allow_failure=True)
    return ranges_to_keep(parse_silences(result.stderr, duration), duration)


def audio_filterchain(profile: str) -> str:
    """Без платных API: чистка фона, сглаживание скачков и громкость речи.

    balanced — бережно, по умолчанию; strong — более агрессивно;
    off — пропуск любых эффектов (сохранение оригинальной дорожки).
    """
    if profile == "off":
        return ""
    if profile == "balanced":
        return (
            "highpass=f=85,lowpass=f=13500,"
            "afftdn=nr=12:nf=-38:tn=1,"
            "acompressor=threshold=0.1:ratio=2:attack=15:release=180:makeup=1,"
            "loudnorm=I=-16:TP=-1.5:LRA=11"
        )
    if profile == "strong":
        return (
            "highpass=f=95,lowpass=f=12000,"
            "afftdn=nr=20:nf=-35:tn=1,"
            "acompressor=threshold=0.08:ratio=2.6:attack=12:release=210:makeup=1,"
            "loudnorm=I=-16:TP=-1.5:LRA=11"
        )
    raise ValueError("Неизвестный режим улучшения звука.")


def base_video(
    path: Path, output: Path, ranges: list[Segment], has_audio: bool,
    audio_profile: str = "balanced",
    speed: float = 1.0,
    filter_style: str = "none",
) -> None:
    """Собрать видео, реально применяя скорость, цвет и очистку речи."""
    if not 0.8 <= speed <= 1.5:
        raise ValueError("Скорость должна быть от 0.8 до 1.5.")
    if filter_style not in ("none", "warm"):
        raise ValueError("Поддерживаются только фильтры none и warm.")

    filters: list[str] = []
    concat_inputs = ""
    for idx, fragment in enumerate(ranges):
        a, b = fragment.start, fragment.end
        filters.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{idx}]")
        concat_inputs += f"[v{idx}]"
        if has_audio:
            filters.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{idx}]")
            concat_inputs += f"[a{idx}]"

    if has_audio:
        filters.append(f"{concat_inputs}concat=n={len(ranges)}:v=1:a=1[vjoined][ajoined]")
    else:
        filters.append(f"{concat_inputs}concat=n={len(ranges)}:v=1:a=0[vjoined]")

    video_source = "[vjoined]"
    audio_source = "[ajoined]"
    if abs(speed - 1.0) > 0.001:
        filters.append(f"{video_source}setpts=(PTS-STARTPTS)/{speed:.3f}[vtempo]")
        video_source = "[vtempo]"
        if has_audio:
            filters.append(f"{audio_source}atempo={speed:.3f}[atempo]")
            audio_source = "[atempo]"

    if has_audio:
        sound_filters = audio_filterchain(audio_profile)
        if sound_filters:
            filters.append(f"{audio_source}{sound_filters}[aclean]")
            audio_source = "[aclean]"

    video_filters = (
        "scale=720:1280:force_original_aspect_ratio=decrease,"
        "pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=0x1a1426,"
        "setsar=1,fps=30"
    )
    if filter_style == "warm":
        # Умеренный тёплый тон, без агрессивного изменения оттенка кожи.
        video_filters += ",colorbalance=rs=0.045:gs=0.005:bs=-0.025"
    video_filters += ",format=yuv420p"
    filters.append(f"{video_source}{video_filters}[vout]")

    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(path), "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "22", "-pix_fmt", "yuv420p",
    ]
    if has_audio:
        args.extend(["-map", audio_source, "-c:a", "aac", "-b:a", "160k"])
    else:
        args.append("-an")
    args.extend(["-movflags", "+faststart", str(output)])
    execute(args)


def ass_time(seconds: float) -> str:
    centiseconds = max(0, int(seconds * 100))
    hours, rem = divmod(centiseconds, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{cs:02}"


def clean_ass_text(word: str) -> str:
    # Не даём тексту речи превратиться в управляющие ASS-теги.
    return word.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def ass_color(hex_color: str) -> str:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", hex_color):
        hex_color = DEFAULT_COLOR
    rgb = hex_color[1:]
    return f"&H{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}&".upper()


def transcribe_words(
    video_path: Path,
    model_size: str = "small",
    language: str = "ru",
) -> list[tuple[float, float, str]]:
    """Более точная расшифровка речи для предварительной проверки.

    В отличие от старой base-модели: small/medium, подсказка русского
    языка и предварительная очистка аудио перед распознаванием.
    Только локальное распознавание: никаких внешних платных API.
    """
    from functools import lru_cache
    from faster_whisper import WhisperModel

    if model_size not in ("small", "medium"):
        raise ValueError("Поддерживаются модели small и medium.")
    if language not in ("ru", "auto"):
        raise ValueError("Язык может быть ru или auto.")

    @lru_cache(maxsize=2)
    def load_model(name: str):
        return WhisperModel(name, device="cpu", compute_type="int8")

    duration, has_audio = duration_and_audio(video_path)
    if not has_audio:
        return []

    with tempfile.TemporaryDirectory(prefix="recognition_") as tmp:
        cleaned = Path(tmp) / "speech.wav"
        # Для распознавания используем очищенную дорожку, но
        # исходная речь в готовом видео сохраняется, не заменяется.
        execute([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000",
            "-af", "highpass=f=80,lowpass=f=7500,afftdn=nr=10:nf=-40",
            "-c:a", "pcm_s16le", str(cleaned),
        ])
        LOG.info("Whisper %s, язык=%s: распознавание речи", model_size, language)
        model = load_model(model_size)
        segments, info = model.transcribe(
            str(cleaned),
            language=None if language == "auto" else language,
            beam_size=5,
            best_of=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 450},
            word_timestamps=True,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
        )
        result: list[tuple[float, float, str]] = []
        for segment in segments:
            if segment.words:
                for token in segment.words:
                    word = clean_ass_text(token.word)
                    if word and token.end > token.start:
                        result.append((float(token.start),float(token.end),word))
            elif segment.text.strip():
                result.append((float(segment.start),float(segment.end),clean_ass_text(segment.text)))
        # Убираем явные дубли по почти одинаковым временным отметкам.
        deduplicated = []
        for item in result:
            if deduplicated and abs(item[0]-deduplicated[-1][0]) < 0.035 and item[2] == deduplicated[-1][2]:
                continue
            deduplicated.append(item)
        LOG.info("Распознано слов/фраз: %d", len(deduplicated))
        return deduplicated


def write_ass(
    video_path: Path, output_ass: Path, color: str,
    style: str = "signature", hook: str = "",
    caption_position: str = "middle", font_profile: str = "elegant",
    words_override: list[tuple[float, float, str]] | None = None,
    caption_animation: str = "word_pop",
    hook_position: str = "start",
) -> int:
    words = words_override if words_override is not None else transcribe_words(video_path)
    from reels_effects import add_hook_to_ass

    def save_subtitles(content: str) -> int:
        seconds, _ = duration_and_audio(video_path)
        accent_color = (
            "#F0443E" if style == "contrast" and color == "auto" else
            "#FFFFFF" if style == "classic" and color == "auto" else color
        )
        complete = add_hook_to_ass(
            content, hook, position=hook_position, duration=seconds,
            color=accent_color, font_profile=font_profile,
        )
        output_ass.write_text(complete, encoding="utf-8")
        return sum(line.startswith("Dialogue: ") for line in complete.splitlines())


    if caption_animation == "word_pop":
        from word_captions import build_word_pop_ass
        content, count = build_word_pop_ass(
            words, style=style, color=color, hook="",
            caption_position=caption_position, font_profile=font_profile,
        )
        return save_subtitles(content)
    if caption_animation != "phrase_float":
        raise ValueError("Неизвестная анимация субтитров.")

    if style == "signature":
        from signature_captions import build_signature_ass
        content, count = build_signature_ass(
            words, color=color, hook="",
            caption_position=caption_position, font_profile=font_profile,
        )
        return save_subtitles(content)
    if style == "contrast":
        from contrast_captions import build_contrast_ass
        content, count = build_contrast_ass(
            words, hook="", accent_color=color,
            caption_position=caption_position, font_profile=font_profile,
        )
        return save_subtitles(content)
    if style != "classic":
        raise ValueError("Неизвестный стиль субтитров.")

    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Main,DejaVu Sans,50,&H00FFFFFF,&H000000FF,"
        "&H002C1739,&H80000000,1,0,0,0,100,100,0,0,1,3,2,2,55,55,235,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    active_color = ass_color(color)
    events = []
    groups = []
    group = []
    for word in words:
        if group and (len(group) >= 4 or word[1] - group[0][0] > 2.2
                      or sum(len(w[2]) for w in group) > 23):
            groups.append(group)
            group = []
        group.append(word)
    if group:
        groups.append(group)

    for group in groups:
        for idx, (start, end, word) in enumerate(group):
            next_start = group[idx+1][0] if idx+1 < len(group) else group[-1][1]
            shown_until = max(end, next_start)
            if shown_until <= start:
                continue
            text = []
            for j, (_, _, token) in enumerate(group):
                if j == idx:
                    text.append(r"{\c" + active_color + r"\fscx110\fscy110}" + token + r"{\r}")
                else:
                    text.append(token)
            line = " ".join(text)
            events.append(
                f"Dialogue: 0,{ass_time(start)},{ass_time(shown_until)},"
                f"Main,,0,0,0,,{line}\n"
            )
    return save_subtitles(header + "".join(events))


def burn_subtitles(input_path: Path, ass_path: Path, output_path: Path) -> None:
    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_path), "-vf", f"ass={ass_path}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p", "-c:a", "copy",
        "-movflags", "+faststart", str(output_path),
    ]
    execute(args)


def edit_video(
    original: Path, output: Path, mode: str, color: str,
    audio_profile: str = "balanced",
    subtitle_style: str = "signature",
    hook: str = "",
    speed: float = 1.0,
    filter_style: str = "none",
    caption_position: str = "middle",
    font_profile: str = "elegant",
    words_override: list[tuple[float, float, str]] | None = None,
    caption_animation: str = "word_pop",
    sound_effects: str = "off",
    emoji_mode: str = "off",
    hook_position: str = "start",
) -> dict:
    from reels_effects import apply_effects, validate_effects
    from speech_review import map_words_to_ranges
    validate_effects(sound_effects, emoji_mode, hook_position)

    duration, has_audio = duration_and_audio(original)
    ranges = ([Segment(0.0, duration)] if mode == "captions"
              else get_keep_ranges(original, duration, has_audio))
    with tempfile.TemporaryDirectory(prefix="editor_") as directory:
        folder=Path(directory)
        work = folder / "joined.mp4"
        staged = folder / "with_subtitles.mp4"
        base_video(
            original, work, ranges, has_audio,
            audio_profile=audio_profile, speed=speed, filter_style=filter_style,
        )
        words = (
            map_words_to_ranges(words_override, ranges, speed)
            if words_override is not None else
            (transcribe_words(work) if has_audio and mode != "cuts" else [])
        )
        subtitle_events = 0
        if mode != "cuts" and has_audio:
            ass = folder / "captions.ass"
            subtitle_events = write_ass(
                work, ass, color, style=subtitle_style, hook=hook,
                caption_position=caption_position, font_profile=font_profile,
                words_override=words, caption_animation=caption_animation,
                hook_position=hook_position,
            )
            if subtitle_events:
                burn_subtitles(work, ass, staged)
            else:
                work.replace(staged)
        else:
            work.replace(staged)

        # Звуковые акценты и эмодзи накладываются только после одобрения
        # слов, чтобы не менять тайминги подписи и не заглушить речь.
        effect_stats=apply_effects(
            staged, output, words,
            sound=sound_effects, emoji=emoji_mode,
            caption_position=caption_position,
        )
    return {
        "before": round(duration, 1),
        "after": round(sum(s.end-s.start for s in ranges) / speed, 1),
        "subtitle_events": subtitle_events,
        **effect_stats,
    }

async def main() -> None:
    required = ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_BOT_TOKEN", "OWNER_TELEGRAM_ID"]
    if any(not os.environ.get(k) for k in required):
        raise RuntimeError(
            "Нужны четыре секрета GitHub Actions: "
            + ", ".join(k for k in required if not os.environ.get(k))
        )
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    owner_id = int(os.environ["OWNER_TELEGRAM_ID"])
    mode = os.environ.get("MONTAGE_MODE", "auto")
    color = os.environ.get("SUBTITLE_COLOR", DEFAULT_COLOR)
    audio_profile = os.environ.get("AUDIO_PROFILE", "balanced")
    audio_filterchain(audio_profile)  # early validation
    subtitle_style = os.environ.get("SUBTITLE_STYLE", "signature")
    if subtitle_style not in ("signature", "classic", "contrast"):
        raise ValueError("Неверный стиль субтитров.")
    hook = os.environ.get("HOOK_TEXT", "").strip()[:70]
    if mode not in ("auto", "captions", "cuts"):
        raise ValueError("Неподдерживаемый режим.")
    done = asyncio.Event()
    busy = False

    client = TelegramClient("telegram_editor_session", api_id, api_hash)
    await client.start(bot_token=token)
    try:
        LOG.info("Бот подключён. Ожидание нового видео владельца (%s секунд).", WAIT_SECONDS)

        @client.on(events.NewMessage(incoming=True))
        async def on_message(event):
            nonlocal busy
            if event.sender_id != owner_id or not event.is_private:
                return
            if event.raw_text and event.raw_text.strip().lower() in ("/start", "/help"):
                await event.respond(
                    "🎬 Чтобы смонтировать ролик, сначала запусти задание "
                    "«Монтаж через Telegram» в GitHub Actions. "
                    "Затем пришли сюда видео до 1 ГБ и длительностью до 2 минут."
                )
                return
            if busy or not event.file:
                return
            mime = (event.file.mime_type or "").lower()
            if not (mime.startswith("video/") or (event.file.name or "").lower().endswith((".mov",".mp4",".m4v"))):
                await event.respond("Пожалуйста, пришли видео MP4 или MOV.")
                return
            if event.file.size and event.file.size > MAX_BYTES:
                await event.respond("Видео больше 1 ГБ. Пришли файл поменьше.")
                return
            busy = True
            try:
                await event.respond("📥 Видео получено, загружаю и начинаю монтаж…")
                with tempfile.TemporaryDirectory(prefix="telegram_video_") as directory:
                    folder = Path(directory)
                    original = folder / ("source.mov" if "quicktime" in mime else "source.mp4")
                    result = folder / "reels_ready.mp4"
                    downloaded = await event.download_media(file=str(original))
                    if not downloaded or not original.exists():
                        raise RuntimeError("Telegram не передал исходный файл.")
                    if original.stat().st_size > MAX_BYTES:
                        raise ValueError("Файл больше 1 ГБ.")
                    await event.respond("✂️ Нарезаю видео и оформляю субтитры. Оригинальная речь сохранится.")
                    details = await asyncio.to_thread(
                        edit_video, original, result, mode, color, audio_profile,
                        subtitle_style, hook
                    )
                    await client.send_file(
                        event.chat_id, str(result), supports_streaming=True,
                        caption=(
                            "✅ Reels готов! 🎬\n"
                            f"Длительность: {details['before']} → {details['after']} сек.\n"
                            "Оригинальная речь сохранена."
                        ),
                    )
            except Exception as exc:
                LOG.exception("Монтаж завершился ошибкой")
                safe = str(exc) if isinstance(exc, ValueError) else "Монтаж не завершился. Открой журнал Actions."
                await event.respond("⚠️ " + safe[:300])
            finally:
                done.set()

        try:
            await asyncio.wait_for(done.wait(), timeout=WAIT_SECONDS)
        except asyncio.TimeoutError:
            LOG.info("Время ожидания нового видео закончилось. Завершаем задание.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
