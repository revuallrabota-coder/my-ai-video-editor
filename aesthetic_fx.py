"""Independent Burgundy / Pink Tender semantic graphics, audio and private stock media.

Original Pillow illustrations and synthesized fallback sounds. Third-party clips
are NEVER fetched, bundled or redistributed. A licensed operator may install
reviewed MP4/WAV files under PRIVATE_STYLE_ASSETS_DIR/<style>/ on the renderer.
"""
from __future__ import annotations
from array import array
from pathlib import Path
import math
import os
import random
import re
import wave
from typing import Sequence

from PIL import Image, ImageDraw, ImageFilter
from retro_inserts import RetroCue, _serif

STYLE_THEMES = {
    "burgundy": (
        ("silk", ("шелк", "шёлк", "атлас", "ткан", "бархат", "silk", "velvet"), "fabric"),
        ("bow", ("бант", "лента", "подар", "bow", "ribbon", "gift"), "fabric"),
        ("flower", ("цвет", "роза", "букет", "лепест", "flower", "rose"), "petal"),
        ("cherry", ("вишн", "ягод", "cherry"), "glass"),
        ("seal", ("сургуч", "печать", "штамп", "stamp", "seal"), "seal"),
        ("letter", ("письм", "конверт", "записк", "letter"), "paper"),
        ("heart", ("серд", "любов", "чувств", "heart", "love"), "seal"),
        ("lace", ("кружев", "романтик", "lace"), "fabric"),
        ("perfume", ("дух", "аромат", "парф", "perfume"), "glass"),
        ("chocolate", ("шоколад", "слад", "chocolate"), "paper"),
    ),
    "pink_tender": (
        ("silk", ("нежн", "воздуш", "ткан", "шелк", "шёлк", "silk", "soft"), "air"),
        ("bow", ("бант", "лента", "подар", "bow", "ribbon"), "air"),
        ("pearl", ("жемчуг", "бусин", "жемчуж", "pearl"), "chime"),
        ("flower", ("цвет", "цветоч", "пион", "роз", "букет", "лепест", "flower", "peony"), "petal"),
        ("heart", ("любов", "серд", "мил", "heart", "love"), "chime"),
        ("butterfly", ("бабоч", "butterfly"), "air"),
        ("letter", ("письм", "открытк", "конверт", "letter", "card"), "paper"),
        ("cloud", ("мечт", "сон", "облак", "dream", "cloud"), "air"),
        ("lace", ("кружев", "кружев", "lace"), "fabric"),
        ("ribbon", ("красив", "изящ", "элегант", "elegant"), "air"),
    ),
}
DENSITIES = {
    "burgundy": {"subtle":(12.,2), "balanced":(8.5,4), "dynamic":(5.5,6)},
    "pink_tender":{"subtle":(13.,2), "balanced":(9.,4), "dynamic":(6.5,6)},
}
STYLE_PALETTE = {
    "burgundy": {"paper":(66,21,37,247), "ink":(246,224,214,255),
                 "accent":(191,127,123,255), "second":(91,43,51,255)},
    "pink_tender":{"paper":(253,241,244,242), "ink":(109,73,89,255),
                   "accent":(222,158,184,255), "second":(248,219,229,255)},
}
SUPPORTED_STYLES = ("old_money", "burgundy", "pink_tender")

def select_mood_cues(words:Sequence[tuple[float,float,str]],duration:float,
                     style:str,density:str="balanced") -> list[RetroCue]:
    if style not in STYLE_THEMES or density not in DENSITIES[style]:
        raise ValueError("Unknown aesthetic style or density")
    if duration < 7:
        return []
    gap,limit = DENSITIES[style][density]
    found=[]
    for start,end,word in sorted(words,key=lambda w:float(w[0])):
        t=float(start)
        if float(end)<=t or t < 4.4 or t > duration-1.65: continue
        if found and t-found[-1].time < gap: continue
        token=re.sub(r"[^a-zа-яё0-9]","",str(word).casefold())
        if not token: continue
        match=next(((theme,sound) for theme,stems,sound in STYLE_THEMES[style]
                    if any(token.startswith(stem) for stem in stems)),None)
        if match is None: continue
        theme,sound=match
        found.append(RetroCue(t,str(word).strip()[:22],theme,sound))
        if len(found)>=limit:break
    return found

def _motif(draw:ImageDraw.ImageDraw,theme:str,style:str,ink,accent)->None:
    x,y=240,158
    if theme in ("bow","ribbon","silk"):
        draw.polygon([(x,y),(x-110,y-60),(x-95,y+55)],outline=ink)
        draw.polygon([(x,y),(x+110,y-60),(x+95,y+55)],outline=ink)
        draw.ellipse((x-19,y-19,x+19,y+19),fill=accent)
        draw.polygon([(x-14,y+22),(x-38,y+99),(x,y+65)],outline=accent)
        draw.polygon([(x+14,y+22),(x+38,y+99),(x,y+65)],outline=accent)
    elif theme in ("flower","butterfly"):
        for i in range(6):
            a=i*math.pi/3
            px=x+51*math.cos(a);py=y+51*math.sin(a)
            draw.ellipse((px-44,py-44,px+44,py+44),outline=ink,width=4)
        draw.ellipse((x-22,y-22,x+22,y+22),fill=accent)
    elif theme=="heart":
        draw.polygon([(x,y+95),(x-105,y-9),(x-90,y-68),(x-37,y-80),
                      (x,y-45),(x+37,y-80),(x+90,y-68),(x+105,y-9)],
                     fill=accent,outline=ink)
    elif theme=="pearl":
        for i in range(12):
            a=math.pi+(i/11)*math.pi
            xx=x+91*math.cos(a); yy=y-55*math.sin(a)
            draw.ellipse((xx-14,yy-14,xx+14,yy+14),fill=(255,252,247,255),
                         outline=accent,width=3)
    elif theme=="cherry":
        for xx in (x-52,x+43):
            draw.ellipse((xx-42,y-7,xx+42,y+78),fill=accent,outline=ink,width=4)
            draw.arc((xx-15,y-73,xx+57,y+25),145,270,fill=ink,width=4)
        draw.line((x-52,y-3,x+2,y-106,x+43,y-5),fill=ink,width=4)
    elif theme=="seal":
        draw.ellipse((x-85,y-85,x+85,y+85),fill=(142,38,55,255),outline=accent,width=6)
        draw.ellipse((x-57,y-57,x+57,y+57),outline=ink,width=4)
        draw.polygon([(x,y-44),(x+14,y-12),(x+51,y-9),(x+23,y+13),
                      (x+30,y+48),(x,y+25),(x-30,y+48),(x-23,y+13),
                      (x-51,y-9),(x-14,y-12)],outline=ink)
    elif theme=="letter":
        draw.rectangle((x-105,y-64,x+105,y+83),outline=ink,width=5)
        draw.line((x-105,y-64,x,y+16,x+105,y-64),fill=accent,width=5)
        draw.ellipse((x-19,y,x+19,y+38),fill=accent)
    elif theme=="lace":
        for dx in range(-96,97,32):
            for dy in range(-55,56,30):
                draw.ellipse((x+dx-15,y+dy-15,x+dx+15,y+dy+15),
                             outline=ink,width=2)
    elif theme=="perfume":
        draw.rounded_rectangle((x-72,y-42,x+72,y+96),radius=18,outline=ink,width=7)
        draw.rectangle((x-21,y-88,x+21,y-42),fill=accent)
        draw.ellipse((x-18,y+6,x+18,y+43),outline=accent,width=3)
    elif theme=="chocolate":
        for i in range(3):
            for j in range(3):
                draw.rounded_rectangle((x-88+i*59,y-80+j*59,
                                         x-34+i*59,y-26+j*59),
                                       radius=4,outline=ink,width=4)
    else:
        for radius in (38,65,84):
            draw.arc((x-radius,y-radius,x+radius,y+radius),190,350,fill=ink,width=4)

def render_mood_card(target:Path,label:str,theme:str,style:str)->None:
    if style not in STYLE_THEMES or theme not in {t for t,_,_ in STYLE_THEMES[style]}:
        raise ValueError("Unknown aesthetics or graphic motif")
    p=STYLE_PALETTE[style]
    image=Image.new("RGBA",(480,382),(0,0,0,0))
    shade=Image.new("RGBA",(480,382),(0,0,0,0))
    ImageDraw.Draw(shade).rounded_rectangle((31,24,449,352),radius=27,fill=(19,7,12,60))
    image.alpha_composite(shade.filter(ImageFilter.GaussianBlur(13)))
    panel=Image.new("RGBA",(480,382),(0,0,0,0))
    d=ImageDraw.Draw(panel)
    d.rounded_rectangle((31,17,449,348),radius=24,fill=p["paper"],
                        outline=p["accent"],width=3)
    d.rounded_rectangle((42,28,438,337),radius=19,outline=p["accent"],width=1)
    _motif(d,theme,style,p["ink"],p["accent"])
    d.line((72,278,408,278),fill=p["accent"],width=2)
    label=re.sub(r"[\r\n{}]","",str(label)).strip().upper()[:22]
    if label:
        size=37
        f=_serif(size)
        while d.textbbox((0,0),label,font=f)[2]>355 and size>18:
            size-=2
            f=_serif(size)
        d.text((240,312),label,font=f,fill=p["ink"],anchor="mm")
    image.alpha_composite(panel)
    target.parent.mkdir(parents=True,exist_ok=True)
    image.save(target)

# Source material MUST be pre-approved and stored outside GitHub; predictable names.
# Also supports Old Money. Never use URLs or untrusted names from a subtitle.
ASSET_NAMES={
    "old_money":{"coffee","book","letter","watch","vinyl","phone","flower",
                 "pearl","architecture","ribbon","typewriter","documents","keyhole","door"},
    "burgundy":{x[0] for x in STYLE_THEMES["burgundy"]},
    "pink_tender":{x[0] for x in STYLE_THEMES["pink_tender"]},
}
def resolve_mood_asset(style:str,theme:str,ext:str)->Path|None:
    if style not in ASSET_NAMES or theme not in ASSET_NAMES[style]:
        return None
    if ext not in ("mp4","wav"): return None
    root=os.environ.get("PRIVATE_STYLE_ASSETS_DIR","").strip()
    if not root:return None
    base=Path(root).expanduser().resolve()
    candidate=(base/style/f"{theme}.{ext}").resolve()
    if not candidate.is_relative_to(base) or not candidate.is_file():
        return None
    if candidate.stat().st_size<64:return None
    return candidate

def make_mood_sound_track(target:Path,cues:Sequence[RetroCue],duration:float,
                           style:str,rate:int=24000)->None:
    """Quiet style-specific fallback for cues WITHOUT uploaded licensed audio."""
    if style not in SUPPORTED_STYLES: raise ValueError("Unsupported style")
    count=max(1,int(duration*rate))
    data=array("h",[0])*count
    strength={"old_money":0.053,"burgundy":0.068,"pink_tender":0.041}[style]
    for n,cue in enumerate(cues):
        start=max(0,int(cue.time*rate))
        if start>=count:continue
        rng=random.Random(f"{style}/{cue.symbol}/{n}")
        kind=cue.sound
        length=min(count-start,int((0.33 if style!="burgundy" else 0.37)*rate))
        for j in range(length):
            t=j/rate
            envelope=(1-math.exp(-t*62))*math.exp(-t*(13 if style=="pink_tender" else 16))
            noise=2*rng.random()-1
            if style=="pink_tender":
                sound=(0.54*math.sin(2*math.pi*880*t)+
                       0.23*math.sin(2*math.pi*1320*t)+0.08*noise)
                if kind in ("air","fabric","petal"):sound=0.26*noise+0.18*math.sin(2*math.pi*(370+120*t)*t)
            elif style=="burgundy":
                sound=(0.37*noise+0.2*math.sin(2*math.pi*118*t))
                if kind=="glass":sound=0.52*math.sin(2*math.pi*910*t)
                if kind=="seal":sound=0.53*noise+0.4*math.sin(2*math.pi*93*t)
            else:
                sound=0.25*noise+0.4*math.sin(2*math.pi*510*t)
                if kind in ("paper","stamp"):sound=0.52*noise
                if kind=="tick":sound=0.42*noise+0.4*math.sin(2*math.pi*820*t)
            val=int(32767*strength*envelope*sound)
            pos=start+j
            data[pos]=max(-32760,min(32760,data[pos]+val))
    target.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(target),"wb") as wf:
        wf.setnchannels(1);wf.setsampwidth(2);wf.setframerate(rate)
        wf.writeframes(data.tobytes())
