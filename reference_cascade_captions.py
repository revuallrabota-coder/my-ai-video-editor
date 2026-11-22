"""Reference-matched editorial subtitles: SMALL -> BIG -> SMALL.

Unlike a block-level phrase animation, each spoken word gets a stable,
measured slot inside one composition. The first context words appear gently;
the emphasized pink serif word joins when spoken; follow-up small words join
the SAME composition rather than flying off in random directions.
Words stay visible together, so the user reads growing phrases naturally.

A low-opacity oval glow is drawn directly behind the measured word it belongs
to, with identical animation coordinates and lifetime. No broad rectangle,
misaligned separate shadow, or hard per-word jumps.
"""
from __future__ import annotations

import re
from typing import Sequence

from font_presets import choose_font, FontSpec
from reference_dynamic_captions import (
    _measure_width, fit_caption_size, _oval_phrase_shadow,
    phrase_groups, phrase_motion, COLOR_PALETTES
)
from signature_captions import ass_color, ass_time, pick_main_word, safe_text, STOP_WORDS

Word=tuple[float,float,str]


def oval_path(w: int, h: int) -> str:
    """Capsule in positive coordinates for ASS top-left anchor (\\an7).

    Negative vector coordinates combined with \\an5 can be laid out by libass
    relative to the glyph bounding box, creating the detached shadow the user
    observed. A top-left origin matches the exact measured word rectangle.
    """
    w=max(64,round(w));h=max(36,round(h))
    r=h/2;k=.55228475
    n=lambda x:round(x)
    return (
        f"m {n(r)} 0 l {n(w-r)} 0 "
        f"b {n(w-r+k*r)} 0 {w} {n(r-k*r)} {w} {n(r)} "
        f"b {w} {n(h-r+k*r)} {n(w-r+k*r)} {h} {n(w-r)} {h} "
        f"l {n(r)} {h} "
        f"b {n(r-k*r)} {h} 0 {n(h-r+k*r)} 0 {n(h-r)} "
        f"b 0 {n(r-k*r)} {n(r-k*r)} 0 {n(r)} 0"
    )


EDITORIAL_KEYWORDS=(
    "ошиб","маникюр","покры","кутикул","результ","важн",
    "секунд","врем","вручную","монтир","монтаж","выреза",
    "добавля","субтитр","картин","неправильн","проблем",
    "сравн","причин","исправ","френч","акцент","съёмк",
    "скорост","качеств","клиент",
)


def _pick_editorial_keyword(group: Sequence[Word]) -> int:
    """Emphasize meaningful spoken concepts, not filler or merely length."""
    original=pick_main_word(group)
    scored=[]
    for i,(_,_,raw) in enumerate(group):
        word=re.sub(r"[^\wа-яёА-ЯЁ-]","",str(raw)).lower()
        weight=min(12,len(word))*.75
        if word in STOP_WORDS or len(word)<=2:
            weight-=7
        if any(stem in word for stem in EDITORIAL_KEYWORDS):
            weight+=5.5
        weight+=.20*i
        scored.append((weight,i))
    best=max(scored)[1]
    # If all words are stop words, preserve legacy emphasis choice.
    return best if scored[best][0]>0 else original


def _row_positions(words: Sequence[tuple[int,str]], cy: int,
                   center_x: int, font: FontSpec, size: int) -> dict[int,tuple[int,int]]:
    """Distribute a small helper row with fixed spacing, always in safe area."""
    widths=[_measure_width(t,size,font) for _,t in words]
    gap=round(size*.28)
    total=sum(widths)+gap*max(0,len(widths)-1)
    first=center_x-total/2
    first=max(91,min(629-total,first)) if total<=538 else 91
    positions={}
    for (index,_),width in zip(words,widths):
        positions[index]=(round(first+width/2),cy)
        first+=width+gap
    return positions


def _caption_slots(group: Sequence[Word], index: int, caption_position: str,
                   small: FontSpec, big: FontSpec,
                   animation_style: str="float", subject_side: str="center") -> tuple[dict[int,tuple[int,int,int,bool]],int]:
    main=_pick_editorial_keyword(group)
    cx,cy,*_=phrase_motion(index,"top" if caption_position=="studio" else caption_position,animation_style)
    if caption_position=="studio":
        # Keep moving words in the upper translucent palette while leaving
        # the full-height portrait visible below and through it.
        cy-=48
    main_word=safe_text(group[main][2]).upper()
    accent_size=fit_caption_size(main_word,53,big,max_width=485)
    accent_size=max(23,accent_size)
    main_w=_measure_width(main_word,accent_size,big)
    before=[(i,safe_text(group[i][2])) for i in range(main)]
    after=[(i,safe_text(group[i][2])) for i in range(main+1,len(group))]
    # On some phrases the little continuation joins to the RIGHT of the
    # highlight, as in the provided 50-second video reference.
    helper_size=27
    if before or after:
        longest=max((len(x[1]) for x in before+after),default=0)
        if longest>=16:helper_size=24
    result={}
    to_side=(bool(after) and index%3==1 and len(after)<=2 and
             main_w+sum(_measure_width(x[1],helper_size,small) for x in after)+48<470)
    main_x=cx
    if to_side:
        after_size=sum(_measure_width(x[1],helper_size,small) for x in after)
        main_x=round(cx-after_size/2-10)
    main_x=max(round(86+main_w/2),min(round(634-main_w/2),main_x))
    result[main]=(main_x,cy,accent_size,True)
    if before:
        prior=_row_positions(before,cy-44,cx-8,small,helper_size)
        result.update({i:(x,y,helper_size,False) for i,(x,y) in prior.items()})
    if after:
        if to_side:
            # Keep its little neighbor near, never "floating" elsewhere.
            center=round(main_x+main_w/2+16+
                sum(_measure_width(t,helper_size,small) for _,t in after)/2)
            center=min(610,center)
            latter=_row_positions(after,cy+9,center,small,helper_size)
        else:
            latter=_row_positions(after,cy+42,cx+13,small,helper_size)
        result.update({i:(x,y,helper_size,False) for i,(x,y) in latter.items()})
    if subject_side in ("left", "right"):
        # Narrow caption column next to the person: maintain the very same
        # word-by-word fade, soft travel and linked halo coordinates.
        target_x = 176 if subject_side == "left" else 544
        factor = .49
        result = {
            i: (round(target_x + (x - cx) * factor), y,
                max(15, round(size * factor)), is_big)
            for i, (x, y, size, is_big) in result.items()
        }
    return result,main


def build_reference_cascade_ass(
    words: Sequence[Word], *, color: str="auto",
    caption_position: str="middle",
    font_profile: str="old_money", small_font_profile: str="refined",
    caption_variant: str="reference_soft",
    background_style: str="occasional",
    animation_style: str="float",
    intro_animated: bool=False,
    intro_title: str="",
    subject_side: str="center",
) -> tuple[str,int]:
    if subject_side not in ("center", "left", "right"):
        raise ValueError("Неизвестная сторона расположения текста.")
    if caption_position not in ("top","middle","bottom","studio"):
        raise ValueError("Недопустимое положение субтитров.")
    if caption_variant not in COLOR_PALETTES:
        raise ValueError("Недопустимая палитра.")
    if background_style not in ("off","occasional","frequent","always"):
        raise ValueError("Недопустимый стиль тени.")
    if animation_style not in ("float","slide","pop"):
        raise ValueError("Недопустимый тип появления.")
    small,big=choose_font(small_font_profile),choose_font(font_profile)
    accent_hex,small_hex=COLOR_PALETTES[caption_variant]
    highlight=ass_color(accent_hex if color=="auto" else color)
    helper=ass_color(small_hex)
    header=(
        "[Script Info]\nScriptType: v4.00+\n"
        "PlayResX: 720\nPlayResY: 1280\nWrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: CascadeSmall,{small.name},27,{helper},{helper},"
        "&H92201923,&HD3242026,"
        f"{small.bold},{small.italic},0,0,{small.scale_x},{small.scale_y},"
        "0,0,1,0.50,0.50,5,70,70,20,1\n"
        f"Style: CascadeBig,{big.name},53,{highlight},{highlight},"
        "&H84201923,&HC3242026,"
        f"{big.bold},{big.italic},0,0,{big.scale_x},{big.scale_y},"
        "0,0,1,0.7,0.5,5,70,70,20,1\n"
        "Style: CascadeHalo,DejaVu Sans,20,&H00201923,&H00201923,"
        "&H00201923,&H00201923,0,0,0,0,100,100,"
        "0,0,1,0,0,5,0,0,0,1\n"
        "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    groups=phrase_groups(words)
    events=[]
    for group_index,group in enumerate(groups):
        if not group:continue
        slots,main=_caption_slots(
            group,group_index,caption_position,small,big,animation_style,
            subject_side=subject_side
        )
        group_start=max(0.0,float(group[0][0]))
        end=max(group[-1][1]+.20,group_start+.68)
        if group_index+1<len(groups):
            end=min(end,max(group_start+.30,groups[group_index+1][0][0]-.02))
        if end-group_start<.15:continue
        side=-1 if group_index%2==0 else 1
        for word_index,(begin,finish,raw) in enumerate(group):
            if word_index not in slots:continue
            # First quick pair forms one gentle starting stage. Subsequent
            # words accumulate at their own spoken boundary.
            start=group_start if begin-group_start<=.20 else max(group_start,begin-.035)
            if end-start<.12:continue
            x,y,size,is_big=slots[word_index]
            spoken=safe_text(raw)
            if not spoken:continue
            shown=spoken.upper() if is_big else spoken
            font=big if is_big else small
            measured=_measure_width(shown,size,font)
            # These are optional, subtle entrance variants inside the SAME
            # cumulative layout; changing them cannot reset other effects.
            drift=side*(
                (17 if is_big else 13) if animation_style=="slide"
                else (4 if is_big else 3) if animation_style=="pop"
                else (9 if is_big else 7)
            )
            rise=(4 if animation_style=="slide" else
                  12 if animation_style=="pop" else
                  9 if is_big else 7)
            # Over 200-260ms the word settles, not a sharp jump or bounce.
            entrance=min(260,max(135,round((end-start)*1000*.20)))
            fadein=min(210,max(95,round((end-start)*1000*.15)))
            fadeout=min(155,max(60,round((end-start)*1000*.10)))
            duration_ms=max(100,round((end-start)*1000))
            move=(rf"\move({x+drift},{y+rise},{x},{y},0,"
                  f"{min(260,duration_ms)})")
            alpha=(r"\clip(72,188,648,1100)")
            fscale=round(font.scale_x*.96)
            gscale=round(font.scale_y*.96)
            common=(r"\an5"+move+rf"\fad({fadein},{fadeout})"
                    +alpha)
            style="CascadeBig" if is_big else "CascadeSmall"
            text_prefix=(
                "{"+common
                +rf"\fs{size}\fscx{fscale}\fscy{gscale}"
                +rf"\t(0,{entrance},\fscx{font.scale_x}\fscy{font.scale_y})"
                +r"\blur0.25"+"}"
            )
            # Every halo is centered on the exact glyph slot. Never use
            # the complete phrase's width under a single word.
            has_halo=(background_style!="off" and
                      (is_big or background_style=="always" or
                       background_style=="frequent" and word_index%2==0))
            if has_halo:
                width=min(515,max(65,round(measured+15)))
                height=max(38,round(size*1.10+11))
                halo=oval_path(width,height)
                # The visual shadow is anchored to each actual word, not to
                # the center of the complete phrase or independent layout.
                plate_color=(highlight if is_big else "&H00251D24&")
                x1=round(x-width/2)
                y1=round(y-height/2)
                # Apply identical integer-pixel movement to the glyph and
                # oval. Rounding each keyframe separately causes 1px jitter.
                x0=x1+drift
                y0=y1+rise
                halo_move=(
                    rf"\move({x0},{y0},{x1},{y1},0,"
                    f"{min(260,duration_ms)})"
                )
                shadow_prefix=(
                    "{"+r"\an7"+halo_move
                    +rf"\fad({fadein},{fadeout})"+alpha
                    +r"\blur5.3"
                    +rf"\1c{plate_color}\1a&HAD&\p1"+"}"
                )
                events.append(
                    f"Dialogue: 1,{ass_time(start)},{ass_time(end)},"
                    f"CascadeHalo,,0,0,0,,{shadow_prefix}{halo}{{\\p0}}\n"
                )
            events.append(
                f"Dialogue: 2,{ass_time(start)},{ass_time(end)},"
                f"{style},,0,0,0,,{text_prefix}{shown}\n"
            )
    # No oversized automatically generated hero: explicit top title uses
    # top_video_title.py. This is intentionally closer to the video reference.
    return header+"".join(events),len(events)
