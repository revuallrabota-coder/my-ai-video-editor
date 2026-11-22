"""Four original art-directed talking-head Reels scenes.

Contour: dark green topographic lines, Cream: warm ivory paper.
Pistachio: soft sage green with forest-green fine line art.
Burgundy Brown: deep wine-to-cocoa gradient with restrained warm highlights.
All scenes keep spoken-word timings, original voice and optional camera edits.
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

VALID_TALK_SCENES = ("off", "contour", "cream", "pistachio", "burgundy_brown")
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
    elif name == "pistachio":
        # Soft pistachio paper with understated olive contour lines.
        image = Image.new("RGB", (w, h), (220, 231, 197))
        pen = ImageDraw.Draw(image)
        for origin in range(-160, 800, 27):
            points = []
            for x in range(-20, 760, 6):
                y = origin + 18 * math.sin(x / 91 + origin / 125)
                points.append((round(x * scale), round(y * h / 1280)))
            pen.line(points, fill=(185, 200, 164), width=max(1, round(scale)))
        pen.arc((round(454*scale), round(54*h/1280),
                 round(686*scale), round(290*h/1280)),
                200, 355, fill=(82, 111, 76), width=max(2, round(2*scale)))
    elif name == "burgundy_brown":
        # Two-color burgundy/chocolate gradient, no metallic-text overload.
        image = Image.new("RGB", (w, h), (70, 29, 45))
        pen = ImageDraw.Draw(image)
        for y in range(h):
            t = y / max(1, h-1)
            mix = .20 + .58 * t
            burgundy = (75, 27, 46)
            chocolate = (79, 51, 41)
            color = tuple(round(a*(1-mix)+b*mix)
                          for a,b in zip(burgundy, chocolate))
            pen.line(((0,y),(w,y)), fill=color)
        # Large, almost invisible curves produce visual depth, not stickers.
        for i in range(7):
            inset = round((38 + i*27)*scale)
            pen.arc((inset, round((62+i*15)*h/1280),
                     w+round(140*scale)+inset, round((870+i*65)*h/1280)),
                    150, 297, fill=(125, 84, 75),
                    width=max(1, round(scale)))
        pen.line([(round(73*scale),round(343*h/1280)),
                  (round(647*scale),round(343*h/1280))],
                 fill=(158, 113, 97), width=max(1, round(scale)))
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
    """Keep the talking person FULL FRAME in a real 9:16 Reels composition.

    A translucent palette gradient lives only behind the moving text in the
    upper area. The underlying person, camera and room remain visible through
    it; there is no small square video, static arch or crop of the lower body.
    Additional editorial motion/photo inserts are added later in reels_effects.
    """
    validate_talk_scene(name)
    if name == "off":
        raise ValueError("No composition needed for ordinary mode.")
    from telegram_editor import duration_and_audio
    duration, _ = duration_and_audio(source)
    if duration <= 0:
        raise ValueError("Исходное видео не содержит кадров.")
    profile = get_export_profile(quality)
    w, h = profile.width, profile.height
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="talk_scene_") as directory:
        folder = Path(directory)
        # Draw original colors/lines, then gradually reveal the real video.
        base = _background(name, (w, h)).convert("RGBA")
        alpha = Image.new("L", (w, h), 0)
        alpha_data = alpha.load()
        solid = round(h * .22)
        bottom = round(h * .45)
        for y in range(bottom):
            opacity = 226 if y < solid else round(
                226 * (1 - (y-solid)/max(1,bottom-solid))**1.4
            )
            for x in range(w):
                alpha_data[x, y] = max(0, opacity)
        base.putalpha(alpha)
        graphic = folder / "transparent_talk_palette.png"
        base.save(graphic)
        filter_complex = (
            f"[0:v]fps=30,scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:(iw-{w})/2:(ih-{h})/2,setsar=1,format=rgba[portrait];"
            "[1:v]format=rgba[palette];"
            "[portrait][palette]overlay=0:0:shortest=1:format=auto,"
            "format=yuv420p[v]"
        )
        cmd = [
            "ffmpeg","-hide_banner","-loglevel","error","-y",
            "-i",str(source),"-loop","1","-framerate","30","-i",str(graphic),
            "-filter_complex",filter_complex,"-map","[v]","-map","0:a:0?",
            "-c:v","libx264","-preset",profile.preset,
            "-crf",str(profile.crf),"-pix_fmt","yuv420p",
            "-c:a","copy","-t",f"{duration:.3f}",
            "-movflags","+faststart",str(output),
        ]
        result = subprocess.run(cmd,capture_output=True,text=True,timeout=2400)
        if result.returncode or not output.is_file():
            raise RuntimeError(
                "Не удалось собрать полноэкранный разговорный Reels: "
                +result.stderr[-450:]
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
    theme={
        "contour": ("#FFF2DE", "#263F36", "#FFF2DE"),
        "cream": ("#29251F", "#FFF8E9", "#29251F"),
        "pistachio": ("#314C38", "#F7F5E5", "#314C38"),
        "burgundy_brown": ("#F2DDD0", "#633E34", "#FFF2E5"),
    }
    pen_hex, sticker_hex, letters_hex = theme[name]
    ink = ass_color(pen_hex)
    sticker = ass_color(sticker_hex)
    letters = ass_color(letters_hex)
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
