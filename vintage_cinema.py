"""Original speech-timed vintage-cinema overlays and sounds.

No Pinterest or third-party stock files are redistributed. A cutaway covers the
whole picture while the original speech continues; text comes only from the
user-approved transcription. No graphics before the first five seconds.
"""
from __future__ import annotations
from array import array
from dataclasses import dataclass
import math
import random
import re
import wave
from pathlib import Path
from typing import Sequence
from PIL import Image, ImageDraw, ImageFont

FPS = 12
SIZE = (720, 1280)
THEMES = (
    ("clock", ("врем", "минут", "секунд", "часов", "быстро", "скорост")),
    ("film", ("съём", "съем", "монтаж", "кадр", "фильм", "кино", "сним", "анимац")),
    ("letter", ("письм", "сообщен", "истори", "вспомин", "памят", "рассказ")),
    ("book", ("учеб", "обуч", "урок", "курс", "знан", "схем", "правил")),
    ("inspection", ("ошиб", "проблем", "недостат", "неправ", "разбор", "проверк")),
    ("detail", ("маникюр", "ногт", "кутикул", "френч", "покрыт", "гел", "детал")),
    ("result", ("результ", "готов", "разниц", "сравн", "получил", "итог")),
)

@dataclass(frozen=True)
class VintageCue:
    start: float
    end: float
    phrase: str
    theme: str
    scene: int

def select_vintage_cues(words: Sequence[tuple[float,float,str]], duration: float,
                        density: str = "balanced") -> list[VintageCue]:
    """Choose only spoken concepts and quote the actual words of that passage."""
    if density not in ("subtle","balanced","dynamic"):
        raise ValueError("Unsupported vintage scene density")
    if duration < 11:
        return []
    gap={"subtle":18.,"balanced":13.,"dynamic":10.}[density]
    limit={"subtle":2,"balanced":4,"dynamic":5}[density]
    ordered=sorted(((float(a),float(b),str(w).strip()) for a,b,w in words
                    if b>a and str(w).strip()),key=lambda x:x[0])
    result=[]
    last=-gap
    for idx,(start,end,word) in enumerate(ordered):
        if start<5.2 or start>duration-3.0 or start-last<gap:
            continue
        clean=re.sub(r"[^0-9a-zа-яё]","",word.casefold())
        theme=next((name for name,roots in THEMES
                    if any(root in clean for root in roots)),None)
        if theme is None:
            continue
        quoted=[word]
        for another,_,token in ordered[idx+1:idx+7]:
            if another>start+1.45 or sum(len(x)+1 for x in quoted)+len(token)>38:
                break
            quoted.append(token)
        length=min(2.2,max(1.55,.32*len(quoted)+.70))
        if start+length>=duration-.6:
            continue
        result.append(VintageCue(start,start+length," ".join(quoted),theme,len(result)%3))
        last=start
        if len(result)>=limit:
            break
    return result

def _font(size, bold=False):
    paths=[
        "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path,size)
        except OSError:
            continue
    return ImageFont.load_default()

def _draw_icon(d,theme,x,y,c):
    # Hand-built film-era pictograms, never random emoji or generated lettering.
    if theme=="clock":
        d.ellipse((x-34,y-34,x+34,y+34),outline=c,width=3)
        d.line((x,y,x,y-21),fill=c,width=3)
        d.line((x,y,x+18,y+12),fill=c,width=3)
    elif theme=="film":
        d.rounded_rectangle((x-43,y-25,x+43,y+25),radius=3,outline=c,width=3)
        for z in range(-32,40,15):
            d.rectangle((x+z,y-23,x+z+7,y-14),fill=c)
            d.rectangle((x+z,y+14,x+z+7,y+23),fill=c)
    elif theme=="letter":
        d.rectangle((x-38,y-25,x+38,y+25),outline=c,width=3)
        d.line((x-38,y-25,x,y+5,x+38,y-25),fill=c,width=3)
    elif theme=="book":
        d.line((x-39,y-27,x-8,y-23,x,y-16,x+8,y-23,x+39,y-27),fill=c,width=4)
        d.line((x-39,y-27,x-39,y+23,x-8,y+27,x,y+34,x+8,y+27,x+39,y+23,x+39,y-27),fill=c,width=3)
        d.line((x,y-16,x,y+34),fill=c,width=3)
    elif theme=="detail":
        d.ellipse((x-35,y-35,x+20,y+20),outline=c,width=4)
        d.line((x+11,y+14,x+39,y+42),fill=c,width=7)
    elif theme=="inspection":
        d.ellipse((x-25,y-25,x+25,y+25),outline=c,width=3)
        d.line((x,y-11,x,y+9),fill=c,width=4)
        d.ellipse((x-2,y+16,x+2,y+20),fill=c)
    else:
        d.line((x-25,y+1,x-5,y+20,x+30,y-19),fill=c,width=5)

def _scene_image(cue, frame, index):
    w,h=SIZE
    dark=cue.scene!=1
    rng=random.Random(927+index*193+frame)
    image=Image.new("RGB",SIZE,(31,27,25) if dark else (225,205,164))
    d=ImageDraw.Draw(image)
    for _ in range(1300):
        x=rng.randrange(w); y=rng.randrange(h); r=rng.randrange(1,4)
        if dark:
            v=rng.randrange(62,114);color=(v,v-4,v-10)
        else:
            color=(rng.randrange(155,190),rng.randrange(133,168),rng.randrange(102,130))
        d.ellipse((x,y,x+r,y+r),fill=color)
    ink=(242,223,187) if dark else (66,49,35)
    fine=(123,101,79) if dark else (133,102,69)
    if dark:
        d.line((61,0,61,h),fill=fine,width=2)
        d.line((w-61,0,w-61,h),fill=fine,width=2)
        for y in range(35,h-20,89):
            for x in (20,w-48):
                d.rounded_rectangle((x,y,x+28,y+44),radius=6,fill=(12,11,12))
        d.rectangle((81,159,w-81,h-158),outline=fine,width=3)
        d.rectangle((90,171,w-90,h-170),outline=fine,width=1)
        d.line((100,213,w-100,213),fill=fine,width=2)
        d.line((100,h-217,w-100,h-217),fill=fine,width=2)
    else:
        d.rectangle((42,78,w-42,h-79),outline=(130,92,59),width=3)
        d.rectangle((52,88,w-52,h-89),outline=(172,134,91),width=2)
    _draw_icon(d,cue.theme,w//2,375,fine)
    font=_font(58,True)
    pieces=cue.phrase.upper().split()
    lines=[]
    for item in pieces:
        if not lines:
            lines.append(item)
        elif d.textbbox((0,0),lines[-1]+" "+item,font=font)[2]<=492:
            lines[-1]+=" "+item
        else:
            lines.append(item)
    # Every displayed word is from this clip's approved transcription.
    lines=lines[:3]
    ypos=574-(len(lines)-1)*39+round(10*math.sin(frame/FPS*2))
    for line in lines:
        d.text((w//2,ypos),line,font=font,anchor="mm",fill=ink)
        ypos+=78
    d.line((w//2-85,790,w//2+85,790),fill=fine,width=2)
    if dark and frame%5 in (1,2):
        x=rng.randint(110,w-110)
        d.line((x,60,x+rng.randint(-9,9),h-70),fill=(117,110,100),width=1)
    return image

def render_vintage_scene(folder: Path,cue: VintageCue,index: int)->tuple[str,int]:
    """Animated film gate + paper scenes; source person is hidden for 1.5–2.2s."""
    folder.mkdir(parents=True,exist_ok=True)
    n=max(3,math.ceil((cue.end-cue.start)*FPS))
    pattern=str(folder/f"vintage_{index:02d}_%03d.png")
    for frame in range(n):
        p=frame/max(1,n-1)
        fade=max(0.,min(1.,p/.16,(1.-p)/.16))
        fade=fade*fade*(3-2*fade)
        im=_scene_image(cue,frame,index).convert("RGBA")
        im.putalpha(Image.new("L",SIZE,round(255*fade)))
        im.save(folder/f"vintage_{index:02d}_{frame:03d}.png",optimize=True)
    return pattern,n

def make_vintage_sound_track(target:Path,cues:Sequence[VintageCue],duration:float,
                             rate:int=24000)->None:
    """Locally synthesized low-volume projector tick, reel hiss, and shutter."""
    samples=array("h",[0])*max(1,int(duration*rate))
    for n,cue in enumerate(cues):
        rng=random.Random(653+n*73)
        start=int(cue.start*rate)
        stop=min(len(samples),int((cue.end+.04)*rate))
        for pos in range(start,stop):
            local=(pos-start)/rate
            total=(stop-start)/rate
            taper=max(0.,min(1.,local/.13,(total-local)/.16))
            click=math.exp(-(local*24%1)*65)
            noise=rng.random()*2-1
            motor=math.sin(2*math.pi*108*local)*.22
            sound=.028*noise+.13*click*noise+.015*motor
            if local<.055:
                sound+=.18*math.exp(-local*80)*noise
            value=round(32767*sound*taper)
            samples[pos]=max(-32760,min(32760,samples[pos]+value))
    target.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(target),"wb") as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate)
        f.writeframes(samples.tobytes())
