"""Дополнительные эффекты Reels: звуковые акценты, эмодзи, хук с подложкой.

Оригинальные синтезированные аудиосигналы: без лицензированных сэмплов.
Эмодзи Pillow/Noto, без доступа к сторонним сервисам и без платных API.
Не имитируем визуальные/звуковые ассеты «Чит-Кода».
"""
from __future__ import annotations

import logging
import math
import re
import tempfile
import wave
from array import array
from pathlib import Path
from typing import Sequence

from signature_captions import ass_color, ass_time, safe_text

LOG = logging.getLogger("reels_effects")
Word = tuple[float, float, str]

# Подбираем эмодзи только для явно узнаваемых слов; не придумываем смысл.
EMOJI_WORDS = (
    ("ошиб", "❌"),
    ("важн", "❗"), ("вниман", "👀"), ("главн", "❗"),
    ("совет", "💡"), ("идея", "💡"),
    ("маникюр", "💅"), ("ногт", "💅"),
    ("красив", "✨"), ("идеальн", "✨"),
    ("работ", "🛠️"), ("мастер", "💅"), ("студ", "🎬"),
    ("салон", "✨"), ("параллел", "🔄"), ("задач", "📋"),
    ("съем", "🎥"), ("съём", "🎥"),
    ("камер", "🎥"), ("видео", "🎞️"), ("фот", "📸"),
    ("интерес", "👀"), ("вопрос", "❓"), ("покаж", "👀"),
    ("секунд", "⏱"), ("врем", "⏱"),
    ("провер", "✅"), ("правильн", "✅"),
    ("ужас", "😱"), ("кошмар", "😱"),
    ("скидк", "🏷️"), ("цен", "💰"), ("выгод", "💰"),
    ("секрет", "🔐"), ("проблем", "⚠️"), ("результат", "🎯"),
    ("клиент", "❤️"), ("обуч", "🎓"), ("урок", "🎓"),
    ("дизайн", "🎨"), ("покрыт", "💅"), ("цвет", "🎨"),
    ("новинк", "🆕"), ("тренд", "🔥"), ("успех", "🏆"),
    ("сравн", "⚖️"), ("наход", "🔎"),
)
_ALLOWED_SFX = {"off", "soft", "punch"}
_ALLOWED_CAPTION_SFX = {"off", "soft", "tick"}
_ALLOWED_EMOJI = {"on", "off"}
_ALLOWED_HOOK = {"start", "end", "both", "off"}


def validate_effects(sound: str, emoji: str, hook_position: str) -> None:
    if sound not in _ALLOWED_SFX:
        raise ValueError("Звук: off, soft или punch.")
    if emoji not in _ALLOWED_EMOJI:
        raise ValueError("Эмодзи: on или off.")
    if hook_position not in _ALLOWED_HOOK:
        raise ValueError("Хук: start, end, both или off.")


def pick_cues(
    words: Sequence[Word], duration: float, *, limit: int = 18,
) -> list[tuple[float, str | None]]:
    """Эмодзи на смысловых словах, с интервалом не менее 1.35 с."""
    if duration <= 0:
        return []
    result: list[tuple[float, str | None]] = []
    last = -10.0
    for start, end, token in sorted(words, key=lambda x: x[0]):
        t = max(0.0, float(start))
        if t < 0.25 or t > duration - 0.40 or t - last < 1.35:
            continue
        cleaned = re.sub(r"[^\wа-яё]", "", token.lower())
        emoji = next((symbol for stem, symbol in EMOJI_WORDS if stem in cleaned), None)
        if emoji is None:
            continue
        result.append((t, emoji))
        last = t
        if len(result) >= limit:
            return result

    # Если нет слов из словаря, добавляем нейтральные ✨ только
    # на смысловые слова. Никаких случайных и неуместных символов.
    if words and len(result) < limit:
        from signature_captions import split_groups, pick_main_word
        extras: list[tuple[float, str]] = []
        for group in split_groups(words):
            chosen = group[pick_main_word(group)]
            t = float(chosen[0])
            clean = re.sub(r"[^а-яёa-z0-9]", "", chosen[2].lower())
            if 0.25 <= t <= duration - 0.40 and len(clean) >= 5:
                extras.append((t, "✨"))
        for t, symbol in extras:
            if any(abs(t - existing) < 1.20 for existing, _ in result):
                continue
            result.append((t, symbol))
            if len(result) >= limit:
                break
    return sorted(result)


def pick_caption_cues(
    words: Sequence[Word], duration: float, *,
    style: str = "soft", limit: int = 36,
) -> list[tuple[float, str | None]]:
    """Очень тихие аудио-сигналы на переходах слов, а не на каждом слове."""
    if style not in ("soft", "tick"):
        raise ValueError("Звук субтитров: soft или tick.")
    if duration <= 0:
        return []
    minimum_gap = 1.00 if style == "soft" else 0.75
    last = -10.0
    result = []
    for start, end, word in sorted(words, key=lambda w: w[0]):
        t = max(0.0,float(start))
        clean = re.sub(r"[^а-яёa-z0-9]", "", word.lower())
        if len(clean) < 4 or t < 0.25 or t > duration - 0.25:
            continue
        if t-last < minimum_gap:
            continue
        result.append((t,None))
        last = t
        if len(result) >= limit:
            break
    return result


def _escape_hook(value: str) -> str:
    return safe_text(value).replace("\n", " ")[:58]


def add_hook_to_ass(
    content: str,
    text: str,
    *,
    position: str,
    duration: float,
    color: str,
    font_profile: str = "elegant",
) -> str:
    """Хук в начале/конце с тёмной полупрозрачной подложкой ЗА текстом."""
    if position not in _ALLOWED_HOOK:
        raise ValueError("Недопустимое положение хука.")
    text = _escape_hook(text)
    if not text or position == "off" or duration < 0.6:
        return content
    from font_presets import choose_font
    font = choose_font(font_profile)
    accent = ass_color(color if color != "auto" else "#EBC0C8")
    new_styles = (
        f"Style: ReelsHook,{font.name},51,{accent},{accent},&H00241A20,"
        f"&HAA000000,{font.bold},{font.italic},0,0,"
        f"{font.scale_x},{font.scale_y},0,0,1,1.5,1,5,54,54,40,1\n"
        "Style: HookPlate,DejaVu Sans,20,&H00FFFFFF,&H00FFFFFF,&H00161616,"
        "&H7C161616,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n"
    )
    if "\n[Events]\n" not in content:
        raise ValueError("Неверный формат ASS для добавления хука.")
    content = content.replace("\n[Events]\n", "\n" + new_styles + "\n[Events]\n", 1)
    span = min(3.6, max(0.6, duration))
    windows = []
    if position in ("start", "both"):
        windows.append((0.0, min(span, duration)))
    if position in ("end", "both"):
        start = max(0.0, duration-span)
        if not windows or start > windows[-1][1] + 0.15:
            windows.append((start, duration))
    for start, end in windows:
        fadein = min(240, int((end-start)*230))
        fadeout = min(270, int((end-start)*230))
        # Плашка позади хука; текстовой слой имеет более высокий порядок.
        shape = (
            r"{\an5\pos(360,202)\p1\1c&H272025&\1a&H68&"
            r"\fad("+str(fadein)+","+str(fadeout)+")}"
            "m -319 -73 l 319 -73 l 319 73 l -319 73"
        )
        label = (
            r"{\an5\pos(360,202)\fad("+str(fadein)+","+str(fadeout)+")"
            r"\fscx94\fscy94\t(0,320,\fscx100\fscy100)}"
            +text.upper()
        )
        content += (
            f"Dialogue: 3,{ass_time(start)},{ass_time(end)},HookPlate,,0,0,0,,{shape}\n"
            f"Dialogue: 4,{ass_time(start)},{ass_time(end)},ReelsHook,,0,0,0,,{label}\n"
        )
    return content


def make_sfx_track(
    target: Path,
    cues: Sequence[tuple[float, str | None]],
    duration: float,
    intensity: str = "soft",
    rate: int = 48000,
) -> None:
    """Тихие короткие собственные pop-звуки, не подавляющие речь."""
    if intensity not in ("soft", "punch", "caption_soft", "caption_tick"):
        raise ValueError("Недопустимая интенсивность звуков.")
    total = max(1, round(duration*rate))
    peak = {"soft":0.12, "punch":0.20, "caption_soft":0.095,
            "caption_tick":0.13}[intensity]
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        cursor = 0
        for moment, _ in sorted(cues):
            start = min(total, max(cursor, int(moment*rate)))
            zero_count = max(0, start-cursor)
            if zero_count:
                wav.writeframesraw(b"\x00\x00"*zero_count)
                cursor += zero_count
            if cursor >= total:
                break
            n = min(int(rate*(0.095 if intensity.startswith("caption_") else 0.19)),
                    total-cursor)
            samples = array("h")
            for i in range(n):
                t = i/rate
                envelope = (1-math.exp(-t*110))*math.exp(-t*27)
                frequency = (985-130*t/0.095
                             if intensity.startswith("caption_")
                             else 710-190*t/0.19)
                audio = (math.sin(2*math.pi*frequency*t)*0.74
                         + math.sin(2*math.pi*frequency*1.58*t)*0.26)
                value = int(32767*peak*envelope*audio)
                samples.append(max(-32767,min(32767,value)))
            wav.writeframesraw(samples.tobytes())
            cursor += n
        if cursor < total:
            wav.writeframesraw(b"\x00\x00"*(total-cursor))


def emoji_image(emoji: str, output: Path) -> None:
    """Создать PNG настоящего эмодзи из установленного Noto Color Emoji."""
    from PIL import Image, ImageDraw, ImageFont

    font_path = Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")
    if not font_path.is_file():
        # GitHub Actions устанавливает font-noto-color-emoji. Явно
        # предупреждаем, если в другой системе шрифт отсутствует.
        raise RuntimeError("Для эмодзи нужен шрифт fonts-noto-color-emoji.")
    font = ImageFont.truetype(str(font_path), size=109)
    canvas = Image.new("RGBA",(145,145),(0,0,0,0))
    brush=ImageDraw.Draw(canvas)
    brush.text((72,72), emoji, font=font, anchor="mm", embedded_color=True)
    bbox=canvas.getbbox()
    if bbox is None:
        raise RuntimeError("Не получилось нарисовать эмодзи.")
    # Иконка размера 105x105 с небольшим прозрачным полем.
    crop = canvas.crop(bbox)
    crop.thumbnail((105,105), Image.Resampling.LANCZOS)
    final = Image.new("RGBA",(120,120),(0,0,0,0))
    final.alpha_composite(crop,((120-crop.width)//2,(120-crop.height)//2))
    final.save(output)


def apply_effects(
    source: Path,
    target: Path,
    words: Sequence[Word],
    *,
    sound: str = "off",
    emoji: str = "off",
    caption_position: str = "middle",
    quality: str = "high",
    caption_sound: str = "off",
    insert_style: str = "off",
    insert_density: str = "balanced",
    insert_sound: str = "on",
) -> dict:
    """Тематические винтажные cutaway, эмодзи, звук, без изменения речи."""
    from telegram_editor import duration_and_audio, execute
    from export_profiles import get_export_profile
    export = get_export_profile(quality)

    validate_effects(sound, emoji, "off")
    if caption_sound not in _ALLOWED_CAPTION_SFX:
        raise ValueError("Звуки субтитров: off, soft или tick.")
    if insert_style not in ("off", "retro", "minimal"):
        raise ValueError("Вставки: off, retro или minimal.")
    if insert_density not in ("subtle", "balanced", "dynamic"):
        raise ValueError("Плотность вставок: subtle, balanced или dynamic.")
    if insert_sound not in ("on", "off"):
        raise ValueError("Звуки вставок: on или off.")
    if caption_position not in ("top", "middle", "bottom"):
        raise ValueError("Неверная позиция эмодзи.")
    duration, has_audio = duration_and_audio(source)
    from retro_inserts import choose_retro_cues, make_retro_card, make_retro_sound_track
    retro = (choose_retro_cues(words, duration, density=insert_density)
             if insert_style != "off" else [])
    cues = pick_cues(words, duration)
    caption_cues = (pick_caption_cues(words,duration,style=caption_sound)
                    if caption_sound != "off" else [])
    # Обычные смайлы не перекрывают большую иллюстрированную карточку.
    visual = [(t, symbol) for t, symbol in cues if symbol
              and all(abs(t - r.time) > 1.15 for r in retro)
             ] if emoji == "on" else []
    if (sound == "off" and not visual and not caption_cues and not retro):
        source.replace(target)
        return {"emoji_count": 0, "sfx_count": 0, "caption_sfx_count": 0,
                "insert_count": 0, "insert_sfx_count": 0}

    with tempfile.TemporaryDirectory(prefix="reels_effects_") as tmp:
        folder = Path(tmp)
        args = ["ffmpeg","-hide_banner","-loglevel","error","-y","-i",str(source)]
        filters: list[str] = []
        prev = "[0:v]"
        current_input = 1
        emoji_count = 0
        if visual:
            # Стикер рядом с центральной зоной титра, а не на краю.
            yratio = {"top": .265, "middle": .515, "bottom": .635}[caption_position]
            # Ограничение, чтобы до двух минут оставаться лёгким для runner.
            for i,(start,symbol) in enumerate(visual[:16]):
                path = folder/f"emoji_{i}.png"
                try:
                    emoji_image(symbol, path)
                except Exception as exc:
                    LOG.warning("Не удалось подготовить %s: %s", symbol, exc)
                    continue
                args.extend(["-loop","1","-framerate","30","-i",str(path)])
                clip_end = min(duration, start+1.0)
                alpha = (f"[{current_input}:v]format=rgba,"
                         f"fade=t=in:st={start:.2f}:d=0.16:alpha=1,"
                         f"fade=t=out:st={max(start+0.22,clip_end-0.18):.2f}:d=0.18:alpha=1[emoji{i}]")
                filters.append(alpha)
                dest = f"[stage{i}]"
                filters.append(
                    f"{prev}[emoji{i}]overlay=x='main_w*(0.70+0.03*mod({i},2))':"
                    f"y='{yratio}*main_h+12*max(0,1-(t-{start:.2f})*4)':"
                    f"enable='between(t,{start:.2f},{clip_end:.2f})'"
                    f":shortest=1{dest}"
                )
                prev = dest
                current_input += 1
                emoji_count += 1

        insert_count = 0
        rendered_retro = []
        for i, insert in enumerate(retro):
            card = folder / f"vintage_card_{i}.png"
            try:
                make_retro_card(card, insert.label, insert.symbol, style=insert_style)
            except Exception as exc:
                LOG.warning("Не удалось подготовить винтажную карточку: %s",exc)
                continue
            args.extend(["-loop","1","-framerate","30","-i",str(card)])
            start=insert.time
            finish=min(duration,start+1.35)
            filters.append(
                f"[{current_input}:v]format=rgba,"
                f"fade=t=in:st={start:.3f}:d=0.19:alpha=1,"
                f"fade=t=out:st={max(start+0.25,finish-0.22):.3f}:d=0.22:"
                f"alpha=1[insert{i}]"
            )
            dest=f"[cardstage{i}]"
            filters.append(
                f"{prev}[insert{i}]overlay=x='(main_w-overlay_w)/2':"
                f"y='main_h*0.16+26*max(0,1-(t-{start:.3f})*5)':"
                f"enable='between(t,{start:.3f},{finish:.3f})':shortest=1{dest}"
            )
            prev=dest
            current_input += 1
            insert_count += 1
            rendered_retro.append(insert)

        sfx_count = 0
        caption_sfx_count = 0
        insert_sfx_count = 0
        sound_output = "0:a:0?"
        track_inputs = ["[0:a:0]"]
        if sound != "off" and has_audio and cues:
            track = folder/"accents.wav"
            make_sfx_track(track,cues,duration,sound)
            args.extend(["-i",str(track)])
            track_inputs.append(f"[{current_input}:a:0]")
            current_input += 1
            sfx_count = len(cues)
        if caption_sound != "off" and has_audio and caption_cues:
            track = folder/"subtitle_pops.wav"
            intensity = "caption_soft" if caption_sound == "soft" else "caption_tick"
            make_sfx_track(track,caption_cues,duration,intensity)
            args.extend(["-i",str(track)])
            track_inputs.append(f"[{current_input}:a:0]")
            current_input += 1
            caption_sfx_count = len(caption_cues)
        if insert_sound=="on" and has_audio and insert_count:
            cue_track=folder/"retro_insert_accents.wav"
            make_retro_sound_track(cue_track, rendered_retro, duration)
            args.extend(["-i",str(cue_track)])
            track_inputs.append(f"[{current_input}:a:0]")
            current_input+=1
            insert_sfx_count=insert_count
        if len(track_inputs)>1:
            filters.append(
                "".join(track_inputs)
                + f"amix=inputs={len(track_inputs)}:duration=first:"
                + "normalize=0,alimiter=limit=0.96[mixed]"
            )
            sound_output = "[mixed]"

        if emoji_count or insert_count:
            args.extend(["-filter_complex",";".join(filters),"-map",prev,
                         "-c:v","libx264","-preset",export.preset,"-crf",str(export.crf)])
        elif sfx_count or caption_sfx_count or insert_sfx_count:
            args.extend(["-filter_complex",";".join(filters),"-map","0:v:0",
                         "-c:v","copy"])
        else:
            source.replace(target)
            return {"emoji_count":0,"sfx_count":0,"caption_sfx_count":0,
                    "insert_count":0,"insert_sfx_count":0}
        if sfx_count or caption_sfx_count or insert_sfx_count:
            args.extend(["-map",sound_output,"-c:a","aac","-b:a",export.audio_bitrate])
        else:
            args.extend(["-map","0:a:0?","-c:a","copy"])
        args.extend(["-t",f"{duration:.3f}","-movflags","+faststart",str(target)])
        execute(args)
        return {"emoji_count":emoji_count, "sfx_count":sfx_count,
                "caption_sfx_count":caption_sfx_count,
                "insert_count":insert_count,"insert_sfx_count":insert_sfx_count}
