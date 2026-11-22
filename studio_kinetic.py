"""Speech-timed picture inserts and kinetic editorial accents for talking Reels.

Unlike a static background template, these short motion cards show frames from
the user's own uncaptioned footage. They are generated at transcript phrase
boundaries and never contain unrelated stock images or fabricated claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont, ImageOps

from reference_dynamic_captions import phrase_groups
from reference_motion_scenes import _frame

Word = tuple[float, float, str]
PALETTES = {
    "contour": ((34, 57, 49), (243, 232, 210), (181, 205, 174)),
    "cream": ((252, 238, 205), (39, 34, 32), (209, 152, 136)),
    "pistachio": ((222, 235, 198), (41, 73, 48), (124, 155, 108)),
    "burgundy_brown": ((82, 38, 53), (245, 220, 205), (155, 108, 90)),
}

@dataclass(frozen=True)
class KineticCue:
    start: float
    end: float
    label: str


def select_studio_cues(
    words: Sequence[Word], duration: float, density: str = "balanced",
) -> list[KineticCue]:
    """Return visual cutaways by phrase rhythm, not by a list of magic words."""
    if density not in ("subtle", "balanced", "dynamic"):
        raise ValueError("Недопустимая частота динамических вставок.")
    gap={"subtle":9.0,"balanced":6.0,"dynamic":4.4}[density]
    max_count={"subtle":7,"balanced":12,"dynamic":18}[density]
    selected=[]
    last=-gap
    for group in phrase_groups(words):
        if len(group)<2:
            continue
        start=max(0.,float(group[0][0]))
        if start<2.4 or start>duration-1.8 or start-last<gap:
            continue
        words_clean=[]
        for _,_,raw in group:
            token=re.sub(r"[^\wА-Яа-яЁё-]","",str(raw)).strip()
            if len(token)>=4:
                words_clean.append(token)
        if not words_clean:
            continue
        # Only an actually spoken word, never an arbitrary marketing tagline.
        label=max(words_clean,key=len).upper()[:20]
        end=min(duration-.08,start+1.75)
        if end-start<1.0:
            continue
        selected.append(KineticCue(start,end,label))
        last=start
        if len(selected)>=max_count:
            break
    return selected


def _font(size: int, bold: bool=True):
    path=("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
          if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    try:
        return ImageFont.truetype(path,size)
    except OSError:
        return ImageFont.load_default()


def make_studio_card(
    video: Path, output: Path, cue: KineticCue, scene: str,
) -> None:
    """An animated video-frame cutaway card: theme + real still + spoken word."""
    if scene not in PALETTES:
        raise ValueError("Неизвестный формат графики.")
    bg, ink, accent=PALETTES[scene]
    w,h=350,430
    card=Image.new("RGBA",(w,h),(0,0,0,0))
    draw=ImageDraw.Draw(card)
    draw.rounded_rectangle((6,6,w-7,h-7),radius=25,fill=(*bg,248),
                           outline=(*accent,255),width=3)
    photo=_frame(video,cue.start+.12,320,286).convert("RGBA")
    mask=Image.new("L",photo.size,0)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,319,285),radius=17,fill=255)
    card.paste(photo,(15,15),mask)
    draw=ImageDraw.Draw(card)
    draw.rounded_rectangle((18,325,w-18,398),radius=15,
                           fill=(*bg,255),outline=(*accent,150),width=1)
    size=34
    while size>17 and draw.textbbox((0,0),cue.label,font=_font(size))[2]>295:
        size-=2
    draw.text((w//2,362),cue.label,fill=(*ink,255),
              anchor="mm",font=_font(size))
    # Animated graphically at render-time, but underlying content is real.
    draw.line((21,409,w-21,409),fill=(*accent,240),width=5)
    output.parent.mkdir(parents=True,exist_ok=True)
    card.save(output)
