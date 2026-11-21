"""Оригинальные ретро-вставки для динамичного Reels, без внешних картинок.

Это не копирование ассетов референса: винтажные карточки создаются
Pillow локально из собственной типографики и системного Noto Emoji.
Вставка привязана к времени произнесённого тематического слова.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
import re
from pathlib import Path
from typing import Sequence

Word = tuple[float, float, str]


@dataclass(frozen=True)
class RetroCue:
    time: float
    label: str
    symbol: str
    sound: str


# Важные темы из разных ниш: маникюр, бьюти, обучение, маркетинг, медицина.
# Слова из реального транскрипта, а не придуманная постановка.
TOPICS: tuple[tuple[tuple[str, ...],str,str,str], ...] = (
    (("маникюр","ногт","покрыти","френч","кутикул"), "МАНИКЮР", "💅", "sparkle"),
    (("зуб","стомат","эмал","кариес","дент","щетк","паст"), "ЗАБОТА", "🦷", "sparkle"),
    (("ошиб","проблем","неправ","кошмар","страшн"), "ВНИМАНИЕ!", "❗", "stamp"),
    (("клиент","запис","встреч","люд"), "КЛИЕНТ", "❤️", "soft_bell"),
    (("цен","рубл","деньг","стоим","скидк","промокод"), "ВЫГОДА", "💰", "coin"),
    (("съём","съем","камера","видео","ролик","reels"), "СЪЁМКА", "📷", "shutter"),
    (("фото","кадр","снимок"), "КАДР", "📸", "shutter"),
    (("секрет","идея","лайфхак","совет","решени"), "ИДЕЯ", "💡", "sparkle"),
    (("быстр","секунд","минут","врем","срок"), "ВРЕМЯ", "⌛", "tick"),
    (("нов","тренд","мода","стиль","образ"), "НОВИНКА", "✨", "sparkle"),
    (("перв","втор","выбор","сравн","вариант"), "СРАВНИМ", "⚖", "paper"),
    (("учен","обуч","урок","школ","курс"), "ОБУЧЕНИЕ", "📚", "paper"),
    (("работ","мастер","професс","студ"), "МАСТЕР", "🎨", "stamp"),
    (("результат","готов","получил","итог"), "РЕЗУЛЬТАТ", "🏆", "soft_bell"),
    (("проверь","вопрос","смотри","запомн","важн"), "ЗАМЕТЬ!", "👀", "stamp"),
)


def choose_retro_cues(
    words: Sequence[Word],
    duration: float,
    density: str = "balanced",
    max_cues: int = 8,
) -> list[RetroCue]:
    """Не заслонять человека постоянно: редкие тематические cutaway-карточки."""
    min_gaps = {"subtle": 8.0, "balanced": 5.4, "dynamic": 3.5}
    if density not in min_gaps:
        raise ValueError("Плотность вставок: subtle, balanced или dynamic.")
    if duration < 2.2:
        return []
    gap = min_gaps[density]
    clean_words = sorted(
        ((max(0.0,float(a)),str(token).lower()) for a,b,token in words
         if b > a and str(token).strip()), key=lambda x:x[0]
    )
    result: list[RetroCue] = []
    for t,word in clean_words:
        if t < 0.35 or t > duration - 1.25 or result and t - result[-1].time < gap:
            continue
        simplified = re.sub(r"[^a-zа-яё0-9]", "", word)
        matched = next(
            ((name,symbol,sound) for stems,name,symbol,sound in TOPICS
             if any(stem in simplified for stem in stems)), None
        )
        if matched is None:
            continue
        name,symbol,sound=matched
        result.append(RetroCue(t,name,symbol,sound))
        if len(result)>=max_cues:
            break
    return result


def _serif(size: int, bold: bool = True):
    from PIL import ImageFont
    paths = [
        "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf"
        if bold else
        "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path,size)
        except OSError:
            continue
    return ImageFont.load_default()


def _emoji_patch(symbol: str, size: int = 140):
    from PIL import Image,ImageDraw,ImageFont,ImageEnhance
    emoji_font=Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")
    if not emoji_font.is_file():
        return None
    try:
        font=ImageFont.truetype(str(emoji_font),109)
        img=Image.new("RGBA",(180,180),(0,0,0,0))
        draw=ImageDraw.Draw(img)
        draw.text((90,90),symbol,anchor="mm",font=font,embedded_color=True)
        bbox=img.getbbox()
        if not bbox:return None
        img=img.crop(bbox)
        img.thumbnail((size,size),Image.Resampling.LANCZOS)
        # Винтажная палитра: деликатная сепия, оставляем объём и фактуру.
        colored=Image.new("RGBA",img.size,(0,0,0,0))
        pix=img.load()
        out=colored.load()
        for y in range(img.height):
            for x in range(img.width):
                rr,gg,bb,aa=pix[x,y]
                if not aa:continue
                nr=int(min(255,0.89*rr+0.15*gg+11))
                ng=int(min(255,0.14*rr+0.76*gg+0.05*bb+5))
                nb=int(min(255,0.10*rr+0.18*gg+0.65*bb))
                out[x,y]=(nr,ng,nb,aa)
        return colored
    except (OSError,ValueError):
        return None


def make_retro_card(
    target: Path,
    label: str,
    symbol: str,
    style: str = "retro",
) -> None:
    """Тиснение, архивная бумага, эмодзи-иллюстрация и физическая тень."""
    if style not in ("retro","minimal"):
        raise ValueError("Вставки: retro, minimal или off.")
    from PIL import Image,ImageDraw,ImageFilter
    width,height=480,382
    image=Image.new("RGBA",(width,height),(0,0,0,0))
    shadow=Image.new("RGBA",(width,height),(0,0,0,0))
    sd=ImageDraw.Draw(shadow)
    bounds=(30,26,width-30,height-29)
    sd.rounded_rectangle((bounds[0]+7,bounds[1]+9,bounds[2]+7,bounds[3]+9),
                         radius=35,fill=(5,11,9,145))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    panel=Image.new("RGBA",(width,height),(0,0,0,0))
    brush=ImageDraw.Draw(panel)
    if style=="retro":
        paper=(235,220,186,252)
        ink=(77,55,45,255)
        accent=(145,84,65,255)
    else:
        paper=(234,242,235,248)
        ink=(26,65,59,255)
        accent=(47,125,103,255)
    brush.rounded_rectangle(bounds, radius=32, fill=paper,outline=ink,width=3)
    brush.rounded_rectangle((39,35,width-39,height-38),radius=25,outline=accent,width=2)
    # Deliberately reproducible aged texture so stickers do not look like
    # the default flat emoji keyboards.
    rng=random.Random(label+symbol+style)
    if style=="retro":
        for _ in range(1050):
            x=rng.randrange(45,width-45)
            y=rng.randrange(41,height-43)
            rad=rng.choice((0,0,1,1,2))
            brush.ellipse((x,y,x+rad,y+rad),fill=(115,79,58,rng.randrange(6,25)))
    brush.line((78,63,width-78,63),fill=accent,width=2)
    brush.line((78,height-81,width-78,height-81),fill=accent,width=2)
    brush.ellipse((65,56,80,71),fill=accent)
    brush.ellipse((width-80,56,width-65,71),fill=accent)
    emoji=_emoji_patch(symbol,158)
    if emoji:
        panel.alpha_composite(emoji,((width-emoji.width)//2,91))
    else:
        brush.text((width//2,154),"✦",font=_serif(112),fill=accent,anchor="mm")
    title=str(label).strip().upper()[:22] or "ВАЖНО"
    font_size=43
    while font_size>=24:
        ft=_serif(font_size)
        if brush.textbbox((0,0),title,font=ft)[2] <= width-112:
            break
        font_size-=2
    brush.text((width//2,height-92),title,font=_serif(font_size),
               fill=ink,anchor="mm",stroke_width=0)
    brush.text((width//2,height-56),"✦  ARCHIVE  •  REELS  ✦",
               font=_serif(17,False),fill=accent,anchor="mm")
    image.alpha_composite(panel)
    target.parent.mkdir(parents=True,exist_ok=True)
    image.save(target)


def make_retro_sound_track(
    target: Path,
    cues: Sequence[RetroCue],
    duration: float,
    rate: int = 48000,
) -> None:
    """Оригинальные paper/swish/shutter/coin/chime, без чужих сэмплов."""
    import wave
    from array import array
    n_total=max(1,int(duration*rate))
    # Для 2-минутного видео храним mono int16: ~12 МБ максимум.
    samples=array("h",[0])*n_total
    for cue in cues:
        start=int(cue.time*rate)
        if start>=n_total:continue
        kind=cue.sound
        span=0.11 if kind=="shutter" else 0.23 if kind in ("sparkle","soft_bell") else 0.16
        length=min(int(span*rate),n_total-start)
        rng=random.Random(f"{kind}:{cue.time:.3f}")
        for i in range(length):
            t=i/rate
            envelope=(1-math.exp(-t*110))*math.exp(-t*(19 if kind!="sparkle" else 13))
            noise=rng.random()*2-1
            if kind=="shutter":
                wave_value=.78*noise + .22*math.sin(2*math.pi*210*t)
            elif kind=="paper":
                wave_value=.65*noise + .35*math.sin(2*math.pi*(250-80*t)*t)
            elif kind=="stamp":
                wave_value=.5*math.sin(2*math.pi*130*t) + .5*noise
            elif kind=="coin":
                wave_value=.62*math.sin(2*math.pi*1100*t)+.38*math.sin(2*math.pi*1620*t)
            elif kind=="tick":
                wave_value=.5*math.sin(2*math.pi*910*t)+.5*noise
            elif kind=="soft_bell":
                wave_value=.7*math.sin(2*math.pi*700*t)+.3*math.sin(2*math.pi*1050*t)
            else: # sparkle
                wave_value=.65*math.sin(2*math.pi*(820+720*t)*t)+.35*math.sin(2*math.pi*1340*t)
            sample=int(32767*0.10*envelope*wave_value)
            pos=start+i
            samples[pos]=max(-32760,min(32760,samples[pos]+sample))
    with wave.open(str(target),"wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())
