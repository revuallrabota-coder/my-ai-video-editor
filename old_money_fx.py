"""Restraint-first Old Money props: semantic moments, self-drawn licensed-safe fallback."""
from __future__ import annotations
import math
import re
from pathlib import Path
from typing import Sequence
from PIL import Image, ImageDraw, ImageFilter
from retro_inserts import RetroCue, _serif

# Explicit nouns only. No generic random emoji or invented product placements.
CONCEPTS = (
    ("coffee", ("кофе","эспрессо","капучино","coffee"), "soft_bell"),
    ("book", ("книг","чита","журнал","journal","book"), "paper"),
    ("letter", ("письм","конверт","записк","letter","envelope"), "paper"),
    ("watch", ("часов","часы","врем","минут","watch","time"), "tick"),
    ("vinyl", ("музык","пластин","винил","music","vinyl"), "soft_bell"),
    ("phone", ("телефон","звонк","позвон","telephone","phone"), "soft_bell"),
    ("flower", ("цветок","цветы","букет","розы","орхиде","flower","rose"), "paper"),
    ("pearl", ("жемчуг","бусин","украшен","pearl","jewel"), "soft_bell"),
    ("architecture", ("архитект","особняк","дворец","колонн","здани","palace","building"), "soft_bell"),
    ("ribbon", ("бант","лента","шёлк","шелк","атлас","ribbon","silk"), "paper"),
)

def select_old_money_cues(words: Sequence[tuple[float,float,str]], duration: float,
                           density: str="balanced") -> list[RetroCue]:
    gaps={"subtle":11.5,"balanced":8.0,"dynamic":5.5}
    limits={"subtle":2,"balanced":4,"dynamic":6}
    if density not in gaps:
        raise ValueError("Unsupported Old Money cue density")
    if duration<7:return []
    result=[]
    for a,b,token in sorted(words,key=lambda x:float(x[0])):
        a,b=float(a),float(b)
        if b<=a or a<4.25 or a>duration-1.7:continue
        if result and a-result[-1].time<gaps[density]:continue
        word=re.sub(r"[^a-zа-яё0-9]","",str(token).casefold())
        choice=next(((name,sound) for name,roots,sound in CONCEPTS
                     if any(word.startswith(root) for root in roots)),None)
        if choice is None:continue
        name,sound=choice
        result.append(RetroCue(a,str(token).strip()[:22],name,sound))
        if len(result)>=limits[density]:break
    return result

def _draw_prop(d: ImageDraw.ImageDraw, theme: str, ink, gold) -> None:
    x,y=240,160
    if theme=="coffee":
        d.ellipse((x-98,y+60,x+98,y+83),outline=gold,width=5)
        d.rounded_rectangle((x-72,y-36,x+62,y+59),radius=12,outline=ink,width=6)
        d.arc((x+46,y-23,x+113,y+50),266,103,fill=gold,width=7)
        for dx in (-32,17):d.arc((x+dx-10,y-85,x+dx+15,y-27),75,245,fill=gold,width=3)
    elif theme=="watch":
        d.ellipse((x-83,y-83,x+83,y+83),outline=ink,width=7)
        d.ellipse((x-70,y-70,x+70,y+70),outline=gold,width=2)
        d.line((x,y,x,y-43),fill=ink,width=6)
        d.line((x,y,x+40,y+17),fill=ink,width=6)
        for k in range(12):
            a=k*math.pi/6
            cx=x+59*math.sin(a);cy=y-59*math.cos(a)
            d.ellipse((cx-2,cy-2,cx+2,cy+2),fill=gold)
    elif theme=="book":
        d.polygon([(x-111,y-64),(x-7,y-48),(x,y-36),(x+7,y-48),
                   (x+111,y-64),(x+111,y+73),(x+7,y+55),(x,y+65),
                   (x-7,y+55),(x-111,y+73)],outline=ink)
        d.line((x,y-36,x,y+65),fill=gold,width=5)
        for z in (0,25,50):d.line((x-98,y-43+z,x-21,y-29+z),fill=gold,width=2)
    elif theme=="letter":
        d.rectangle((x-111,y-66,x+111,y+74),outline=ink,width=6)
        d.line((x-111,y-66,x,y+23,x+111,y-66),fill=gold,width=4)
        d.ellipse((x-19,y+5,x+19,y+43),fill=(112,44,50,255),outline=gold,width=2)
    elif theme=="vinyl":
        d.ellipse((x-91,y-91,x+91,y+91),fill=(49,47,45,255),outline=gold,width=4)
        for r in (70,53,36):d.ellipse((x-r,y-r,x+r,y+r),outline=(113,104,89,255),width=2)
        d.ellipse((x-24,y-24,x+24,y+24),fill=(202,177,129,255))
        d.ellipse((x-4,y-4,x+4,y+4),fill=ink)
    elif theme=="phone":
        d.arc((x-105,y-110,x+105,y+29),188,352,fill=ink,width=18)
        d.rounded_rectangle((x-105,y-6,x+105,y+88),radius=16,outline=gold,width=6)
        d.ellipse((x-42,y+11,x+42,y+82),outline=ink,width=5)
    elif theme=="flower":
        for k in range(6):
            a=k*math.pi/3
            cx=x+48*math.cos(a);cy=y+48*math.sin(a)
            d.ellipse((cx-42,cy-42,cx+42,cy+42),outline=ink,width=4)
        d.ellipse((x-25,y-25,x+25,y+25),fill=gold)
    elif theme=="pearl":
        for k in range(11):
            a=math.pi+k*math.pi/10
            cx=x+93*math.cos(a);cy=y-6-70*math.sin(a)
            r=15 if k in (4,5,6) else 11
            d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=(250,245,236,255),outline=gold,width=3)
    elif theme=="architecture":
        d.polygon([(x-112,y-56),(x,y-105),(x+112,y-56)],outline=gold)
        for dx in (-78,-26,26,78):
            d.rectangle((x+dx-10,y-51,x+dx+10,y+69),outline=ink,width=4)
        d.line((x-115,y+76,x+115,y+76),fill=gold,width=8)
    elif theme=="ribbon":
        d.polygon([(x,y),(x-112,y-69),(x-105,y+53)],outline=ink)
        d.polygon([(x,y),(x+112,y-69),(x+105,y+53)],outline=ink)
        d.ellipse((x-22,y-22,x+22,y+22),fill=gold)
        d.polygon([(x-17,y+20),(x-51,y+94),(x,y+75)],outline=ink)
        d.polygon([(x+17,y+20),(x+51,y+94),(x,y+75)],outline=ink)

def render_old_money_card(target:Path,label:str,theme:str)->None:
    """Transparent serif editorial card with original vector-like tactile motif."""
    if theme not in {a for a,_,_ in CONCEPTS}:
        raise ValueError("Invalid Old Money theme")
    w,h=480,382
    shadow=Image.new("RGBA",(w,h),(0,0,0,0))
    ImageDraw.Draw(shadow).rounded_rectangle((38,28,w-38,h-30),radius=28,fill=(26,22,18,65))
    image=shadow.filter(ImageFilter.GaussianBlur(15))
    paper=Image.new("RGBA",(w,h),(0,0,0,0))
    d=ImageDraw.Draw(paper)
    ink=(67,54,46,255);gold=(170,140,102,255)
    d.rounded_rectangle((32,20,w-32,h-34),radius=24,fill=(246,237,222,243),outline=gold,width=3)
    d.line((72,280,w-72,280),fill=gold,width=2)
    _draw_prop(d,theme,ink,gold)
    text=re.sub(r"[\r\n{}]","",str(label)).upper()[:22].strip()
    if text:
        size=38
        font=_serif(size)
        while d.textbbox((0,0),text,font=font)[2]>350 and size>18:
            size-=2; font=_serif(size)
        d.text((w//2,310),text,font=font,fill=ink,anchor="mm")
    image.alpha_composite(paper)
    target.parent.mkdir(parents=True,exist_ok=True)
    image.save(target)
