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


def _clean(s: str) -> str:
    return re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9% -]","",s).strip()


def _label(words: Sequence[Word], t: float, limit: int = 22) -> str:
    local=[_clean(str(w)) for st,en,w in words
           if st<=t+2.8 and en>=t-.3 and len(_clean(str(w)))>=3]
    return (max(local,key=len) if local else "АКЦЕНТ").upper()[:limit]


def plan(words: Sequence[Word], duration: float, choice: str,
         density: str = "balanced") -> list[GuideCue]:
    """One 3s primary effect at a time, >=1s clear air before the next.

    No silent overlap between the 18 choices or legacy studio ornaments.
    Explicit mode repeats only at long intervals; auto is semantic, not random.
    """
    if choice not in EFFECTS and choice not in ("off","auto"):
        raise ValueError("Неизвестный приём из гайда: "+choice)
    if choice=="off" or duration<1.05:
        return []
    if density not in ("subtle","balanced","dynamic"):
        raise ValueError("Недопустимая частота эффектов.")
    interval={"subtle":10.0,"balanced":7.0,"dynamic":5.0}[density]
    starts=[max(.15,float(st)) for st,en,w in words if 0<=st<duration-1.05
            and len(_clean(str(w)))>=3]
    if not starts:return []  # never fabricate a phrase for a silent clip
    out=[]
    last=-interval
    for start in starts:
        if start-last<interval or start+1.05>duration:continue
        if len(out)>=({"subtle":5,"balanced":8,"dynamic":12}[density]):break
        chosen=choice
        if choice=="auto":
            window=" ".join(_clean(str(w)).lower() for st,en,w in words
                            if st>=start-.4 and st<=start+2.5)
            if any(q in window for q in ("процент","рост","прогресс","%")):
                chosen="liquid_glass_graph"
            elif any(q in window for q in ("ошибк","неправил","ошибл","косяк")):
                chosen="match_cut"
            elif any(q in window for q in ("салон","студи","клиент")):
                chosen="image_cluster_reel"
            elif any(q in window for q in ("телефон","приложен","экран")):
                chosen="phone_3d_float"
            elif any(q in window for q in ("пошаг","пункт","этап","настро")):
                chosen="apple_ui_toggles"
            elif any(q in window for q in ("сравн","разниц","вместо")):
                chosen="split_reel"
            elif any(q in window for q in ("главно","важно","запомн")):
                chosen="cinematic_type_reel"
            else:
                chosen=("screen_push_digital","over_shoulder_zoom",
                        "notification_stack","liquid_glass_graph",
                        "cinematic_type_reel")[len(out)%5]
        end=min(duration-.02,start+SECS)
        if end-start<1.0:continue
        out.append(GuideCue(chosen,start,end,_label(words,start)))
        last=start
    if not out and choice!="auto" and duration>=1.05:
        out=[GuideCue(choice,.05,min(duration-.01,SECS),_label(words,.05))]
    return out


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
          palette: str) -> Image.Image:
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
        for k in range(8):
            ang=(k*2*math.pi/8+p*5.76) # ~110 degrees/sec over 3s
            x=int(180+118*math.sin(ang)-35)
            y=int(310+85*math.cos(ang)-49)
            sub=frames[(frame_index+k*4)%len(frames)]
            card=_frame_draw(sub,(max(0,x),max(0,y),min(360,x+70),min(640,y+98)))
            if math.cos(ang)>0 and mask is not None:
                card.putalpha(ImageChops.subtract(card.getchannel("A"),mask))
            img.alpha_composite(card)
        d=ImageDraw.Draw(img)
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
            _text(d,(x+73,241),"1" if k==0 else "2",15,cream)
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
            img.alpha_composite(_frame_draw(frames[(frame_index+k*6)%len(frames)],
                                             (x,y,x+105,y+137)))
    elif effect=="cutout_grid_reel":
        for k in range(4):
            x=(k%2)*180;y=(k//2)*320
            sub=frames[(frame_index+int(p>.37)*11+k*6)%len(frames)]
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
            img.alpha_composite(_frame_draw(frames[(frame_index+k*4)%len(frames)],
                                              (x,540,x+77,629),radius=4))
    else:
        raise ValueError("Сцена отсутствует: "+effect)
    if effect not in FULL_FX:
        alpha=img.getchannel("A")
        alpha=alpha.point(lambda a:int(a*max(0,min(1,fade))))
        img.putalpha(alpha)
    return img


def render(source: Path, folder: Path, cue:GuideCue, index:int,
           words:Sequence[Word],palette:str="burgundy_brown") -> tuple[str,int]:
    """Return image2 input path and frame count for one verified 3-second cue."""
    if cue.effect not in EFFECTS:
        raise ValueError("Эффект не поддерживается.")
    count=max(1,int(math.ceil((cue.end-cue.start)*FPS)))
    raw=_read_video(source,cue.start,cue.end-cue.start)
    if not raw:raise RuntimeError("Нет кадров для монтажа.")
    if cue.effect in SUBJECT_FX:
        masks=_mask_frames(raw)
    else:
        masks=[]
    target=folder/f"guide_fx_{index:02d}"
    target.mkdir(parents=True,exist_ok=True)
    for i in range(count):
        current=raw[min(i,len(raw)-1)]
        mask=masks[min(i,len(masks)-1)] if masks else None
        frame=_draw(cue.effect,i/max(1,count-1),cue.label,current,raw,
                    i,mask,words,cue.start,palette)
        frame.save(target/f"frame_{i:03d}.png",compress_level=2)
    return str(target/"frame_%03d.png"),count


def sound_track(path:Path,events:Sequence[GuideCue],duration:float,rate:int=48000):
    """Three families of original SFX. Different consecutive events differ.

    No supplied copyrighted sounds are bundled by this guide; these synthetic
    sounds are optional embellishments over the unchanged spoken audio.
    """
    total=max(1,int(duration*rate))
    track=array("h",[0])*total
    for index,event in enumerate(events):
        family=index%3
        if event.effect in ("screen_push_digital","match_cut","zoom_through_text"):
            family=(index+1)%3
        start=max(0,int(event.start*rate))
        length=min(total-start,int((.25,.4,.19)[family]*rate))
        for i in range(max(0,length)):
            t=i/rate
            seed=(i*1664525+1013904223+index*13731)&0xFFFFFFFF
            noise=((seed>>8)/16777216.0)*2-1
            if family==0:  # soft whoosh
                envelope=math.sin(math.pi*i/max(1,length))**1.6
                wavevalue=noise*.85+math.sin(2*math.pi*(410+700*t)*t)*.15
            elif family==1: # tactile typewriter ticks
                pulse=t%.065
                envelope=math.exp(-pulse*92)
                wavevalue=noise*.68+math.sin(2*math.pi*1150*t)*.32
            else: # pop/snap, not another whoosh
                envelope=(1-math.exp(-t*100))*math.exp(-t*22)
                wavevalue=math.sin(2*math.pi*(820-550*t)*t)
            track[start+i]=max(-32767,min(32767,track[start+i]+
                round(32767*.065*envelope*wavevalue)))
    path.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),"wb") as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate)
        f.writeframes(track.tobytes())
