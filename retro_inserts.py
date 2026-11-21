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


CARD_STYLES = {
    # bg, ink, border, visual shape
    "retro":     ((235,220,186,251),(77,55,45,255),(145,84,65,255),"archive"),
    "vintage":   ((232,209,167,251),(84,51,39,255),(162,88,55,255),"archive"),
    "old_money": ((246,236,214,251),(68,59,54,255),(170,141,87,255),"luxury"),
    "elegant":   ((248,243,239,250),(79,58,72,255),(189,146,160,255),"luxury"),
    "street":    ((33,35,42,251),(247,245,232,255),(214,239,70,255),"street"),
    "editorial": ((247,246,240,251),(39,35,39,255),(220,71,68,255),"clean"),
    "minimal":   ((243,244,241,249),(48,54,50,255),(116,133,122,255),"clean"),
    "neon":      ((31,25,51,250),(237,242,243,255),(183,236,85,255),"street"),
    "pop":       ((255,229,238,251),(98,43,82,255),(241,87,150,255),"street"),
    "luxe":      ((245,235,218,251),(75,49,45,255),(183,141,101,255),"luxury"),
}


def make_retro_card(
    target: Path, label: str, symbol: str, style: str = "retro",
) -> None:
    """Create an ORIGINAL themed cutaway card for every user caption style."""
    if style not in CARD_STYLES:
        raise ValueError("Неизвестный стиль вставки: " + str(style))
    from PIL import Image, ImageDraw, ImageFilter

    paper,ink,accent,shape=CARD_STYLES[style]
    w,h=480,382
    image=Image.new("RGBA",(w,h),(0,0,0,0))
    shade=Image.new("RGBA",(w,h),(0,0,0,0))
    sd=ImageDraw.Draw(shade)
    bounds=(29,25,w-29,h-29)
    radius=12 if shape=="street" else 20 if shape=="clean" else 34
    sd.rounded_rectangle((37,35,w-21,h-20),
                         radius=radius,fill=(7,7,10,126))
    image.alpha_composite(shade.filter(ImageFilter.GaussianBlur(11)))
    panel=Image.new("RGBA",(w,h),(0,0,0,0))
    brush=ImageDraw.Draw(panel)
    brush.rounded_rectangle(bounds,radius=radius,fill=paper,outline=accent,width=3)
    if shape=="luxury":
        brush.rounded_rectangle((40,36,w-40,h-39),
                                radius=radius-8,outline=accent,width=2)
        for x in (60,w-60):
            for y in (59,h-60):
                brush.ellipse((x-4,y-4,x+4,y+4),fill=accent)
        brush.line((76,65,w-76,65),fill=accent,width=2)
    elif shape=="archive":
        brush.rounded_rectangle((39,35,w-39,h-38),
                                radius=radius-9,outline=ink,width=1)
        brush.line((72,64,w-72,64),fill=accent,width=2)
        brush.line((72,h-77,w-72,h-77),fill=accent,width=2)
        rng=random.Random(label+symbol+style)
        # Aged paper has locally generated tiny speckles, not stock texture.
        for _ in range(780):
            x,y=rng.randrange(46,w-46),rng.randrange(45,h-45)
            rad=rng.randrange(1,3)
            brush.ellipse((x,y,x+rad,y+rad),
                          fill=(123,85,55,rng.randrange(5,24)))
    elif shape=="street":
        brush.rectangle((39,37,w-39,46),fill=accent)
        brush.polygon([(44,61),(120,61),(91,77),(44,77)],fill=accent)
        brush.rectangle((52,h-79,w-52,h-75),fill=accent)
        for x in range(60,w-55,34):
            brush.line((x,56,x-14,80),fill=accent,width=2)
    else: # clean editorial
        brush.line((52,65,w-52,65),fill=accent,width=2)
        brush.rectangle((49,50,65,66),fill=accent)

    icon=_emoji_patch(symbol,152)
    if icon:
        # For darker graphics the tinted icon is deliberately lighter.
        panel.alpha_composite(icon,((w-icon.width)//2,91))
    else:
        brush.text((w//2,159),"✦",font=_serif(118),
                   fill=accent,anchor="mm")

    title=str(label).strip().upper()[:22] or "ВАЖНО"
    if shape in ("street","clean"):
        family=("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
                if shape=="street" else
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        from PIL import ImageFont
        try: chosen=ImageFont.truetype(family,39)
        except OSError: chosen=_serif(39)
    else:
        chosen=_serif(42)
    font_size=42 if shape not in ("street","clean") else 39
    while font_size>19:
        try:
            from PIL import ImageFont
            current=ImageFont.truetype(chosen.path,font_size)
        except (AttributeError,OSError):
            current=_serif(font_size)
        bb=brush.textbbox((0,0),title,font=current)
        if bb[2]-bb[0]<=w-110:
            break
        font_size-=2
    brush.text((w//2,h-95),title,font=current,fill=ink,anchor="mm")
    footer={
        "street":"STREET  •  CUT  •  PLAY",
        "neon":"NIGHT  •  REELS",
        "pop":"POP  •  REELS",
        "elegant":"ELEGANCE  •  REELS",
        "old_money":"ATELIER  •  REELS",
        "luxe":"COLLECTION  •  REELS",
        "editorial":"EDITORIAL  •  REELS",
        "minimal":"MOTION  •  REELS",
    }.get(style,"✦  ARCHIVE  •  REELS  ✦")
    brush.text((w//2,h-58),footer,
               font=_serif(17,False),fill=accent,anchor="mm")
    image.alpha_composite(panel)
    target.parent.mkdir(parents=True,exist_ok=True)
    image.save(target)


def make_retro_sound_track(
    target: Path,
    cues: Sequence[RetroCue],
    duration: float,
    rate: int = 48000,
    style: str = "retro",
) -> None:
    """Оригинальные звуки в характере выбранного оформления."""
    if style not in CARD_STYLES:
        raise ValueError("Неподдерживаемый стиль звука вставок.")
    gain = (0.072 if style in ("old_money","elegant","luxe") else
            0.115 if style in ("street","neon","pop") else
            0.090)
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
            sample=int(32767*gain*envelope*wave_value)
            pos=start+i
            samples[pos]=max(-32760,min(32760,samples[pos]+sample))
    with wave.open(str(target),"wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())
