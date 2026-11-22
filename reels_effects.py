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
_ALLOWED_SFX = {"off", "soft", "punch", "whoosh"}
_ALLOWED_CAPTION_SFX = {"off", "soft", "tick", "typewriter"}
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
    words: Sequence[Word], duration: float, *, limit: int = 10,
) -> list[tuple[float, str | None]]:
    """Only sparse, meaningful emoji; no generic decorative stickers."""
    if duration <= 0:
        return []
    result: list[tuple[float, str | None]] = []
    last = -10.0
    for start, end, token in sorted(words, key=lambda x: x[0]):
        t = max(0.0, float(start))
        if t < 0.25 or t > duration - 0.40 or t - last < 2.2:
            continue
        cleaned = re.sub(r"[^\wа-яё]", "", token.lower())
        emoji = next((symbol for stem, symbol in EMOJI_WORDS if stem in cleaned), None)
        if emoji is None:
            continue
        result.append((t, emoji))
        last = t
        if len(result) >= limit:
            return result

    return sorted(result)


def pick_caption_cues(
    words: Sequence[Word], duration: float, *,
    style: str = "soft", limit: int = 36,
) -> list[tuple[float, str | None]]:
    """One gentle cue per displayed PHRASE, never a chime on every word."""
    if style not in ("soft","tick","typewriter"):
        raise ValueError("Звуки субтитров: soft или tick.")
    from reference_dynamic_captions import phrase_groups
    min_gap=1.22 if style=="soft" else 0.84
    last=-10.0
    cues=[]
    for group in phrase_groups(words):
        t=float(group[0][0])
        if t < 0.25 or t > duration-0.30 or t-last < min_gap:
            continue
        cues.append((t,None))
        last=t
        if len(cues)>=limit:break
    return cues


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
    y_center: int = 202,
) -> str:
    """Хук с круглой тенью; с заголовком сверху сдвигается ниже него."""
    if not 140 <= y_center <= 345:
        raise ValueError("Недопустимая высота хука.")
    if position not in _ALLOWED_HOOK:
        raise ValueError("Недопустимое положение хука.")
    text = _escape_hook(text)
    if not text or position == "off" or duration < 0.6:
        return content
    from font_presets import choose_font
    from reference_dynamic_captions import _oval_phrase_shadow
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
        # Same fully rounded capsule as speech subtitles, never a box.
        oval_width=min(612,max(212,round(len(text)*27+66)))
        oval=_oval_phrase_shadow(oval_width,126)
        shape = (
            (r"{\an5\pos(360,"+str(y_center)+r")\p1\blur6\1c&H272025&\1a&H8E&")
            +r"\fad("+str(fadein)+","+str(fadeout)+")}"
            +oval+r"{\p0}"
        )
        label = (
            r"{\an5\pos(360,"+str(y_center)+r")\fad("+str(fadein)+","+str(fadeout)+")"
            +r"\fscx94\fscy94\t(0,320,\fscx100\fscy100)}"
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
    if intensity not in ("soft", "punch", "whoosh", "caption_soft", "caption_tick", "caption_typewriter"):
        raise ValueError("Недопустимая интенсивность звуков.")
    total = max(1, round(duration*rate))
    peak = {"soft":0.10, "punch":0.18, "whoosh":0.15,
            "caption_soft":0.060, "caption_tick":0.085,
            "caption_typewriter":0.14}[intensity]
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
            span = (0.72 if intensity=="caption_typewriter"
                    else 0.43 if intensity=="whoosh"
                    else 0.095 if intensity.startswith("caption_") else 0.19)
            n = min(int(rate*span),total-cursor)
            samples = array("h")
            for i in range(n):
                t = i/rate
                if intensity=="caption_typewriter":
                    # Six delicate paired mechanical clicks per phrase,
                    # timed like typing rather than one synthetic ringtone.
                    keytime=t % .116
                    envelope=(math.exp(-keytime*130)+
                              .35*math.exp(-abs(keytime-.024)*260))
                    seed=(i*1664525+1013904223)&0xFFFFFFFF
                    noise=((seed>>9)/8388608.0)*2-1
                    audio=noise*.65+math.sin(2*math.pi*1300*t)*.35
                elif intensity=="whoosh":
                    envelope=max(0.,math.sin(math.pi*t/span))**1.8
                    seed=(i*22695477+12345)&0xFFFFFFFF
                    noise=((seed>>9)/8388608.0)*2-1
                    audio=noise*.74+math.sin(2*math.pi*(350+540*t/span)*t)*.26
                else:
                    envelope=(1-math.exp(-t*110))*math.exp(-t*27)
                    frequency=(985-130*t/.095 if intensity.startswith("caption_")
                               else 710-190*t/.19)
                    audio=(math.sin(2*math.pi*frequency*t)*.74
                           +math.sin(2*math.pi*frequency*1.58*t)*.26)
                value=int(32767*peak*envelope*audio)
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
    font_profile: str = "bold",
    small_font_profile: str = "modern",
    animation_style: str = "float",
    private_assets = None,
    studio_mode: bool = False,
    studio_scene: str = "off",
    insert_source: Path | None = None,
    guide_effect: str = "off",
) -> dict:
    """Тематические винтажные cutaway, эмодзи, звук, без изменения речи."""
    from telegram_editor import duration_and_audio, media_info, execute
    from export_profiles import get_export_profile
    export = get_export_profile(quality)

    validate_effects(sound, emoji, "off")
    if caption_sound not in _ALLOWED_CAPTION_SFX:
        raise ValueError("Звуки субтитров: off, soft, tick или typewriter.")
    from retro_inserts import CARD_STYLES
    if insert_style != "off" and insert_style not in CARD_STYLES:
        raise ValueError("Неизвестный стиль вставок: " + insert_style)
    if insert_density not in ("subtle", "balanced", "dynamic"):
        raise ValueError("Плотность вставок: subtle, balanced или dynamic.")
    if insert_sound not in ("on", "off"):
        raise ValueError("Звуки вставок: on или off.")
    if caption_position not in ("top", "middle", "bottom"):
        raise ValueError("Неверная позиция эмодзи.")
    duration, has_audio = duration_and_audio(source)
    # The subtitle ASS uses 720x1280 coordinates; Full HD output is 1080x1920.
    # Scale emoji placement and size to the ACTUAL video stream dimensions.
    info=media_info(source)
    stream=next((it for it in info.get("streams",[])
                 if it.get("codec_type")=="video"),{})
    frame_width=int(stream.get("width") or 720)
    frame_height=int(stream.get("height") or 1280)
    sx=frame_width/720
    sy=frame_height/1280
    from retro_inserts import choose_retro_cues, make_retro_card, make_retro_sound_track
    from vintage_cinema import select_vintage_cues, render_vintage_scene, make_vintage_sound_track
    from reference_motion_scenes import select_motion_cues, make_motion_assets
    from studio_kinetic import select_studio_cues, make_studio_card, make_studio_keyword_asset
    from guide18_fx import plan as plan_guide, render as render_guide, sound_track as guide_audio
    from semantic_editing import choose_semantic_cues
    from semantic_object_overlays import choose_object_cues
    # PNG props only appear at a genuinely spoken matching noun.
    object_cues=(choose_object_cues(
        words,duration,private_assets.photos,insert_density
    ) if insert_style!="off" and private_assets is not None else [])
    semantic_cues=(choose_semantic_cues(
                       words,duration,"subtle" if studio_mode else insert_density
                   ) if (insert_style=="reference_soft" or
                         studio_mode and emoji=="on") else [])
    motion_cues=(select_motion_cues(words,duration,insert_density)
                 if insert_style=="reference_soft" and not studio_mode else [])
    # Automatic mode NEVER invokes legacy huge studio cards and kinetic
    # words. The new speech-matched guide micro-cues handle small accents.
    # Manual off retains the old studio module for backward-compatible
    # existing projects that intentionally selected it.
    studio_cues=(select_studio_cues(words,duration,insert_density)
                 if studio_mode and insert_style!="off" and guide_effect=="off"
                 else [])
    retro=(choose_retro_cues(words,duration,density=insert_density)
           if insert_style not in ("off","reference_soft","vintage") and not studio_mode else [])
    vintage_cues=(select_vintage_cues(words,duration,insert_density)
                  if insert_style=="vintage" else [])
    # In a guide scene, no second independent studio card / kinetic headline
    # may overlap it. Exactly one primary animation owns this time window.
    guide_cues=(plan_guide(words,duration,guide_effect,insert_density)
                if insert_style!="off" and guide_effect!="off"
                and not (insert_style=="vintage" and guide_effect=="auto") else [])

    # The FIRST FOUR SECONDS belong exclusively to the speaker and their
    # correctly timed subtitles. All independent decorative planners must
    # obey this same guard, including explicit PDF techniques and user PNGs.
    intro_clear_seconds=4.0
    object_cues=[c for c in object_cues if c.start>=intro_clear_seconds]
    semantic_cues=[c for c in semantic_cues if c.start>=intro_clear_seconds]
    motion_cues=[c for c in motion_cues if c.start>=intro_clear_seconds]
    studio_cues=[c for c in studio_cues if c.start>=intro_clear_seconds]
    retro=[c for c in retro if c.time>=intro_clear_seconds]
    vintage_cues=[c for c in vintage_cues if c.start>=intro_clear_seconds]
    guide_cues=[c for c in guide_cues if c.start>=intro_clear_seconds]
    # Legacy full-screen illustrated motion panels obscure the conversation
    # even when semantically triggered. Keep them disabled until redesigned
    # as compact person-safe overlays. Reference-safe PNG/caption accents remain.
    motion_cues=[]
    if object_cues and guide_cues:
        overlap=lambda a,b: (a.start < b.end+.35 and a.end > b.start-.35)
        if guide_effect=="auto":
            # Concrete spoken objects outrank an auto-generated generic
            # graphic; never show both simultaneously.
            guide_cues=[g for g in guide_cues
                        if not any(overlap(g,o) for o in object_cues)]
        else:
            # A manually chosen full-screen effect is always intentional.
            object_cues=[o for o in object_cues
                         if not any(overlap(o,g) for g in guide_cues)]
    if vintage_cues:
        # Only one full-frame cutaway may own a time window. Uploaded real
        # stickers remain allowed outside those windows, with face protection.
        vintage_cues=[v for v in vintage_cues if not any(
            v.start < g.end+.3 and v.end > g.start-.3 for g in guide_cues)]
        object_cues=[o for o in object_cues if not any(
            o.start < v.end+.3 and o.end > v.start-.3 for v in vintage_cues)]
    if guide_cues or object_cues:
        # Eliminate secondary large cards rather than accidentally mixing
        # animations from different independent planners.
        retro=[]
        motion_cues=[]
        studio_cues=[]
        semantic_cues=[]
    semantic_emojis={
        "error":"❌","inspect":"🔎","success":"✅","compare":"↔️",
        "time":"⏱️","speech":"💬","camera":"🎥",
        "phone":"📱","next":"➡️",
    }
    # No stickers merely for saying a generic "маникюр" or "видео".
    cues=([(c.start,semantic_emojis.get(c.kind)) for c in semantic_cues]
          if studio_mode or insert_style=="reference_soft"
          else [(t,symbol) for t,symbol in pick_cues(words,duration)
                if t>=intro_clear_seconds])
    caption_cues = (pick_caption_cues(
                        words,duration,
                        style=caption_sound
                    ) if caption_sound != "off" else [])
    # Обычные смайлы не перекрывают большую иллюстрированную карточку.
    from reference_dynamic_captions import phrase_emoji_anchors
    geometry=phrase_emoji_anchors(words, caption_position,
                                  small_font_profile, font_profile,
                                  animation_style)
    if studio_mode:
        # The studio subtitle layout is moved 143 ASS units upward to stay
        # The dynamic studio caption panel uses a 48px upper offset.
        # Keep emojis attached to their actual moving phrase coordinates.
        geometry=[
            (start,end,x0,y0-48,x1,y1-48)
            for start,end,x0,y0,x1,y1 in geometry
        ]
    # Attach emoji to the emphasized phrase line, rather than the screen edge.
    visual=[]
    used_phrases=set()
    if emoji=="on":
        for t,symbol in cues:
            if (not symbol or any(abs(t-r.time)<1.15 for r in retro)
                    or any(sc.start-.15<=t<=sc.end+.15 for sc in motion_cues)):
                continue
            for k,(start,end,x0,y0,x1,y1) in enumerate(geometry):
                if start-0.05<=t<=end+0.02 and k not in used_phrases:
                    visual.append((start,end,symbol,x0,y0,x1,y1))
                    used_phrases.add(k)
                    break
    if (sound == "off" and not visual and not caption_cues
            and not retro and not motion_cues and not studio_cues
            and not guide_cues and not object_cues and not (private_assets and any(
                c.kind in private_assets.icons for c in semantic_cues))):
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
            # One refined sticker beside the actual PHRASE. It fades and
            # floats together with that phrase, with a 12px breathing gap.
            for i,(start,clip_end,symbol,x0,y0,x1,y1) in enumerate(visual[:10]):
                path = folder/f"emoji_{i}.png"
                try:
                    emoji_image(symbol, path)
                except Exception as exc:
                    LOG.warning("Не удалось подготовить %s: %s", symbol, exc)
                    continue
                args.extend(["-loop","1","-framerate","30","-i",str(path)])
                clip_end=min(duration,clip_end)
                sticker_size=max(24,round((29 if studio_mode else 43)*sx))
                moving_seconds=max(0.25,clip_end-start)
                position=f"max(0,min(1,(t-{start:.3f})/{moving_seconds:.3f}))"
                sticker_x=f"{x0*sx:.2f}+{(x1-x0)*sx:.2f}*{position}"
                sticker_y=f"{y0*sy-sticker_size/2:.2f}+{(y1-y0)*sy:.2f}*{position}"
                alpha = (f"[{current_input}:v]"
                         f"scale={sticker_size}:{sticker_size},format=rgba,"
                         f"fade=t=in:st={start:.3f}:d=0.30:alpha=1,"
                         f"fade=t=out:st={max(start+0.31,clip_end-0.22):.3f}:"
                         f"d=0.22:alpha=1[emoji{i}]")
                filters.append(alpha)
                dest = f"[stage{i}]"
                filters.append(
                    f"{prev}[emoji{i}]overlay=x='{sticker_x}':"
                    f"y='{sticker_y}':"
                    f"enable='between(t,{start:.3f},{clip_end:.3f})'"
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
            finish=min(duration,start+(1.80 if insert_style=="reference_soft" else 1.35))
            # Reference cutaways take approximately half the picture, not
            # the tiny cards used by legacy vintage styles.
            large=insert_style=="reference_soft"
            insert_width=max(220,round((625 if large else 286)*sx))
            insert_height=max(172,round((497 if large else 228)*sy))
            filters.append(
                f"[{current_input}:v]"
                f"scale={insert_width}:{insert_height},format=rgba,"
                f"fade=t=in:st={start:.3f}:d=0.26:alpha=1,"
                f"fade=t=out:st={max(start+0.25,finish-0.22):.3f}:d=0.22:"
                f"alpha=1[insert{i}]"
            )
            dest=f"[cardstage{i}]"
            filters.append(
                f"{prev}[insert{i}]overlay=x='(main_w-overlay_w)/2':"
                f"y='main_h*{0.07 if large else 0.16}+26*max(0,1-(t-{start:.3f})*3)':"
                f"enable='between(t,{start:.3f},{finish:.3f})':shortest=1{dest}"
            )
            prev=dest
            current_input += 1
            insert_count += 1
            rendered_retro.append(insert)

        # True vintage cinema: a short full-height archive-film scene covers
        # the speaker entirely while their unchanged original speech continues.
        # Captions in this scene are only real words from the transcription.
        rendered_vintage = []
        for i, cue in enumerate(vintage_cues):
            try:
                pattern, _ = render_vintage_scene(folder, cue, i)
            except Exception as exc:
                LOG.warning("Skipping failed vintage cinema scene: %s", exc)
                continue
            args.extend(["-framerate", "12", "-start_number", "0",
                         "-i", pattern])
            layer=f"[vintagescene{i}]"
            filters.append(
                f"[{current_input}:v]fps=30,scale={frame_width}:{frame_height}:"
                f"flags=lanczos,format=rgba,"
                f"setpts=PTS-STARTPTS+{cue.start:.3f}/TB{layer}"
            )
            stage=f"[vintagestage{i}]"
            filters.append(
                f"{prev}{layer}overlay=x=0:y=0:"
                f"enable='between(t,{cue.start:.3f},{cue.end:.3f})':"
                f"shortest=0:eof_action=pass:repeatlast=0{stage}"
            )
            prev=stage
            current_input+=1
            rendered_vintage.append(cue)
            insert_count+=1

        scene_count = 0
        for i, scene in enumerate(motion_cues):
            # Three transparent planes: paper-white stage, original-video
            # illustration/photo collage, and a late-entering decoration.
            assets=make_motion_assets(source,folder,scene,i)
            start,end=scene.start,scene.end
            for layer,path in enumerate(assets):
                delay=(0.0,0.26,0.58)[layer]
                appear=start+delay
                if appear>=end-.15:continue
                args.extend(["-loop","1","-framerate","30","-i",str(path)])
                out_label=f"[motion{i}_{layer}]"
                fadeout=max(appear+.38,end-.33)
                filters.append(
                    f"[{current_input}:v]scale={frame_width}:{frame_height},"
                    f"format=rgba,fade=t=in:st={appear:.3f}:d=0.36:alpha=1,"
                    f"fade=t=out:st={fadeout:.3f}:d=0.30:alpha=1{out_label}"
                )
                stage=f"[motionstage{i}_{layer}]"
                # The illustrated object keeps gliding after appearing, while
                # the white backdrop remains steady.
                if layer==0:
                    travel="0"
                else:
                    travel=(f"{round(18*sy)}-"
                            f"{round(24*sy)}*min(1,max(0,(t-{appear:.3f})/0.6))"
                            f"-{round(5*sy)}*sin((t-{appear:.3f})*1.4)")
                filters.append(
                    f"{prev}{out_label}overlay=x=0:y='{travel}':"
                    f"enable='between(t,{appear:.3f},{end:.3f})'"
                    f":shortest=1{stage}"
                )
                prev=stage
                current_input+=1
            scene_count+=1

        # Full-height editorial video stays visible behind every insert.
        # Each short animated card contains an authentic frame from the
        # user's clean footage and a word from the approved transcript.
        studio_insert_count = 0
        kinetic_word_count = 0
        if studio_cues:
            # Large original kinetic word graphics across the live footage,
            # not a static mini-screenshot at the right edge. Alternate
            # positions and timing by the real speech, retaining 9:16.
            for i,cue in enumerate(studio_cues[:10]):
                headline=folder/f"kinetic_keyword_{i}.png"
                make_studio_keyword_asset(headline,cue,studio_scene,i)
                start,end=cue.start,cue.end
                args.extend(["-loop","1","-framerate","30","-i",str(headline)])
                glyph=f"[wordmotion{i}]"
                glyph_w=round(520*sx)
                glyph_h=round(179*sy)
                filters.append(
                    f"[{current_input}:v]scale={glyph_w}:{glyph_h},"
                    f"format=rgba,fade=t=in:st={start:.3f}:d=0.24:alpha=1,"
                    f"fade=t=out:st={max(start+.32,end-.26):.3f}:"
                    f"d=0.22:alpha=1{glyph}"
                )
                direction=1 if i%2 else -1
                word_x=(f"(main_w-overlay_w)/2+{direction*round(55*sx)}*"
                        f"max(0,1-(t-{start:.3f})*3.2)")
                word_y=(f"main_h*{.34 if i%2 else .46}-overlay_h/2+"
                        f"{round(20*sy)}*max(0,1-(t-{start:.3f})*3)")
                stage=f"[wordstage{i}]"
                filters.append(
                    f"{prev}{glyph}overlay=x='{word_x}':y='{word_y}':"
                    f"enable='between(t,{start:.3f},{end:.3f})':"
                    f"shortest=1{stage}"
                )
                prev=stage
                current_input+=1
                kinetic_word_count+=1
            insert_count+=kinetic_word_count
            for i,cue in enumerate(studio_cues[:10]):
                asset=folder/f"editorial_insert_{i}.png"
                try:
                    make_studio_card(insert_source or source,asset,cue,studio_scene)
                except Exception as error:
                    LOG.warning("Не удалось подготовить анимированную вставку: %s",error)
                    continue
                args.extend(["-loop","1","-framerate","30","-i",str(asset)])
                start,end=cue.start,cue.end
                # No fixed tiny thumbnail: alternate larger left/right
                # moving footage and variable editorial crop sizes.
                width=max(185,round((334 if i%2==0 else 284)*sx))
                height=max(230,round((405 if i%2==0 else 340)*sy))
                name=f"[kinetic{i}]"
                filters.append(
                    f"[{current_input}:v]scale={width}:{height},format=rgba,"
                    f"fade=t=in:st={start:.3f}:d=0.30:alpha=1,"
                    f"fade=t=out:st={max(start+.4,end-.30):.3f}:d=0.27:"
                    f"alpha=1{name}"
                )
                stage=f"[kineticstage{i}]"
                travel=f"{round(75*sx)}*max(0,1-(t-{start:.3f})*3.2)"
                right_side=(i%2==0)
                target_x=(f"main_w-overlay_w-{round(22*sx)}"
                          if right_side else f"{round(22*sx)}")
                target_y=f"main_h-overlay_h-{round((125 if i%2==0 else 175)*sy)}"
                filters.append(
                    f"{prev}{name}overlay=x='{target_x}+{travel}':"
                    f"y='{target_y}+{round(18*sy)}*"
                    f"max(0,1-(t-{start:.3f})*3.2)':"
                    f"enable='between(t,{start:.3f},{end:.3f})':"
                    f"shortest=1{stage}"
                )
                prev=stage
                current_input+=1
                # Show a real MOVING clip inside the graphic card, not merely
                # a frozen thumbnail. This source is the clean, original edit
                # timeline, before any burned subtitles or decorative overlays.
                # It has no separate audio in the output, so speech stays exact.
                moving_source=insert_source or source
                clip_w=max(36,round(width*320/350))
                clip_h=max(36,round(height*286/430))
                left=round(width*15/350)
                top=round(height*15/430)
                clip_length=max(.2,end-start)
                args.extend([
                    "-ss",f"{start:.3f}","-t",f"{clip_length:.3f}",
                    "-i",str(moving_source),
                ])
                live=f"[liveclip{i}]"
                # Keep the reference's soft slide and the original footage
                # time-locked. A short fade ensures no hard pop at the edges.
                filters.append(
                    f"[{current_input}:v]fps=30,"
                    f"scale={clip_w}:{clip_h}:force_original_aspect_ratio=increase,"
                    f"crop={clip_w}:{clip_h},setsar=1,format=rgba,"
                    f"setpts=PTS-STARTPTS+{start:.3f}/TB,"
                    f"fade=t=in:st={start:.3f}:d=0.21:alpha=1,"
                    f"fade=t=out:st={max(start+.22,end-.23):.3f}:"
                    f"d=0.22:alpha=1{live}"
                )
                live_x=f"({target_x})+{left}+{travel}"
                live_y=(f"({target_y})+{top}+"
                        f"{round(18*sy)}*max(0,1-(t-{start:.3f})*3.2)")
                moving_stage=f"[movingstage{i}]"
                filters.append(
                    f"{prev}{live}overlay=x='{live_x}':y='{live_y}':"
                    f"enable='between(t,{start:.3f},{end:.3f})':"
                    f"shortest=0:eof_action=pass:repeatlast=0{moving_stage}"
                )
                prev=moving_stage
                current_input+=1
                studio_insert_count+=1
            insert_count+=studio_insert_count

        # The guide's 18 styles are rendered as genuine changing RGBA video
        # frame sequences. None is a static screenshot or another unplanned
        # floating card. They retain the original speech on audio input 0.
        guide_count=0
        rendered_guide_cues=[]
        for i,cue in enumerate(guide_cues):
            from guide18_fx import SUBJECT_FX
            guide_source=(source if cue.effect in SUBJECT_FX
                          else insert_source or source)
            try:
                pattern,count=render_guide(
                    guide_source,folder,cue,i,words,
                palette=studio_scene,
                caption_position=caption_position,
                # Auto mode never pours unrelated decorative PNGs into a
                # generic collage. Manual photo collage may use provided
                # client imagery; ordinary word-based props use separate cues.
                photos=([p for p in private_assets.photos
                         if p.name.startswith("photo_sticker_")]
                        if private_assets is not None and
                        guide_effect in ("image_cluster_reel",
                                         "cutout_grid_reel",
                                         "pov_carousel_spin",
                                         "split_reel") else []),
                background_path=(
                    private_assets.backgrounds.get(
                        "grid_blue" if studio_scene=="pistachio"
                        else "grid_white")
                    if private_assets is not None else None
                )
                )
            except Exception as exc:
                # An automatic accent is optional: if we cannot identify and
                # protect a person, SKIP instead of obscuring them or losing MP4.
                if cue.compact:
                    LOG.warning("Safe small animation skipped: %s",exc)
                    continue
                raise
            args.extend(["-framerate","15","-start_number","0",
                         "-i",pattern])
            fx=f"[guideclip{i}]"
            filters.append(
                f"[{current_input}:v]fps=30,"
                f"scale={frame_width}:{frame_height}:flags=lanczos,"
                f"format=rgba,setpts=PTS-STARTPTS+{cue.start:.3f}/TB{fx}"
            )
            stage=f"[guidestage{i}]"
            filters.append(
                f"{prev}{fx}overlay=x=0:y=0:"
                f"enable='between(t,{cue.start:.3f},{cue.end:.3f})':"
                f"shortest=0:eof_action=pass:repeatlast=0{stage}"
            )
            current_input+=1
            prev=stage
            guide_count+=1
            rendered_guide_cues.append(cue)
        insert_count+=guide_count

        # Uploaded PNGs are never stretched into giant 400px cards.
        # Render each as a small, precise RGBA overlay with dynamic
        # silhouette protection and a verified clear side of the video.
        from semantic_object_overlays import render_safe_object
        object_count=0
        rendered_object_cues=[]
        for i,cue in enumerate(object_cues):
            start,end=cue.start,cue.end
            try:
                pattern,count=render_safe_object(
                    insert_source or source,folder,cue,i,
                    caption_position=caption_position,
                )
            except Exception as exc:
                LOG.warning("Skipping unsafe/unreadable user PNG: %s",exc)
                continue
            args.extend(["-framerate","15","-start_number","0","-i",pattern])
            layer=f"[spokenobject{i}]"
            filters.append(
                f"[{current_input}:v]fps=30,scale={frame_width}:{frame_height}:"
                f"flags=lanczos,format=rgba,"
                f"setpts=PTS-STARTPTS+{start:.3f}/TB{layer}"
            )
            stage=f"[spokenobjectstage{i}]"
            filters.append(
                f"{prev}{layer}overlay=x=0:y=0:"
                f"enable='between(t,{start:.3f},{end:.3f})':"
                f"shortest=0:eof_action=pass:repeatlast=0{stage}"
            )
            prev=stage
            current_input+=1
            object_count+=1
            rendered_object_cues.append(cue)
        insert_count+=object_count

        # Private animated icon MOV, matched to the actual spoken topic.
        private_icon_count=0
        # Uploaded MOV icons are not yet silhouette-masked: never insert
        # them in automatic mode, where they could obscure the speaker.
        # The protected speech-matched PNG path above is the safe default.
        if (private_assets is not None and insert_style=="reference_soft"
                and guide_effect=="off" and not guide_cues):
            for cue in semantic_cues:
                if private_icon_count>=6:
                    break
                if any(cue.start < mc.end+0.2 and cue.end>mc.start-0.2
                       for mc in motion_cues):
                    continue
                media=private_assets.icons.get(cue.kind)
                if media is None or not media.is_file():
                    continue
                start,end=cue.start,cue.end
                if end-start<0.50:
                    continue
                args.extend(["-stream_loop","-1","-t",
                             f"{end-start+0.20:.3f}","-i",str(media)])
                size=max(96,round(225*sx))
                label=f"[privateicon{private_icon_count}]"
                filters.append(
                    f"[{current_input}:v]fps=30,scale={size}:{size},"
                    f"format=rgba,trim=duration={end-start+0.15:.3f},"
                    f"setpts=PTS-STARTPTS+{start:.3f}/TB,"
                    f"fade=t=in:st={start:.3f}:d=0.16:alpha=1,"
                    f"fade=t=out:st={max(start+0.2,end-0.2):.3f}:"
                    f"d=0.18:alpha=1{label}"
                )
                stage=f"[privateiconstage{private_icon_count}]"
                x=f"(main_w-overlay_w)*{0.72 if cue.kind in ('error','inspect') else 0.12}"
                y=f"main_h*{0.24 if cue.kind in ('error','inspect') else 0.34}"
                filters.append(
                    f"{prev}{label}overlay=x='{x}':y='{y}':"
                    f"enable='between(t,{start:.3f},{end:.3f})':"
                    f"shortest=0:eof_action=pass:repeatlast=0{stage}"
                )
                prev=stage
                current_input+=1
                private_icon_count+=1

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
            selected_sound_kind=("typewriter" if caption_sound=="typewriter"
                                 else "pop")
            private_typewriter=(private_assets.sounds.get(selected_sound_kind)
                                if private_assets is not None else None)
            if private_typewriter and private_typewriter.is_file():
                # An uploaded real typewriter is preferred to a synthesized
                # substitute. Each key phrase gets a short copy, never louder
                # than the original speech.
                for i,(t,_) in enumerate(caption_cues[:18]):
                    args.extend(["-i",str(private_typewriter)])
                    label=f"[private_typing{i}]"
                    filters.append(
                        f"[{current_input}:a:0]atrim=duration=0.55,"
                        f"asetpts=PTS-STARTPTS,aresample=48000,"
                        f"volume=0.13,adelay={int(t*1000)}:all=1{label}"
                    )
                    track_inputs.append(label)
                    current_input+=1
                    caption_sfx_count+=1
            else:
                track = folder/"subtitle_pops.wav"
                intensity = ("caption_typewriter" if caption_sound=="typewriter" else
                             "caption_soft" if caption_sound=="soft" else "caption_tick")
                make_sfx_track(track,caption_cues,duration,intensity)
                args.extend(["-i",str(track)])
                track_inputs.append(f"[{current_input}:a:0]")
                current_input += 1
                caption_sfx_count = len(caption_cues)
        if insert_sound=="on" and has_audio and (guide_count or object_count):
            from guide18_fx import GuideCue
            audio=folder/"guide_varied_sfx.wav"
            soundtrack_events=sorted([
                *rendered_guide_cues,
                *[GuideCue("notification_stack",o.start,o.end,o.concept)
                  for o in rendered_object_cues]
            ],key=lambda item:item.start)
            guide_audio(audio,soundtrack_events,duration)
            args.extend(["-i",str(audio)])
            track_inputs.append(f"[{current_input}:a:0]")
            current_input+=1
            insert_sfx_count+=guide_count+object_count
        if insert_sound=="on" and has_audio and studio_insert_count:
            uploaded_whoosh=(private_assets.sounds.get("whoosh")
                             if private_assets is not None else None)
            if uploaded_whoosh and uploaded_whoosh.is_file():
                for i,cue in enumerate(studio_cues[:studio_insert_count]):
                    args.extend(["-i",str(uploaded_whoosh)])
                    label=f"[user_whoosh{i}]"
                    filters.append(
                        f"[{current_input}:a:0]atrim=duration=0.56,"
                        f"asetpts=PTS-STARTPTS,aresample=48000,"
                        f"volume=0.095,adelay={int(cue.start*1000)}:all=1{label}"
                    )
                    track_inputs.append(label)
                    current_input+=1
                    insert_sfx_count+=1
            else:
                # An original synthesized whoosh on every actual moving insert.
                track=folder/"animated_inserts_whoosh.wav"
                make_sfx_track(
                    track,[(c.start,None) for c in studio_cues[:studio_insert_count]],
                    duration,"whoosh"
                )
                args.extend(["-i",str(track)])
                track_inputs.append(f"[{current_input}:a:0]")
                current_input+=1
                insert_sfx_count+=studio_insert_count
        if insert_sound=="on" and has_audio and rendered_vintage:
            track=folder/"vintage_projector_and_film.wav"
            make_vintage_sound_track(track, rendered_vintage, duration)
            args.extend(["-i",str(track)])
            track_inputs.append(f"[{current_input}:a:0]")
            current_input+=1
            insert_sfx_count+=len(rendered_vintage)
        if insert_sound=="on" and has_audio and rendered_retro:
            cue_track=folder/"retro_insert_accents.wav"
            make_retro_sound_track(cue_track, rendered_retro, duration,
                                   style=insert_style)
            args.extend(["-i",str(cue_track)])
            track_inputs.append(f"[{current_input}:a:0]")
            current_input+=1
            insert_sfx_count+=len(rendered_retro)
        # Dramatic trailer accents only when explicitly enabled and
        # meaningful; low-volume against the unchanged original speech.
        if (insert_sound=="on" and has_audio and private_assets is not None
                and insert_style=="reference_soft"):
            for cue in semantic_cues:
                if cue.kind not in ("error","compare"):
                    continue
                wav=private_assets.sounds.get(cue.kind)
                if wav is None or not wav.is_file():
                    continue
                args.extend(["-i",str(wav)])
                label=f"[private_sfx{insert_sfx_count}]"
                milliseconds=int(cue.start*1000)
                filters.append(
                    f"[{current_input}:a:0]atrim=0:0.42,"
                    f"asetpts=PTS-STARTPTS,volume=0.045,"
                    f"adelay={milliseconds}:all=1{label}"
                )
                track_inputs.append(label)
                current_input+=1
                insert_sfx_count+=1
                if insert_sfx_count>=3:break
        if len(track_inputs)>1:
            filters.append(
                "".join(track_inputs)
                + f"amix=inputs={len(track_inputs)}:duration=first:"
                + "normalize=0,alimiter=limit=0.96[mixed]"
            )
            sound_output = "[mixed]"

        if emoji_count or insert_count or scene_count or private_icon_count or object_count:
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
                "guide_effect_count":guide_count,
                "speech_object_count":object_count,
                "guide_effects_rendered":[cue.effect for cue in guide_cues],
                "kinetic_word_count":kinetic_word_count,
                "caption_sfx_count":caption_sfx_count,
                "insert_count":insert_count+scene_count+private_icon_count,
                "insert_sfx_count":insert_sfx_count,
                "semantic_cue_count":len(semantic_cues),
                "private_asset_count":private_icon_count}
