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


def append_scene_ornaments(ass_file: Path,
                           words: list[tuple[float,float,str]],
                           name: str) -> None:
    """Add tasteful fading word-stickers and hand-drawn arcs.

    Sticker labels come solely from the transcript, not generated claims.
    Pure ASS graphics share the same timeline as existing moving captions.
    """
    validate_talk_scene(name)
    if name=="off" or not words:
        return
    script=ass_file.read_text("utf-8")
    if "[Events]" not in script:
        raise ValueError("Нет секции Events в субтитрах.")
    dark=(name=="cream")
    ink=ass_color("#171711" if dark else "#FFFFFF")
    panel=ass_color("#171711" if not dark else "#FFFFFF")
    panel_text=ass_color("#FFF8D8" if not dark else "#161611")
    # Add styles before [Events], so stickers work with all existing presets.
    definition=(
        f"Style: TalkBadge,Lato,24,{panel_text},{panel_text},"
        "&H00000000,&H00000000,1,0,0,0,100,100,"
        "0,0,1,0,0,5,20,20,10,1\n"
        f"Style: TalkDraw,DejaVu Sans,20,{ink},{ink},"
        f"{ink},&H00000000,0,0,0,0,100,100,"
        "0,0,1,0,0,5,0,0,0,1\n"
    )
    script=script.replace("\n[Events]", "\n"+definition+"\n[Events]",1)
    groups=phrase_groups(words)
    events=[]
    for i,group in enumerate(groups):
        if i%3!=1 or not group:
            continue
        start=max(0.0,group[0][0]+.10)
        end=max(start+.65,min(group[-1][1]+.40,start+2.0))
        candidate=max(group,key=lambda entry:len(safe_text(entry[2])))
        word=safe_text(candidate[2]).upper().strip()
        if not word or len(word)>14:
            continue
        width=max(95,min(205,round(len(word)*15+37)))
        x=128 if i%2 else 580
        y=423 if name=="contour" else 430
        x0=x-width//2
        fill=panel
        alpha=(r"\an7\p1\bord0\blur.4"
               +rf"\1c{fill}\fad(260,230)"
               +rf"\move({x0},{y-16},{x0},{y},0,260)")
        pill=oval_path(width,48)
        events.append(
            f"Dialogue: 1,{ass_time(start)},{ass_time(end)},"
            f"TalkDraw,,0,0,0,,{{{alpha}}}{pill}{{\\p0}}\n"
        )
        text_prefix=(
            r"\an5"+rf"\pos({x},{y+24})"
            +rf"\fad(280,230)\fs{max(15,24-round(max(0,len(word)-9)*1.5))}"
            +rf"\c{panel_text}\blur.15"
        )
        events.append(
            f"Dialogue: 2,{ass_time(start)},{ass_time(end)},"
            f"TalkBadge,,0,0,0,,{{{text_prefix}}}{word}\n"
        )
        # Hand-drawn accent: one gently animated curved stroke, not a
        # constantly flashing graphic or a giant opaque rectangle.
        if i%2==1:
            path="m 0 16 b 29 -6 63 -3 91 16 b 108 29 133 22 155 2"
            cx=425 if dark else 380
            stroke=(r"\an7\p1\1a&HFF&\bord2.6"
                    +rf"\3c{ink}\blur.6"
                    +rf"\move({cx-7},363,{cx},360,0,320)"
                    +r"\fad(270,280)")
            events.append(
                f"Dialogue: 1,{ass_time(start)},{ass_time(end)},"
                f"TalkDraw,,0,0,0,,{{{stroke}}}{path}{{\\p0}}\n"
            )
    if name=="cream":
        # An original stylized mini-interface, not a screenshot of a third-party
        # app. It appears only if the actual speech mentions an app, bot,
        # video, upload or subtitles. No misleading random insert cards.
        shown=0
        for group in groups:
            if shown>=2:break
            matched=next((
                safe_text(raw).upper() for _,_,raw in group
                if any(stem in safe_text(raw).lower() for stem in
                       ("бот","монтаж","видео","прилож","загруз","субтитр"))
            ),None)
            if not matched or len(matched)>13:
                continue
            start=max(0.,float(group[0][0]))
            end=min(start+2.3,max(start+1.1,float(group[-1][1])+.55))
            origin_x,origin_y=504,465
            bg=(r"\an7\p1\bord1\blur1"
                +r"\1c&H00F9F7F2&\3c&H00B9B5A5&"
                +r"\fad(320,280)"
                +rf"\move({origin_x+15},{origin_y+12},{origin_x},{origin_y},0,360)")
            events.append(
                f"Dialogue: 3,{ass_time(start)},{ass_time(end)},"
                f"TalkDraw,,0,0,0,,{{{bg}}}{oval_path(172,215)}{{\\p0}}\n"
            )
            text_tag=(r"\an5\c&H00282317&\b1\fs19"
                      +rf"\pos({origin_x+86},{origin_y+61})\fad(380,280)")
            events.append(
                f"Dialogue: 4,{ass_time(start)},{ass_time(end)},"
                f"TalkBadge,,0,0,0,,{{{text_tag}}}{matched}\n"
            )
            # Simple animated pink action bar in the mockup.
            btn=(r"\an7\p1\bord0"
                 +r"\1c&H00712BCD&\fad(430,330)"
                 +rf"\pos({origin_x+20},{origin_y+140})")
            events.append(
                f"Dialogue: 4,{ass_time(start)},{ass_time(end)},"
                f"TalkDraw,,0,0,0,,{{{btn}}}{oval_path(132,29)}{{\\p0}}\n"
            )
            shown+=1
    ass_file.write_text(script+"".join(events),encoding="utf-8")
