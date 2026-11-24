"""Original immersive editorial photo/video carousel for a vertical Reels cutaway.

The backdrop completely replaces the speaker for a short cutaway. Original
spoken audio continues unchanged. Photo panels are never stock imagery and
must come from user-owned photos or genuine frames of the supplied video.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

SIZE=(360,640)
BG={
    "burgundy":((35,12,24),(89,46,54),(231,190,163)),
    "burgundy_brown":((35,12,24),(89,46,54),(231,190,163)),
    "old_money":((29,27,24),(72,62,50),(222,199,160)),
    "pink_tender":((68,37,50),(115,70,88),(251,209,220)),
    "vintage":((24,23,22),(66,55,47),(202,170,124)),
    "reference_soft":((30,26,31),(69,47,58),(233,190,195)),
    "off":((30,26,31),(69,47,58),(233,190,195)),
}


@lru_cache(maxsize=12)
def _backdrop(palette: str) -> Image.Image:
    base,raised,accent=BG.get(palette,BG["reference_soft"])
    image=Image.new("RGBA",SIZE)
    draw=ImageDraw.Draw(image,"RGBA")
    for y in range(640):
        frac=y/639
        pulse=(1-abs(frac-.45)*1.55)*.48
        color=tuple(max(0,min(255,round(c+(raised[i]-c)*pulse)))
                    for i,c in enumerate(base))
        draw.line((0,y,359,y),fill=(*color,255))
    # A quiet matte editorial composition, not a boxed sticker.
    # IMPORTANT: Drawing a semi-transparent line on an RGBA background with
    # ImageDraw replaces the alpha rather than blending it. That previously
    # leaked the old talking-head image through the supposedly FULL cutaway.
    def opaque_tint(strength):
        return tuple(round(base[k]*(1-strength)+accent[k]*strength)
                     for k in range(3))+(255,)
    for x in (19,340):
        draw.line((x,45,x,594),fill=opaque_tint(.15),width=1)
    draw.line((31,51,329,51),fill=opaque_tint(.28),width=1)
    draw.line((31,589,329,589),fill=opaque_tint(.28),width=1)
    return image


def _fit_portrait(source: Image.Image, width: int, height: int,
                  index: int) -> Image.Image:
    picture=source.convert("RGB")
    # Only a genuine crop of the original; avoid artificial AI details.
    scale=max(width/picture.width,height/picture.height)
    resized=picture.resize((math.ceil(picture.width*scale),
                            math.ceil(picture.height*scale)),
                           Image.Resampling.BILINEAR)
    excess_x=resized.width-width
    excess_y=resized.height-height
    # With a single wide studio shot, alternate natural viewing positions.
    offset=(.50,.43,.56)[index%3]
    left=max(0,min(excess_x,round(excess_x*offset)))
    top=max(0,min(excess_y,round(excess_y*(.46 if index==1 else .52))))
    return resized.crop((left,top,left+width,top+height)).convert("RGBA")


def _portrait_panel(photo: Image.Image, width: int, height: int,
                    accent: tuple[int,int,int], index: int) -> Image.Image:
    image=Image.new("RGBA",(width+14,height+14),(0,0,0,0))
    draw=ImageDraw.Draw(image,"RGBA")
    draw.rounded_rectangle((5,6,width+10,height+11),radius=17,
                           fill=(0,0,0,106))
    photo=_fit_portrait(photo,width,height,index)
    rounded=Image.new("L",(width,height),0)
    ImageDraw.Draw(rounded).rounded_rectangle(
        (0,0,width-1,height-1),radius=15,fill=255)
    image.paste(photo,(7,5),rounded)
    draw.rounded_rectangle((7,5,width+6,height+4),radius=15,
                           outline=(*accent,232),width=2)
    return image


def draw_carousel(progress: float, photos: Sequence[Image.Image],
                  palette: str="reference_soft") -> Image.Image:
    """Large cinematic sequence: each new photo glides to the center.

    Three full-height image compositions, with adjacent slides peeking at the
    edges. No irrelevant automatic text from transcripts and no three small
    repeated screenshots in a corner.
    """
    if not photos:
        raise ValueError("Для карусели нужны настоящие кадры или фотографии.")
    base,raised,accent=BG.get(palette,BG["reference_soft"])
    image=_backdrop(palette).copy()
    draw=ImageDraw.Draw(image,"RGBA")
    p=max(0.,min(1.,float(progress)))
    # Constant movement across cards, with smooth acceleration at scene ends.
    travel=2*(p*p*(3-2*p))
    visible=min(2,round(travel))
    cards=[photos[k%len(photos)] for k in range(3)]
    depth=[]
    for k in range(3):
        rel=k-travel
        if abs(rel)>1.73:
            continue
        depth.append((abs(rel),k,rel))
    for _,k,rel in sorted(depth,reverse=True):
        abs_rel=min(1.6,abs(rel))
        scale=max(.64,1-.30*abs_rel)
        width=round(255*scale)
        height=round(456*scale)
        panel=_portrait_panel(cards[k],width,height,accent,k)
        horizontal=180+202*rel
        vertical=304+round(25*abs_rel)+round(4*math.sin(p*math.pi*2))
        center_x=round(horizontal-panel.width/2)
        center_y=round(vertical-panel.height/2)
        # Correct RGBA composition onto an OPAQUE editorial background.
        # paste(..., mask=panel) could lower alpha around shadows and cause
        # translucent holes that show the old talking footage underneath.
        left=max(0,-center_x);top=max(0,-center_y)
        right=min(panel.width,360-center_x)
        bottom=min(panel.height,640-center_y)
        if right>left and bottom>top:
            clipped=panel.crop((left,top,right,bottom))
            image.alpha_composite(
                clipped,(max(0,center_x),max(0,center_y)))
    draw=ImageDraw.Draw(image,"RGBA")
    # Subtle slide counter and progress, no unrelated generated headlines.
    font_path="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font=ImageFont.truetype(font_path,12)
    draw.text((31,75),f"{visible+1:02d} / 03",
              font=font,fill=(*accent,255))
    for k in range(3):
        x=150+k*21
        dim=tuple(round(base[j]*.68+accent[j]*.32) for j in range(3))
        draw.rounded_rectangle((x,563,x+13,565),radius=1,
                               fill=(accent if k==visible else dim)+(255,))
    draw.line((31,602,31+round(298*p),602),fill=(*accent,255),width=2)
    # Cinematic dissolve back to talking head; no harsh black flash.
    opacity=min(1.,p/.12,(1-p)/.12)
    if opacity<1.:
        image.putalpha(image.getchannel("A").point(
            lambda value:round(value*max(0.,opacity))))
    return image
