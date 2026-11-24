"""18 reusable cinematic Reels techniques based on the 13-page neurofam guide.

These are original procedural adaptations, not HyperFrames or copyrighted
templates. Frames are generated from the client's own video, and UI text is
sourced from approved transcription. 15fps overlays become 30fps in FFmpeg.
The "behind" and "cutout" modes require MediaPipe subject segmentation and
fail clearly rather than falsely claiming the effect was applied.
"""
from __future__ import annotations

import math
import re
import subprocess
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

SIZE=(360,640)
FPS=15
SECS=3.
EFFECTS={
    "pov_carousel_spin":"Карусель вокруг человека",
    "liquid_glass_graph":"Жидкое стекло и график",
    "match_cut":"Нарезка на одном слове",
    "screen_push_digital":"Пиксельные слова",
    "apple_ui_toggles":"Переключатели iOS",
    "over_shoulder_zoom":"Зум и карточки-доказательства",
    "text_behind_me":"Слово за спиной",
    "notification_stack":"Уведомления над головой",
    "phone_3d_float":"Видео в 3D-телефоне",
    "split_clones":"Три копии со сдвигом",
    "sticker_cutout":"Человек-стикер",
    "zoom_through_text":"Пролёт сквозь букву",
    "glass_explainer_reel":"Объяснялка на стекле",
    "cinematic_type_reel":"Кинотипографика",
    "image_cluster_reel":"Картинки над головой",
    "cutout_grid_reel":"Человек поверх сетки",
    "depth_ui_reel":"Интерфейс за спиной",
    "split_reel":"Разделённый экран",
}
SUBJECT_FX={"text_behind_me","sticker_cutout","cutout_grid_reel","depth_ui_reel",
            "pov_carousel_spin"}
FULL_FX={"match_cut","screen_push_digital","phone_3d_float","split_clones",
         "zoom_through_text","glass_explainer_reel","cinematic_type_reel",
         "sticker_cutout","cutout_grid_reel","split_reel"}
Word=tuple[float,float,str]


@dataclass(frozen=True)
class GuideCue:
    effect: str
    start: float
    end: float
    label: str
    compact: bool = False  # Compact overlay.
    required: bool = False  # Manually requested visual.


def _clean(s: str) -> str:
    return re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9% -]","",s).strip()


def _label(words: Sequence[Word], t: float, limit: int = 22) -> str:
    local=[_clean(str(w)) for st,en,w in words
           if st<=t+2.8 and en>=t-.3 and len(_clean(str(w)))>=3]
    priorities=("ошиб","результ","важн","салон","кисть","паста",
                "сравн","гель","толщин","скорост","обучен","время")
    featured=next((word for word in local
                   if any(root in word.lower() for root in priorities)),None)
    return (featured or max(local,key=len) if local else "").upper()[:limit]


# The eight understandable effect families are mappings, not an 18-item
# roulette wheel. Every automatic trigger must be present in the actual speech.
SMART_EFFECTS = (
    "pov_carousel_spin", "match_cut", "split_reel",
    "glass_explainer_reel", "apple_ui_toggles", "image_cluster_reel",
    "liquid_glass_graph", "notification_stack",
)
# Order is intentional: concrete meaning wins over vague related wording.
SMART_TRIGGERS = (
    ("pov_carousel_spin", ("много", "несколько", "вариант", "перечисл",
                           "список", "три", "четыре", "пять", "подборк",
                           "коллекц", "many", "several", "options", "list")),
    ("split_reel", ("сравн", "разниц", "отлич", "против", "сопостав",
                    "compare", "versus", "difference")),
    ("match_cut", ("главн", "важн", "ключев", "запомн", "основн", "ошиб", "проблем", "неправ",
                   "самое", "важнейш", "important", "main", "key")),
    ("glass_explainer_reel", ("объясн", "почему", "причин", "потому",
                              "разбер", "поясн", "explain", "because", "why")),
    ("apple_ui_toggles", ("этап", "шаг", "сначала", "затем", "во-первых",
                          "во-вторых", "следующ", "порядок",
                          "step", "first", "second")),
    ("image_cluster_reel", ("пример", "покаж", "фото", "картин", "иллюстр",
                            "демонстр", "example", "photo", "show")),
    ("liquid_glass_graph", ("результ", "прогресс", "процент", "показател",
                            "скорост", "вырос", "снизил", "percent", "result")),
    ("notification_stack", ("секрет", "обратите", "предупреж", "вниман",
                             "совет", "secret", "attention", "tip")),
)
SMART_GAP = {"subtle":10.5, "balanced":7.2, "dynamic":5.1}
SMART_LIMIT = {"subtle":3, "balanced":5, "dynamic":7}


def _allowed_auto_effects(choice: str) -> set[str] | None:
    """None means unconstrained auto; multi: holds a validated preferred set."""
    if choice == "auto":
        return None
    if not choice.startswith("multi:"):
        raise ValueError("Некорректный набор эффектов.")
    selected = choice[6:].split(",")
    if (not 1 <= len(selected) <= len(SMART_EFFECTS) or
            len(set(selected)) != len(selected) or
            any(name not in SMART_EFFECTS for name in selected)):
        raise ValueError("Укажи от одного до восьми совместимых эффектов.")
    return set(selected)


def _spoken_smart_cues(words: Sequence[Word], duration: float, choice: str,
                       density: str) -> list[GuideCue]:
    permitted = _allowed_auto_effects(choice)
    # First four seconds are reserved for the speaker and natural subtitles.
    gap = SMART_GAP[density]
    ordered = sorted(words, key=lambda w: float(w[0]))
    candidates = []
    for start, end, spoken in ordered:
        t = float(start)
        if t < 4.0 or t > duration - 1.85 or float(end) <= t:
            continue
        token = _clean(str(spoken)).casefold().strip()
        if not token:
            continue
        kind = next((
            (priority, effect) for priority, (effect, stems)
            in enumerate(SMART_TRIGGERS)
            if (permitted is None or effect in permitted)
            and any(token.startswith(stem) for stem in stems)
        ), None)
        if kind is None and token.endswith("%") and token[:-1].isdigit():
            if permitted is None or "liquid_glass_graph" in permitted:
                kind=(6,"liquid_glass_graph")
        if token in ("сначала", "first"):
            # "Сначала поговорим" is not proof of a multi-step explanation.
            subsequent = any(
                0 < float(st)-t < 4.5 and
                _clean(str(word)).casefold().startswith(
                    ("затем","потом","следующ","втор","шаг","этап","second","next")
                )
                for st,en,word in ordered
            )
            if not subsequent and kind and kind[1]=="apple_ui_toggles":
                kind = None
        # "До и после" is a comparison; "до пяти секунд" is not.
        if kind is None and token=="до" and (
                permitted is None or "split_reel" in permitted):
            paired = any(
                0 < float(st)-t < 3.5 and
                _clean(str(word)).casefold().startswith("после")
                for st,en,word in ordered
            )
            if paired: kind=(1,"split_reel")
        if kind:
            priority,effect=kind
            candidates.append((t,priority,effect,_clean(str(spoken)).upper()[:22]))
    if not candidates:
        return []
    # Nearby keywords describe a SINGLE phrase. The stronger/more specific
    # meaning wins: "покажу много вариантов" → carousel, not generic photo.
    clusters=[]
    cluster=[]
    for item in candidates:
        if cluster and item[0]-cluster[-1][0]>1.65:
            clusters.append(cluster)
            cluster=[]
        cluster.append(item)
    if cluster:clusters.append(cluster)
    planned: list[GuideCue] = []
    last=-gap
    for cluster in clusters:
        t,_,effect,label=min(cluster,key=lambda item:(item[1],item[0]))
        if t-last < gap:
            continue
        planned.append(GuideCue(effect,t,min(duration-.05,t+2.35 if effect=="pov_carousel_spin" else t+1.75),
                                label,compact=effect!="pov_carousel_spin"))
        last=t
        if len(planned)>=SMART_LIMIT[density]:
            break
    return planned


def _manual_smart_cues(words: Sequence[Word], duration: float,
                       choice: str, density: str) -> list[GuideCue]:
    """Manually checked favorites are instructions, NOT speech keyword filters.

    Preserve the exact selected order, prefer matching spoken timing when
    nearby, otherwise use a speech-adjacent slot after the clean intro.
    """
    permitted = _allowed_auto_effects(choice)
    assert permitted is not None
    chosen = choice[6:].split(",")
    matched = _spoken_smart_cues(words, duration, choice, density)
    planned: list[GuideCue] = []
    next_start = 4.5
    for effect in chosen:
        if duration-next_start < 1.48:
            break
        matching = next((cue for cue in matched
                         if cue.effect == effect
                         and next_start <= cue.start <= next_start + 3.5), None)
        start = matching.start if matching else next_start
        end = min(duration-.08, start+2.35)
        if end-start < 1.4:
            break
        title = matching.label if matching else _label(words,start)
        if not title:
            title = {
                "pov_carousel_spin":"КАДРЫ",
                "image_cluster_reel":"КАДРЫ",
                "split_reel":"СРАВНЕНИЕ",
                "apple_ui_toggles":"ШАГИ",
                "match_cut":"АКЦЕНТ",
                "glass_explainer_reel":"ПОЯСНЕНИЕ",
                "liquid_glass_graph":"ГРАФИКА",
                "notification_stack":"ВАЖНО",
            }[effect]
        planned.append(GuideCue(effect,start,end,title,
                                compact=effect!="pov_carousel_spin",required=True))
        next_start = end + 1.05
        if len(planned)>=SMART_LIMIT[density]:
            break
    return planned


def plan(words: Sequence[Word], duration: float, choice: str,
         density: str = "balanced") -> list[GuideCue]:
    """Single intelligent selector: auto or a constrained group of favorites.

    Auto is speech-triggered. Explicitly selected favorites must actually
    render (when duration permits), not silently wait for keyword matches.
    A legacy explicit single-effect choice also remains supported.
    """
    if density not in SMART_GAP:
        raise ValueError("Недопустимая частота эффектов.")
    if choice not in EFFECTS and choice not in ("auto", "off") and not choice.startswith("multi:"):
        raise ValueError("Неизвестный приём из гайда: " + choice)
    if choice == "off" or duration < 1.05:
        return []
    if choice == "auto":
        return _spoken_smart_cues(words, duration, choice, density)
    if choice.startswith("multi:"):
        return _manual_smart_cues(words, duration, choice, density)

    # Compatibility for old projects that explicitly chose ONE cinematic effect.
    interval = {"subtle":10.0,"balanced":8.0,"dynamic":7.0}[density]
    limit = {"subtle":3,"balanced":4,"dynamic":5}[density]
    starts = [max(.15, float(st)) for st,en,word in words
              if 0 <= st < duration-1.05 and len(_clean(str(word))) >= 3]
    selected = []
    last = -interval
    for start in starts:
        if start-last < interval or start+1.05 > duration:
            continue
        end = min(duration-.02,start+SECS)
        if end-start < 1.0:
            continue
        selected.append(GuideCue(choice,start,end,_label(words,start)))
        last = start
        if len(selected)>=limit:
            break
    return selected


def _font(size: int, bold: bool=True):
    font=("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
          else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    return ImageFont.truetype(font,size)


def _text(draw,xy,text,size=27,color=(255,247,235),anchor="mm",maxw=315):
    text=_clean(str(text)).upper()
    size=max(10,int(size))
    font=_font(size)
    while size>11 and draw.textbbox((0,0),text,font=font)[2]>maxw:
        size-=1; font=_font(size)
    draw.text(xy,text,fill=color,font=font,anchor=anchor,stroke_width=0)


def _rect(draw,box,color,radius=14,outline=None,width=2):
    draw.rounded_rectangle(tuple(map(int,box)),radius=radius,fill=color,
                           outline=outline,width=width)


def _frame_draw(video: Image.Image | None, box, outline=(255,248,238),
                radius=13) -> Image.Image:
    """Draw a real live frame (not a frozen screenshot) inside a masked card."""
    x0,y0,x1,y1=map(int,box)
    w,h=max(1,x1-x0),max(1,y1-y0)
    src=video if video is not None else Image.new("RGB",(w,h),(60,50,48))
    ratio=max(w/src.width,h/src.height)
    image=src.resize((math.ceil(src.width*ratio),math.ceil(src.height*ratio)),
                     Image.Resampling.LANCZOS)
    dx=(image.width-w)//2;dy=(image.height-h)//2
    cropped=image.crop((dx,dy,dx+w,dy+h)).convert("RGBA")
    mask=Image.new("L",(w,h),0)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,w-1,h-1),radius=radius,fill=255)
    layer=Image.new("RGBA",SIZE,(0,0,0,0))
    layer.paste(cropped,(x0,y0),mask)
    ImageDraw.Draw(layer).rounded_rectangle(
        (x0,y0,x1,y1),radius=radius,outline=outline,width=2)
    return layer


def _read_video(source: Path,start: float,seconds: float, fps: int=FPS):
    """Exactly time-aligned original frames, 360x640, preserving aspect ratio."""
    command=[
        "ffmpeg","-hide_banner","-loglevel","error",
        "-ss",f"{start:.3f}","-i",str(source),"-t",f"{seconds:.3f}",
        "-vf",f"fps={fps},scale=360:640:force_original_aspect_ratio=increase,"
              "crop=360:640,setsar=1",
        "-f","rawvideo","-pix_fmt","rgb24","pipe:1",
    ]
    data=subprocess.run(command,capture_output=True,timeout=120,check=True).stdout
    stride=360*640*3
    if len(data)<stride:
        raise RuntimeError("Не удалось декодировать кадры для эффектов.")
    frames=[Image.frombytes("RGB",SIZE,data[i:i+stride])
            for i in range(0,len(data)-stride+1,stride)]
    return frames


def _distinct_carousel_frames(source: Path, backup: Sequence[Image.Image]
                              ) -> list[Image.Image]:
    """Pick three genuinely separated moments across the WHOLE source video.

    Previously all thumbnails came from 2.35 seconds around one sentence,
    resulting in nearly identical pictures. Never invent unrelated imagery.
    Favor diverse real frames when the footage has visual changes.
    """
    try:
        probe=subprocess.run(
            ["ffprobe","-v","error","-show_entries","format=duration",
             "-of","default=noprint_wrappers=1:nokey=1",str(source)],
            capture_output=True,text=True,timeout=15,check=True,
        )
        duration=float(probe.stdout.strip())
        if not math.isfinite(duration) or duration<4.0:
            raise ValueError("short source")
        candidates=[]
        size=360*640*3
        for fraction in (.07,.22,.38,.54,.70,.86,.95):
            t=max(0.,min(duration-.2,duration*fraction))
            result=subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error",
                "-ss",f"{t:.3f}","-i",str(source),"-frames:v","1",
                "-vf","scale=360:640:force_original_aspect_ratio=increase,"
                      "crop=360:640,setsar=1",
                "-f","rawvideo","-pix_fmt","rgb24","pipe:1",
            ],capture_output=True,timeout=25,check=True)
            if len(result.stdout)>=size:
                image=Image.frombytes("RGB",SIZE,result.stdout[:size])
                candidates.append(image)
        if len(candidates)<3:
            raise ValueError("not enough video frames")
        # Perceptual contrast from resized grayscale avoids choosing three
        # back-to-back near duplicates when the source contains real cuts.
        thumbs=[x.convert("L").resize((24,43),Image.Resampling.BILINEAR)
                for x in candidates]
        def difference(i:int,j:int)->float:
            from PIL import ImageStat
            return ImageStat.Stat(
                ImageChops.difference(thumbs[i],thumbs[j])).mean[0]
        selected=[0]
        while len(selected)<3:
            remaining=[i for i in range(len(candidates)) if i not in selected]
            selected.append(max(remaining,key=lambda i:
                min(difference(i,j) for j in selected)))
        return [candidates[i] for i in sorted(selected)]
    except (OSError,ValueError,subprocess.SubprocessError):
        if not backup:
            raise RuntimeError("Нет реальных кадров для карусели.")
        chosen=[backup[0],backup[len(backup)//2],backup[-1]]
        return [frame.convert("RGB") for frame in chosen]


def _mask_frames(frames):
    """Strict fail-closed subject segmentation, never a fake occlusion."""
    from portrait_caption_layer import _segmenter, _person_mask
    with _segmenter() as (segmenter,mp,cv2,np):
        masks=[]
        for frame in frames:
            rgb=np.asarray(frame)
            bgr=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
            value=_person_mask(bgr,segmenter,mp,cv2,np)
            mask=Image.fromarray(np.uint8(np.clip(value,0,1)*255),"L")
            masks.append(mask.resize(SIZE,Image.Resampling.BILINEAR))
        if not masks or max(max(m.getextrema()) for m in masks)<100:
            raise RuntimeError("В этом фрагменте не удалось выделить силуэт.")
        return masks


def _cutout(image: Image.Image,mask: Image.Image):
    layer=image.convert("RGBA")
    layer.putalpha(mask)
    return layer


def _pct(words:Sequence[Word],start:float):
    for st,en,w in words:
        if start-2.0<=st<=start+3.0:
            match=re.search(r"(?<!\d)(\d{1,3})\s*%",str(w))
            if match:return min(100,int(match.group(1)))
    return None


def _draw(effect: str, p: float, label: str,
          video: Image.Image, frames: list[Image.Image], frame_index: int,
          mask: Image.Image | None, words: Sequence[Word], start:float,
          palette: str, photos: Sequence[Image.Image] | None = None,
          background_video: Image.Image | None = None) -> Image.Image:
    """Build one animated RGBA scene frame. All visual branches are distinct."""
    bg=(78,34,51) if palette=="burgundy_brown" else (
       (219,231,198) if palette=="pistachio" else (248,236,214))
    dark=(33,27,35); accent=(224,119,78); cream=(250,242,230)
    img=Image.new("RGBA",SIZE,(0,0,0,0))
    d=ImageDraw.Draw(img,"RGBA")
    label=label or "ГЛАВНОЕ"
    ease=1-(1-min(1,p/.22))**3
    enter=round((1-ease)*95)
    fade=min(1,p/.16,(1-p)/.18)
    if effect=="pov_carousel_spin":
        from cinematic_carousel import draw_carousel
        actual=photos if photos else [
            frames[0],frames[len(frames)//2],frames[-1]
        ]
        return draw_carousel(p,actual,palette)
    elif effect=="liquid_glass_graph":
        _rect(d,(22,315+enter,338,505+enter),(255,255,255,170),
              20,(255,255,255,215),2)
        _text(d,(50,341+enter),"ПРОГРЕСС",14,dark,anchor="lm")
        percent=_pct(words,start)
        _text(d,(295,345+enter),str(round(percent*p))+"%" if percent is not None
              else "↗",37,dark,maxw=95)
        coords=[(38,476+enter)]
        for i in range(24):
            t=i/23
            if t<=p:
                coords.append((round(38+270*t),round(471+enter-79*t+.06*math.sin(t*12)*50)))
        if len(coords)>1:d.line(coords,fill=(52,155,96,255),width=4,joint="curve")
        d.ellipse((coords[-1][0]-5,coords[-1][1]-5,
                   coords[-1][0]+5,coords[-1][1]+5),fill=(70,217,135,255))
    elif effect=="match_cut":
        _rect(d,(0,0,360,640),(237,226,203),0)
        page=int(p*16)%16
        for j in range(36):
            y=20+j*19+(page%4)*3
            x=12+(page*j)%21
            d.line((x,y,360-x,y),fill=(70,59,54,95),width=2)
        _rect(d,(24,284,336,364),(190,57,42),3)
        _text(d,(180,324),label,48,cream,maxw=298)
    elif effect=="screen_push_digital":
        if background_video is not None:
            img=background_video.convert("RGBA")
            d=ImageDraw.Draw(img,"RGBA")
            d.rectangle((0,0,360,640),fill=(9,11,16,58))
        else:
            d.rectangle((0,0,360,640),fill=(9,11,16,255))
        for j in range(0,640,5):
            d.line((0,j,360,j),fill=(70,64,83,47))
        word=label[:18]
        x=int(340-p*550)
        _text(d,(x+3,311),word,49,(230,70,75),maxw=300)
        _text(d,(x-3,315),word,49,(68,148,225),maxw=300)
        _text(d,(x,313),word,49,(247,246,240),maxw=300)
    elif effect=="apple_ui_toggles":
        _rect(d,(25,290+enter,335,500+enter),(254,254,254,250),21)
        for j in range(3):
            y=321+j*61+enter
            if j:d.line((38,y-24,322,y-24),fill=(128,130,133,55),width=1)
            _text(d,(44,y),("1  "+label[:12],"2  ПРОВЕРИТЬ","3  РЕЗУЛЬТАТ")[j],
                  13,dark,"lm",200)
            done=p>(.14+j*.24)
            _rect(d,(260,y-13,317,y+14),
                  (52,199,89,255) if done else (160,164,169,255),14)
            d.ellipse((287 if done else 263,y-11,312 if done else 287,y+12),
                      fill=(255,255,255,255))
    elif effect=="over_shoulder_zoom":
        zoom=1+.14*min(1,p*1.35)
        crop=(int(180-180/zoom),int(320-320/zoom),
              int(180+180/zoom),int(320+320/zoom))
        img=video.crop(crop).resize(SIZE).convert("RGBA")
        d=ImageDraw.Draw(img,"RGBA")
        if p<.58:
            x=15+enter
        else:
            x=190-min(0,enter)
        _rect(d,(x,235,x+153,345),(248,245,242,240),15)
        _text(d,(x+77,265),label,19,dark,maxw=142)
        _text(d,(x+77,304),"ВАЖНО",15,accent,maxw=140)
    elif effect=="text_behind_me":
        _text(d,(180,180-round(14*p)),label,66,cream,maxw=345)
        if mask is not None:
            img.putalpha(ImageChops.subtract(img.getchannel("A"),mask))
    elif effect=="notification_stack":
        for k in range(4):
            show=p>k*.17
            if not show:continue
            y=85+k*79-round(19*max(0,1-(p-k*.17)*5))
            _rect(d,(14,y,346,y+70),(25,25,31,232),18)
            d.ellipse((28,y+13,57,y+42),fill=(226,126,68))
            _text(d,(68,y+25),("РИЛС","НОВОЕ","ВАЖНО","СЕЙЧАС")[k],
                  12,cream,"lm",232)
            _text(d,(68,y+50),label,16,cream,"lm",235)
    elif effect=="phone_3d_float":
        d.rectangle((0,0,360,640),fill=(19,12,19,255))
        w=round(220+50*min(1,p/.3))
        x=(360-w)//2+round(16*math.sin(p*6))
        y=115+round(8*math.sin(p*8))
        _rect(d,(x-8,y-8,x+w+8,y+410),(94,78,80),33)
        _rect(d,(x,y,x+w,y+400),(13,14,18),29)
        img.alpha_composite(_frame_draw(video,(x+10,y+16,x+w-10,y+388),radius=21))
        d=ImageDraw.Draw(img);_rect(d,(163,y+7,198,y+13),(0,0,0),4)
    elif effect=="split_clones":
        img=Image.new("RGBA",SIZE,(15,12,15,255))
        for k in range(3):
            shifted=frames[max(0,frame_index-int(.25*k*FPS))]
            x=k*123
            y=(round(60*(1-p/.18)) if k==0 and p<.18 else
               round(-60*(1-p/.18)) if k==2 and p<.18 else 0)
            img.alpha_composite(_frame_draw(shifted,(x,y,x+116,640+y),radius=0))
        d=ImageDraw.Draw(img);d.line((126,0,126,640),fill=accent,width=3)
    elif effect=="sticker_cutout":
        img=Image.new("RGBA",SIZE,(232,89,47,255))
        d=ImageDraw.Draw(img)
        for j in range(27):
            x=(j*73)%360;y=(j*139)%640
            d.ellipse((x,y,x+2,y+2),fill=(255,232,199,115))
        if mask is not None:
            cut=_cutout(video,mask)
            border=mask.filter(ImageFilter.MaxFilter(15))
            white=Image.new("RGBA",SIZE,(255,255,255,255))
            white.putalpha(ImageChops.subtract(border,mask))
            img.alpha_composite(white)
            img.alpha_composite(cut)
        d=ImageDraw.Draw(img)
        _rect(d,(200,96+enter,347,146+enter),(255,255,255,236),12)
        _text(d,(274,119+enter),label,15,dark,maxw=132)
    elif effect=="zoom_through_text":
        big=Image.new("L",SIZE,0)
        textd=ImageDraw.Draw(big)
        size=110+round(520*p*p)
        font=_font(size)
        word=label[:7]
        textd.text((180,320),word,font=font,fill=255,anchor="mm")
        if p>.55:
            big=Image.blend(big,Image.new("L",SIZE,255),min(1,(p-.55)/.4))
        img=Image.new("RGBA",SIZE,(5,4,6,255))
        clip=video.convert("RGBA");clip.putalpha(big)
        img.alpha_composite(clip)
    elif effect=="glass_explainer_reel":
        d.rectangle((0,0,360,640),fill=(17,14,18,255))
        _rect(d,(18,49,342,142),(78,75,83,205),14)
        _text(d,(180,95),label,25,cream,maxw=300)
        for k in range(2):
            x=25+k*162
            _rect(d,(x,163,x+148,269),(77,70,76,216),13)
            _text(d,(x+73,210),"ДО" if k==0 else "ПОСЛЕ",18,accent)
            _text(d,(x+73,241),"БЫЛО" if k==0 else "СТАЛО",15,cream)
        img.alpha_composite(_frame_draw(video,(30,304,331,574)))
    elif effect=="cinematic_type_reel":
        if p<.32:
            d.rectangle((0,0,360,640),fill=(227,99,52,255))
            _text(d,(180,297),label,53,cream,maxw=310)
            _text(d,(180,348),"ВАЖНЫЙ МОМЕНТ",14,cream)
        else:
            d.rectangle((0,0,360,640),fill=(229,230,228,255))
            img.alpha_composite(_frame_draw(video,(24,95,336,475)))
            d=ImageDraw.Draw(img)
            _text(d,(180,525),label,35,dark,maxw=325)
    elif effect=="image_cluster_reel":
        for k in range(4):
            if p<k*.20:continue
            x=20+k*72
            y=84+round(20*math.sin(k*1.5))-round(30*(1-min(1,(p-k*.20)*5)))
            picture=(photos[k%len(photos)] if photos else
                     frames[(frame_index+k*6)%len(frames)])
            img.alpha_composite(_frame_draw(picture,(x,y,x+105,y+137)))
    elif effect=="cutout_grid_reel":
        for k in range(4):
            x=(k%2)*180;y=(k//2)*320
            sub=(photos[(k+int(p>.37)*4)%len(photos)] if photos else
                 frames[(frame_index+int(p>.37)*11+k*6)%len(frames)])
            img.alpha_composite(_frame_draw(sub,(x,y,x+180,y+320),radius=0))
        if mask is not None:img.alpha_composite(_cutout(video,mask))
        d=ImageDraw.Draw(img)
        _rect(d,(22,410,338,472),(13,13,18,191),10)
        _text(d,(180,442),label,28,cream,maxw=290)
    elif effect=="depth_ui_reel":
        _rect(d,(25+enter,70,335+enter,260),(253,250,244,238),22)
        d.ellipse((43+enter,89,78+enter,124),fill=accent)
        _text(d,(61+enter,106),"1",17,cream)
        _text(d,(182+enter,106),"НАСТРОЙКИ",19,dark,maxw=205)
        for k in range(3):
            d.line((53+enter,145+k*30,300+enter,145+k*30),
                   fill=(111,113,111,145),width=2)
        if mask is not None:
            img.putalpha(ImageChops.subtract(img.getchannel("A"),mask))
        d=ImageDraw.Draw(img)
        _text(d,(180,448),label,39,accent,maxw=310)
    elif effect=="split_reel":
        d.rectangle((0,0,360,640),fill=(18,13,16,255))
        img.alpha_composite(_frame_draw(video,(0,0,360,330),radius=0))
        d=ImageDraw.Draw(img)
        _text(d,(180,365),label,27,accent,maxw=315)
        for k in range(2):
            x=20+k*177
            _rect(d,(x,420,x+143,513),(75,61,66,255),13)
            _text(d,(x+71,468),"ДО" if k==0 else "ПОСЛЕ",19,cream,maxw=130)
        d.ellipse((161,444,200,483),fill=accent)
        _text(d,(180,464),"VS",14,cream)
        for k in range(5):
            x=(k*86-int(p*55))%450-60
            photo=(photos[k%len(photos)] if photos else
                   frames[(frame_index+k*4)%len(frames)])
            img.alpha_composite(_frame_draw(photo,(x,540,x+77,629),radius=4))
    else:
        raise ValueError("Сцена отсутствует: "+effect)
    if effect not in FULL_FX:
        alpha=img.getchannel("A")
        alpha=alpha.point(lambda a:int(a*max(0,min(1,fade))))
        img.putalpha(alpha)
    return img


def _compact_protection(mask: Image.Image,
                        caption_position: str) -> Image.Image:
    """Exclude the person and the complete animated subtitle zone."""
    expanded = mask.filter(ImageFilter.MaxFilter(47)).resize(
        (720, 1280), Image.Resampling.BILINEAR
    )
    zones = {
        "top": (190, 655),
        "middle": (445, 980),
        "bottom": (640, 1165),
    }
    if caption_position not in zones:
        raise ValueError("Недопустимое расположение защищённых субтитров.")
    top, bottom = zones[caption_position]
    ImageDraw.Draw(expanded).rectangle((65, top, 655, bottom), fill=255)
    return expanded


def _compact_candidates(effect: str="match_cut") -> tuple[tuple[int, int], ...]:
    if effect in ("pov_carousel_spin","image_cluster_reel"):
        return ((24,245),(376,245),(24,1005),(376,1005))
    return ((36,245),(428,245),(36,475),(428,475),
            (36,680),(428,680),(36,890),(428,890))


def _compact_occupancy(mask: Image.Image,x:int,y:int,
                       effect:str="match_cut") -> float:
    wide=effect in ("pov_carousel_spin","image_cluster_reel")
    area=mask.crop((x-8,y-8,x+(324 if wide else 268),y+(158 if wide else 84)))
    return sum(area.histogram()[128:])/max(1,area.width*area.height)

def _compact_frame(label: str, progress: float,
                   mask: Image.Image, location: tuple[int, int],
                   caption_position: str, effect: str="match_cut",
                   clips: Sequence[Image.Image] = (),
                   palette: str="off",
                   required: bool=False) -> Image.Image:
    """Different small effects per MEANING; same collision-safe 256x72 zone.

    A carousel uses real frames or user-owned photos, not imaginary examples.
    A comparison, step, alert or highlight never invents spoken claims.
    """
    width,height=720,1280
    layer=Image.new("RGBA",(width,height),(0,0,0,0))
    title=_clean(label).upper()[:22]
    if not title:return layer
    expanded=_compact_protection(mask,caption_position)
    x,y=location
    if _compact_occupancy(expanded,x,y,effect)>.03 and not required:
        return layer
    ease=min(1.,max(0.,progress*5.5))
    fade=min(1.,ease,max(0.,(1-progress)*6))
    y+=round(11*(1-ease))
    colors={
        "old_money":((58,48,41,226),(205,179,136,235),(255,244,227,255)),
        "burgundy":((56,15,34,232),(188,115,121,240),(255,233,225,255)),
        "pink_tender":((250,232,239,236),(219,147,175,242),(91,55,75,255)),
        "vintage":((45,37,33,225),(175,137,99,240),(248,227,199,255)),
    }
    bg,accent,ink=colors.get(palette,
                              ((32,26,31,208),(187,113,133,245),(255,245,237,255)))
    draw=ImageDraw.Draw(layer,"RGBA")
    carousel=effect in ("pov_carousel_spin","image_cluster_reel") and bool(clips)
    draw.rounded_rectangle(
        (x,y,x+(320 if carousel else 256),y+(150 if carousel else 72)),
        radius=20,fill=bg,outline=accent,width=3 if carousel else 2)
    def speak(t,xx,yy,maxw,size=20):
        text=_clean(t).upper()
        font=_font(size,False)
        while size>11 and draw.textbbox((0,0),text,font=font)[2]>maxw:
            size-=1;font=_font(size,False)
        draw.text((xx,yy),text,font=font,fill=ink,anchor="lm")
    if carousel:
        # Three large, animated cards made from actual video frames/photos.
        phase=min(2,int(progress*3))
        glide=round(8*math.sin(math.pi*progress))
        for k in range(3):
            source=clips[(k+phase)%len(clips)].convert("RGB")
            ratio=max(91/source.width,94/source.height)
            scaled=source.resize(
                (math.ceil(source.width*ratio),math.ceil(source.height*ratio)),
                Image.Resampling.BILINEAR)
            left=(scaled.width-91)//2
            top=(scaled.height-94)//2
            cropped=scaled.crop((left,top,left+91,top+94)).convert("RGBA")
            rounded=Image.new("L",(91,94),0)
            ImageDraw.Draw(rounded).rounded_rectangle(
                (0,0,90,93),radius=10,fill=255)
            cropped.putalpha(rounded)
            xx=x+13+100*k+glide*(1 if k==1 else -1)
            yy=y+11+(5 if k!=1 else 0)
            layer.alpha_composite(cropped,(xx,yy))
            draw.rounded_rectangle((xx,yy,xx+91,yy+94),
                                   radius=10,outline=accent,width=3)
        speak(title,x+15,y+126,278,19)
        draw.ellipse((x+292,y+120,x+302,y+130),fill=accent)
    elif effect=="split_reel":
        draw.rounded_rectangle((x+10,y+14,x+88,y+58),radius=7,outline=accent,width=2)
        draw.rounded_rectangle((x+111,y+14,x+190,y+58),radius=7,outline=accent,width=2)
        speak(title,x+198,y+36,48,12)
        draw.line((x+99,y+15,x+99,y+58),fill=accent,width=2)
    elif effect=="match_cut":
        draw.rounded_rectangle((x+12,y+10,x+244,y+62),radius=15,
                               outline=accent,width=2)
        speak(title,x+26,y+35,208,29)
        draw.line((x+21,y+60,x+min(239,21+round(212*progress)),y+60),
                  fill=accent,width=3)
    elif effect=="liquid_glass_graph":
        speak(title,x+16,y+25,165,20)
        pts=[(x+16,y+57)]
        for j in range(1,13):
            p=j/12
            if p>progress:break
            pts.append((x+16+int(p*216),y+57-round(29*p+5*math.sin(p*6))))
        if len(pts)>1:draw.line(pts,fill=accent,width=4)
        draw.ellipse((pts[-1][0]-3,pts[-1][1]-3,
                      pts[-1][0]+3,pts[-1][1]+3),fill=ink)
    elif effect=="apple_ui_toggles":
        for j in range(3):
            draw.ellipse((x+14,y+11+j*18,x+26,y+23+j*18),
                         outline=accent,width=2)
            if progress>j*.28:
                draw.line((x+16,y+17+j*18,x+19,y+20+j*18,x+25,y+12+j*18),
                          fill=accent,width=2)
        speak(title,x+46,y+36,195,21)
    elif effect=="notification_stack":
        for j in range(2):
            draw.rounded_rectangle((x+12+j*8,y+10+j*13,x+224+j*6,y+43+j*13),
                                   radius=11,outline=accent,width=2)
        speak(title,x+26,y+31,190,19)
    elif effect=="glass_explainer_reel":
        draw.rounded_rectangle((x+10,y+11,x+47,y+61),radius=11,
                               outline=accent,width=2)
        speak("?",x+24,y+35,24,26)
        speak(title,x+61,y+36,178,22)
    else:
        draw.rounded_rectangle((x+14,y+16,x+20,y+56),radius=3,fill=accent)
        speak(title,x+35,y+36,202,25)
    alpha=ImageChops.subtract(layer.getchannel("A"),expanded)
    if fade<1:
        alpha=alpha.point(lambda value:round(value*fade))
    layer.putalpha(alpha)
    return layer


def render(source: Path, folder: Path, cue:GuideCue, index:int,
           words:Sequence[Word],palette:str="burgundy_brown",
           photos:Sequence[Path] | None = None,
           background_path:Path | None = None,
           caption_position:str="middle") -> tuple[str,int]:
    """Return image2 input path and frame count for one verified 3-second cue."""
    if cue.effect not in EFFECTS:
        raise ValueError("Эффект не поддерживается.")
    count=max(1,int(math.ceil((cue.end-cue.start)*FPS)))
    raw=_read_video(source,cue.start,cue.end-cue.start)
    if not raw:raise RuntimeError("Нет кадров для монтажа.")
    # Full-frame carousel replaces the talking shot instead of wrapping
    # 8 micro-images around a falsely detected face; no mask is required.
    needs_mask=(cue.compact or cue.effect in SUBJECT_FX) and (
        cue.effect!="pov_carousel_spin")
    if needs_mask:
        try:
            masks=_mask_frames(raw)
        except Exception:
            if not cue.required:
                raise
            # Optional face segmenter failure must not erase an explicit
            # small corner carousel. Never fake a person cutout.
            masks=[Image.new("L",SIZE,0) for _ in raw]
    else:
        masks=[]
    original_photos=[]
    if cue.effect in ("pov_carousel_spin","image_cluster_reel",
                      "cutout_grid_reel","split_reel"):
        for filepath in (photos or [])[:16]:
            try:
                with Image.open(filepath) as source_photo:
                    picture=source_photo.convert("RGB")
                    picture.thumbnail((640,960),Image.Resampling.LANCZOS)
                    original_photos.append(picture)
            except (OSError,ValueError):
                continue
    carousel_media=(original_photos[:16]
                    if original_photos else _distinct_carousel_frames(source,raw)
                    if cue.effect=="pov_carousel_spin" else [])
    compact_location=None
    if cue.compact:
        # Position is chosen ONCE for the whole animation, considering the
        # moving person's silhouette and every active subtitle frame.
        protected=[_compact_protection(mask,caption_position)
                   for mask in masks[::max(1,len(masks)//12)]]
        ranked=[
            (max(_compact_occupancy(mask,x,y,cue.effect)
                 for mask in protected),x,y)
            for x,y in _compact_candidates(cue.effect)
        ]
        risk,x,y=min(ranked)
        if risk>.025 and not cue.required:
            raise RuntimeError(
                "Нет безопасной области для текста без перекрытия человека "
                "и обычных субтитров."
            )
        compact_location=(x,y)
    grid_frames=[]
    if cue.effect=="screen_push_digital" and background_path is not None:
        if background_path.is_file():
            grid_frames=_read_video(background_path,0,cue.end-cue.start)
    target=folder/f"guide_fx_{index:02d}"
    target.mkdir(parents=True,exist_ok=True)
    for i in range(count):
        current=raw[min(i,len(raw)-1)]
        mask=masks[min(i,len(masks)-1)] if masks else None
        if cue.compact:
            frame=_compact_frame(
                cue.label,i/max(1,count-1),mask,
                compact_location,caption_position,effect=cue.effect,
                clips=original_photos or
                    [raw[j] for j in (0,len(raw)//2,len(raw)-1)],
                palette=palette,
                required=cue.required
            )
        else:
            frame=_draw(cue.effect,i/max(1,count-1),cue.label,current,raw,
                        i,mask,words,cue.start,palette,
                        carousel_media if cue.effect=="pov_carousel_spin"
                        else original_photos,
                        grid_frames[min(i,len(grid_frames)-1)] if grid_frames else None)
        frame.save(target/f"frame_{i:03d}.png",compress_level=2)
    return str(target/"frame_%03d.png"),count


# Every semantic animation has a STABLE and distinct sound, rather than
# alternating random pops/whooshes based on event index.
EFFECT_SOUND_FAMILY = {
    "pov_carousel_spin":"pages",
    "image_cluster_reel":"photo",
    "split_reel":"compare",
    "match_cut":"emphasis",
    "glass_explainer_reel":"glass",
    "apple_ui_toggles":"steps",
    "liquid_glass_graph":"graph",
    "notification_stack":"notify",
    # Previously published effect IDs remain supported in manual/legacy jobs.
    "screen_push_digital":"emphasis",
    "over_shoulder_zoom":"photo",
    "text_behind_me":"emphasis",
    "phone_3d_float":"glass",
    "split_clones":"compare",
    "sticker_cutout":"photo",
    "zoom_through_text":"emphasis",
    "cinematic_type_reel":"emphasis",
    "cutout_grid_reel":"compare",
    "depth_ui_reel":"glass",
}
SOUND_LENGTH = {
    "pages":0.32, "photo":0.14, "compare":0.28, "emphasis":0.19,
    "glass":0.36, "steps":0.34, "graph":0.42, "notify":0.31,
}
def sound_family(effect: str) -> str:
    return EFFECT_SOUND_FAMILY.get(effect,"emphasis")

def sound_track(path:Path,events:Sequence[GuideCue],duration:float,
                rate:int=48000,style:str="reference_soft"):
    """Synthesize low-volume context-specific SFX for *rendered* scene cues.

    Original voice/audio remains separate. Theme changes pitch/timbre subtly;
    clips and licensed recordings must be supplied separately.
    """
    if rate<8000 or rate>96000:raise ValueError("Invalid audio sample rate")
    # Audible over normal dialogue, but still quieter than the speech track.
    # Former 0.038..0.060 gains were effectively inaudible on phone speakers.
    base_volume={"pink_tender":0.080,"old_money":0.095,"burgundy":0.103,
                 "vintage":0.095}.get(style,0.112)
    pitch={"pink_tender":1.28,"old_money":0.88,"burgundy":0.79,
           "vintage":0.78}.get(style,1.)
    total=max(1,int(duration*rate))
    track=array("h",[0])*total
    for index,event in enumerate(events):
        family=sound_family(event.effect)
        start=max(0,int(event.start*rate))
        if start>=total:continue
        length=min(total-start,int(SOUND_LENGTH[family]*rate))
        for i in range(length):
            t=i/rate
            u=i/max(1,length)
            seed=(i*1664525+1013904223+index*13471)&0xFFFFFFFF
            noise=((seed>>8)/16777216.)*2-1
            if family=="pages":  # a soft, tactile 3-card shuffle
                env=math.sin(math.pi*u)**1.7
                value=.83*noise+.17*math.sin(2*math.pi*(330+120*u)*pitch*t)
            elif family=="photo":  # a discrete gentle shutter-like tick
                env=(1-math.exp(-t*200))*math.exp(-t*36)
                value=.6*noise+.4*math.sin(2*math.pi*570*pitch*t)
            elif family=="compare": # two distinct, quiet A/B taps
                phase=t%.13
                env=math.exp(-phase*65)*(.9 if t<.13 else .67)
                value=.25*noise+.75*math.sin(2*math.pi*640*pitch*t)
            elif family=="emphasis": # one warm emphasis beat
                env=(1-math.exp(-t*130))*math.exp(-t*26)
                value=.15*noise+.85*math.sin(2*math.pi*(560-250*u)*pitch*t)
            elif family=="glass": # lightly resonant chime for an explanation
                env=(1-math.exp(-t*100))*math.exp(-t*12)
                value=.72*math.sin(2*math.pi*780*pitch*t)+.28*math.sin(2*math.pi*1170*pitch*t)
            elif family=="steps": # three muted sequential clicks
                phase=t%.11
                env=math.exp(-phase*82)*(.8 if t<.11 else .59)
                value=.43*noise+.57*math.sin(2*math.pi*690*pitch*t)
            elif family=="graph": # a restrained ascending tone
                env=math.sin(math.pi*u)**1.9
                value=.74*math.sin(2*math.pi*(490+380*u)*pitch*t)+.26*math.sin(2*math.pi*950*pitch*t)
            else: # notify: two low and unobtrusive alert sounds
                phase=t%.17
                env=math.exp(-phase*23)*(.8 if t<.17 else .53)
                value=.82*math.sin(2*math.pi*690*pitch*t)+.18*math.sin(2*math.pi*1010*pitch*t)
            # No sound plays when a semantic animation was skipped by renderer.
            volume=base_volume*(.65 if style=="pink_tender" and family=="photo" else 1.)
            position=start+i
            track[position]=max(-32760,min(32760,
                track[position]+round(32767*volume*env*value)))
    path.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),"wb") as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate)
        f.writeframes(track.tobytes())
