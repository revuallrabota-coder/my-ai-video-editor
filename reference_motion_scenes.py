"""Original motion-graphics cutaways for short vertical videos.

The incoming video supplies all photographic frames. No screenshots or objects
from a third-party reference are reused. Scenes alternate retro-TV and moving
photo-collage compositions on an editorial white stage.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re
import subprocess
from typing import Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

Word = tuple[float, float, str]
WIDTH, HEIGHT = 720, 1280


@dataclass(frozen=True)
class MotionCue:
    start: float
    end: float
    label: str
    kind: str
    caption: str = ""


def select_motion_cues(words: Sequence[Word], duration: float,
                       density: str = "subtle") -> list[MotionCue]:
    """Pick a few speech-led illustrated scenes, avoiding the opening title."""
    if density not in {"subtle", "balanced", "dynamic"}:
        raise ValueError("Unknown motion scene density")
    if duration < 7:
        return []
    steps={"subtle":10.5,"balanced":8.8,"dynamic":7.0}
    gap=steps[density]
    anchor=4.6
    result=[]
    sorted_words=sorted(words,key=lambda w:float(w[0]))
    while anchor < duration - 1.7 and len(result)<5:
        candidates=[(float(a),str(w).strip()) for a,b,w in sorted_words
                    if anchor-0.8<=a<=anchor+2.6 and b>a
                    and len(re.sub(r"[^\wа-яё]","",w,re.I))>=4]
        if candidates:
            timestamp,word=max(candidates,key=lambda it:len(it[1]))
            label=re.sub(r"[^\wа-яёА-ЯЁ\-]","",word)[:21].upper()
            start=max(anchor,timestamp)
        else:
            future=[(float(a),str(w).strip()) for a,b,w in sorted_words
                    if a>=anchor and b>a and len(w.strip())>=3]
            if not future:
                anchor+=gap
                continue
            start,word=future[0]
            label=re.sub(r"[^\wа-яёА-ЯЁ\-]","",word)[:21].upper()
        if not label:
            anchor+=gap
            continue
        start=min(start,duration-1.65)
        finish=min(duration-.02,start+2.65)
        context=[re.sub(r"[^а-яёА-ЯЁa-zA-Z0-9\-]","",str(w))
                 for a,b,w in sorted_words if start-1.25<=a<=start+1.3
                 and b>a]
        excerpt=" ".join(w for w in context if w).strip()[:44]
        result.append(MotionCue(start,finish,label,
                                "television" if len(result)%2==0 else "collage",
                                excerpt))
        anchor=max(start,anchor)+gap
    return result


def _font(size: int, bold: bool=False):
    file=("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
          if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    try:
        return ImageFont.truetype(file,size)
    except OSError:
        return ImageFont.load_default()


def _star(draw: ImageDraw.ImageDraw,x: int,y: int,r: int,
          color: tuple[int,int,int,int]) -> None:
    points=[]
    for i in range(8):
        rad=r if i%2==0 else r*.19
        angle=-math.pi/2+i*math.pi/4
        points.append((x+math.cos(angle)*rad,y+math.sin(angle)*rad))
    draw.polygon(points,fill=color)


def _frame(video: Path, t: float, w: int, h: int) -> Image.Image:
    """Sample user's own video, not reference imagery or generated faces."""
    command=["ffmpeg","-hide_banner","-loglevel","error","-y",
             "-ss",str(max(.1,t)),"-i",str(video),
             "-frames:v","1","-f","image2pipe","-vcodec","mjpeg","-"]
    try:
        result=subprocess.run(command,capture_output=True,check=True,timeout=45)
        from io import BytesIO
        with Image.open(BytesIO(result.stdout)) as im:
            frame=im.convert("RGB")
            return ImageOps.fit(frame,(w,h),Image.Resampling.LANCZOS)
    except (OSError,ValueError,subprocess.CalledProcessError,
            subprocess.TimeoutExpired):
        return Image.new("RGB",(w,h),(177,143,161))


def _photo_card(frame: Image.Image, width: int, height: int,
                rotate: int=0) -> Image.Image:
    canvas=Image.new("RGBA",(width+28,height+38),(0,0,0,0))
    d=ImageDraw.Draw(canvas)
    d.rounded_rectangle((0,0,width+27,height+37),radius=7,
                        fill=(250,248,247,255),outline=(225,198,206,255),width=2)
    canvas.paste(frame.resize((width,height)),(14,13))
    return canvas.rotate(rotate,Image.Resampling.BICUBIC,expand=True)


def make_motion_assets(source: Path, folder: Path, cue: MotionCue,
                       index: int) -> list[Path]:
    """Build three independent full-stage RGBA layers for staggered motion."""
    folder.mkdir(parents=True,exist_ok=True)
    bg=Image.new("RGBA",(WIDTH,HEIGHT),(255,254,253,255))
    b=ImageDraw.Draw(bg)
    b.rounded_rectangle((28,90,692,1175),radius=35,
                        outline=(240,219,228,255),width=3)
    excerpt=cue.caption[:42] or "REELS · MOTION"
    excerpt_size=22
    while excerpt_size>14 and b.textbbox((0,0),excerpt,font=_font(excerpt_size))[2]>525:
        excerpt_size-=1
    b.text((95,166),excerpt,font=_font(excerpt_size),
           fill=(159,120,145,255))
    label=cue.label
    size=57
    while size>25 and b.textbbox((0,0),label,font=_font(size,True))[2]>550:
        size-=2
    b.text((95,218),label,font=_font(size,True),fill=(46,39,43,255))
    b.rounded_rectangle((95,289,95+min(490,22*len(label)+90),302),
                        radius=6,fill=(245,179,209,255))
    b.text((96,1110),"REELS · MOTION STORY",font=_font(17),
           fill=(171,126,151,255))
    main=Image.new("RGBA",(WIDTH,HEIGHT),(0,0,0,0))
    d=ImageDraw.Draw(main)

    if cue.kind=="television":
        # Original illustrated pink retro TV, with the user's clip on screen.
        d.rounded_rectangle((87,367,637,882),radius=41,
                            fill=(222,122,170,255),outline=(141,74,119,255),width=11)
        d.rounded_rectangle((105,387,618,863),radius=32,
                            outline=(255,208,233,240),width=7)
        d.rounded_rectangle((131,417,483,801),radius=43,
                            fill=(71,55,69,255),outline=(102,57,84,255),width=8)
        frame=_frame(source,cue.start+.55,326,353).convert("RGBA")
        mask=Image.new("L",frame.size,0)
        ImageDraw.Draw(mask).rounded_rectangle((0,0,325,352),radius=29,fill=255)
        main.paste(frame,(145,432),mask)
        d=ImageDraw.Draw(main)
        d.ellipse((522,467,586,531),fill=(255,210,231,255),
                  outline=(103,59,88,255),width=6)
        d.ellipse((534,478,574,519),fill=(115,68,106,255))
        d.ellipse((522,566,586,630),fill=(255,210,231,255),
                  outline=(103,59,88,255),width=6)
        d.ellipse((534,579,574,619),fill=(115,68,106,255))
        for y in range(680,780,16):
            d.line((521,y,589,y),fill=(114,64,102,255),width=5)
        d.line((171,891,266,891),fill=(110,65,94,255),width=6)
        d.line((483,891,573,891),fill=(110,65,94,255),width=6)
    else:
        # Staggered picture boards showing three different moments of OWN clip.
        shots=[_frame(source,cue.start+dt,220,354)
               for dt in (.12,.67,1.31)]
        places=((70,410,-8),(312,452,8),(169,669,-4))
        for i,(x,y,angle) in enumerate(places):
            im=_photo_card(shots[i],220,354,angle)
            main.alpha_composite(im,(x,y))
        d=ImageDraw.Draw(main)
        d.rounded_rectangle((407,367,603,423),radius=28,
                            fill=(242,169,203,255))
        d.text((505,396),"СМОТРИ",font=_font(27,True),
               fill=(255,255,255,255),anchor="mm")

    dec=Image.new("RGBA",(WIDTH,HEIGHT),(0,0,0,0))
    dd=ImageDraw.Draw(dec)
    if cue.kind=="television":
        # A stylized audience row at the very bottom, like an editorial silhouette.
        pink=(240,160,199,255)
        dd.rectangle((44,1040,676,1190),fill=pink)
        for x,r in ((75,35),(148,39),(226,48),(300,35),
                    (382,43),(464,37),(546,42),(620,39)):
            dd.ellipse((x-r,987-r,x+r,987+r),fill=pink)
            dd.ellipse((x-r-12,1022,x+r+12,1130),fill=pink)
    else:
        dd.arc((60,350,640,980),180,268,fill=(242,167,196,255),width=7)
        dd.polygon([(573,523),(556,490),(599,499)],fill=(242,167,196,255))
        dd.rounded_rectangle((106,982,430,1025),radius=19,
                             fill=(246,202,219,255))
        dd.text((268,1004),"КАДР ЗА КАДРОМ",font=_font(19,True),
                fill=(133,71,109,255),anchor="mm")
    for i,(x,y,r) in enumerate(((598,298,24),(91,347,14),(574,947,28))):
        _star(dd,x,y,r,(239,157,189,255) if i%2 else (224,174,103,255))
    files=[]
    for tag,layer in (("back",bg),("main",main),("decoration",dec)):
        target=folder/f"motion_{index}_{tag}.png"
        layer.save(target)
        files.append(target)
    return files
