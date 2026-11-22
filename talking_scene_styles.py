"""Two original art-directed talking-head Reels scenes.

Contour: muted deep-green topographic lines and cream hand-drawn accents.
Cream: warm ivory background, dark type and a rounded speaker portrait.
Both scenes keep spoken-word timings, original voice and optional camera edits.
No third-party watermarks, footage, proprietary preset files or logos.
"""
from __future__ import annotations

import math
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from export_profiles import get_export_profile
from signature_captions import ass_color, ass_time, safe_text
from reference_cascade_captions import oval_path
from reference_dynamic_captions import phrase_groups

VALID_TALK_SCENES = ("off", "contour", "cream")
STUDIO_CAPTION_POS = "studio"


def validate_talk_scene(name: str) -> str:
    if name not in VALID_TALK_SCENES:
        raise ValueError("Неизвестная композиция разговорного Reels.")
    return name


def _background(name: str, size: tuple[int, int]) -> Image.Image:
    w, h = size
    scale = w / 720
    if name == "contour":
        image = Image.new("RGB", (w, h), (27, 43, 37))
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        pen = ImageDraw.Draw(overlay, "RGBA")
        # A wholly original contour-wave field, rather than copying textures
        # or visible branding from the reference.
        for origin in range(-180, 1500, 21):
            points = []
            for x in range(-40, 765, 5):
                y = (origin
                     + 36 * math.sin((x + origin * .12) / 79.0)
                     + 15 * math.sin(x / 31.0 + origin / 160.0))
                points.append((round(x * scale), round(y * h / 1280)))
            pen.line(points, fill=(150, 192, 166, 41), width=max(1, round(scale)))
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    else:
        image = Image.new("RGB", (w, h), (255, 239, 190))
        pen = ImageDraw.Draw(image)
        rand = random.Random(37)
        for _ in range(int(w * h / 160)):
            x, y = rand.randrange(w), rand.randrange(h)
            v = rand.choice((246, 250, 255))
            pen.point((x, y), fill=(v, min(250, v-7), 194))
        # Very subtle offset paper circles: no copyright-protected stickers.
        pen.arc((round(-70*scale),round(35*scale),
                 round(210*scale),round(290*scale)),
                start=190,end=327,fill=(218,199,150),width=max(1,round(scale*2)))
    return image


def _arch_mask(size: tuple[int, int]) -> Image.Image:
    w,h=size
    mask = Image.new("L", (w, h), 0)
    px = mask.load()
    # Curved upper edge with straight sides and bottom, like an editorial arch.
    for x in range(w):
        relative = abs((x-(w-1)/2)/((w-1)/2))
        top = round(h * .155 * (1-math.sqrt(max(0.,1-relative**2))))
        for y in range(top,h):
            px[x,y] = 255
    return mask.filter(ImageFilter.GaussianBlur(max(.7,w/750)))


def render_scene(source: Path, output: Path, name: str,
                 *, quality: str = "high") -> None:
    """Replace the plain full-frame source with the visual scene.

    This stage runs BEFORE ASS subtitle animation.  Text therefore sits on
    the unobstructed designed upper area and never crosses the portrait.
    """
    validate_talk_scene(name)
    if name == "off":
        raise ValueError("Обычная сцена не требует отдельной композиции.")
    from telegram_editor import duration_and_audio
    duration, has_audio = duration_and_audio(source)
    if duration <= 0:
        raise ValueError("Исходное видео не содержит кадров.")
    profile = get_export_profile(quality)
    w,h=profile.width,profile.height
    offset = round(h * .37)
    person_height = h - offset
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="talk_scene_") as directory:
        folder=Path(directory)
        bg=folder/"background.png"
        mask=folder/"arch_mask.png"
        _background(name,(w,h)).save(bg)
        _arch_mask((w,person_height)).save(mask)
        # Scale the original source to the scene width; portrait-window
        # crop gently favors the upper half (eyes rather than empty floor).
        filter_complex=(
            f"[0:v]fps=30,scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{person_height}:(iw-{w})/2:(ih-{person_height})*0.30,"
            f"setsar=1,format=rgba[portrait];"
            f"[2:v]format=gray[alpha];"
            f"[portrait][alpha]alphamerge[arch];"
            f"[1:v][arch]overlay=0:{offset}:shortest=1:format=auto,"
            "format=yuv420p[v]"
        )
        cmd=["ffmpeg","-hide_banner","-loglevel","error","-y",
             "-i",str(source),
             "-loop","1","-framerate","30","-i",str(bg),
             "-loop","1","-framerate","30","-i",str(mask),
             "-filter_complex",filter_complex,
             "-map","[v]","-map","0:a:0?",
             "-c:v","libx264","-preset",profile.preset,
             "-crf",str(profile.crf),"-pix_fmt","yuv420p",
             "-c:a","copy","-t",f"{duration:.3f}",
             "-movflags","+faststart",str(output)]
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=2400)
        if p.returncode or not output.is_file():
            raise RuntimeError(
                "Не удалось собрать сцену разговорного Reels: "+
                p.stderr[-450:]
            )


def append_scene_ornaments(
    ass_file: Path,
    words: list[tuple[float, float, str]],
    name: str,
) -> int:
    """Add at most a few *speech-grounded* stickers in the unused top area.

    No periodic stickers, random words, fake phone screenshots, big retro cards
    or icons based on generic job titles. Optional scene embellishments must
    always have a specific conversational reason. Timings follow approved
    transcript; no effect is allowed to cover the speaker's arched portrait.
    """
    validate_talk_scene(name)
    if name == "off" or not words:
        return 0
    from semantic_editing import choose_semantic_cues
    duration = max(float(end) for _, end, _ in words)
    cues = choose_semantic_cues(words, duration, density="subtle")
    if not cues:
        return 0
    script = ass_file.read_text("utf-8")
    if "\n[Events]" not in script:
        raise ValueError("Нет секции Events в субтитрах.")
    dark = name == "cream"
    ink = ass_color("#1F2420" if dark else "#FFF6E6")
    sticker = ass_color("#262F2A" if not dark else "#FDF8E8")
    letters = ass_color("#FFF6E6" if not dark else "#252520")
    definition = (
        f"Style: TalkBadge,Lato,24,{letters},{letters},"
        "&H00000000,&H00000000,1,0,0,0,100,100,"
        "0,0,1,0,0,5,20,20,10,1\n"
        f"Style: TalkDraw,DejaVu Sans,20,{ink},{ink},"
        f"{ink},&H00000000,0,0,0,0,100,100,"
        "0,0,1,0,0,5,0,0,0,1\n"
    )
    script=script.replace("\n[Events]", "\n"+definition+"\n[Events]", 1)
    events=[]
    max_badges = 1 if duration < 15 else 2 if duration < 45 else 3
    last=-100.0
    for cue in cues:
        if len(events)//2>=max_badges or cue.start-last<5.0:
            continue
        # Label is the *actual spoken word* recognized and checked in Telegram.
        label=safe_text(cue.label).upper()
        if not label or len(label)>13:
            continue
        start=max(0.0, cue.start)
        end=min(duration, start+1.3)
        if end-start<.45:
            continue
        width=max(86,min(183, int(len(label)*13+38)))
        center_x=139 if len(events)%4==0 else 578
        y=383
        x=center_x-width//2
        pill=oval_path(width,46)
        capsule=(r"\an7\p1\bord0\blur.4"
                 +rf"\1c{sticker}\fad(270,220)"
                 +rf"\move({x},{y+8},{x},{y},0,290)")
        events.append(
            f"Dialogue: 1,{ass_time(start)},{ass_time(end)},"
            f"TalkDraw,,0,0,0,,{{{capsule}}}{pill}{{\\p0}}\n"
        )
        tag=(rf"\an5\pos({center_x},{y+23})"
             +rf"\fad(280,240)\fs{21 if len(label)<10 else 17}"
             +rf"\c{letters}\blur.15")
        events.append(
            f"Dialogue: 2,{ass_time(start)},{ass_time(end)},"
            f"TalkBadge,,0,0,0,,{{{tag}}}{label}\n"
        )
        last=start
    if events:
        ass_file.write_text(script+"".join(events), encoding="utf-8")
    return len(events)//2
