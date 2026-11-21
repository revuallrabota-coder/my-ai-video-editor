"""Читаемые субтитры Reels по таймкодам речи, с безопасными полями.

Все текстовые слои и подложки используют ОДИН и тот же центр и время.
Ни один длинный акцент не должен пересекать края изображения 9:16.
"""
from __future__ import annotations

import math
import re
import subprocess
from functools import lru_cache
from typing import Sequence

from font_presets import FontSpec, choose_font
from signature_captions import (
    ass_color, ass_time, pick_main_word, safe_text, split_groups,
)
from word_captions import word_events

Word = tuple[float, float, str]
PLAY_WIDTH, PLAY_HEIGHT = 720, 1280
TEXT_SAFE_WIDTH = 500
CENTER_X = PLAY_WIDTH // 2

COLOR_PALETTES = {
    "editorial": ("#F0443E", "#FFFFFF"),
    "luxe": ("#D8BFA0", "#FFF4E5"),
    "minimal": ("#FFFFFF", "#EFEFEF"),
    "neon": ("#D7FF6C", "#F3F7E7"),
    "pop": ("#FF7BB6", "#FFF3F9"),
    "old_money": ("#CEB68A", "#FFF3E1"),
    "vintage": ("#D79B6D", "#F4DFC7"),
    "street": ("#DEEF5A", "#F5F5F0"),
    "elegant": ("#F0DBDC", "#FFFFFF"),
}


@lru_cache(maxsize=24)
def _font_file(family: str) -> str | None:
    """Use exact installed font metrics where available, never download fonts."""
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{file}", family],
            capture_output=True, text=True, timeout=4, check=True,
        )
        value = result.stdout.strip()
        from pathlib import Path
        if value and Path(value).is_file():
            return value
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _estimated_width(text: str, size: int, font: FontSpec) -> float:
    """Conservative fallback including Cyrillic width."""
    units = 0.0
    for char in text:
        units += (0.35 if char.isspace() else
                  0.86 if char.isalpha() and char.isupper() else
                  0.70 if char.isalpha() else 0.50)
    return units*size*font.scale_x/100


def _measure_width(text: str, size: int, font: FontSpec) -> float:
    try:
        from PIL import ImageFont
        path = _font_file(font.name)
        if path:
            rendered = ImageFont.truetype(path, size=size)
            # libass may choose the bold/italic face, wider than fc-match.
            return rendered.getlength(text)*font.scale_x/100*1.15
    except (ImportError, OSError, ValueError):
        pass
    return _estimated_width(text,size,font)


def fit_caption_size(text: str, requested: int, font: FontSpec,
                     *, max_width: int = TEXT_SAFE_WIDTH) -> int:
    """Shrink overlong Cyrillic words to fit a central Reels safe area."""
    target=max_width*0.88
    for size in range(min(82,max(18,int(requested))),17,-1):
        if _measure_width(text,size,font)<=target:
            return size
    return 18


def _rounded_plate(half_width: int, half_height: int, radius: int=15) -> str:
    """ASS positive-coordinate polygon anchored at its TOP-LEFT corner."""
    w,h=max(72,2*half_width),max(42,2*half_height)
    r=min(radius,w//2,h//2)
    return (f"m {r} 0 l {w-r} 0 "
            f"b {w} 0 {w} {r//2} {w} {r} "
            f"l {w} {h-r} b {w} {h-r//2} {w} {h} {w-r} {h} "
            f"l {r} {h} b 0 {h} 0 {h-r//2} 0 {h-r} "
            f"l 0 {r} b 0 {r//2} 0 0 {r} 0")


def _wrap_two_lines(text: str, font: FontSpec, requested: int) -> tuple[str,int,float,int]:
    """Wrap too-long phrases while maintaining a readable font size."""
    size=fit_caption_size(text,requested,font)
    tokens=text.split()
    if len(tokens)<2 or size>=max(26,requested*.78):
        return text,size,_measure_width(text,size,font),1
    candidates=[(" ".join(tokens[:i])," ".join(tokens[i:]))
                for i in range(1,len(tokens))]
    left,right=min(candidates,key=lambda pair:max(
        _measure_width(pair[0],requested,font),
        _measure_width(pair[1],requested,font)))
    size2=min(fit_caption_size(left,requested,font),
              fit_caption_size(right,requested,font))
    if size2<=20 and size>20:
        return text,size,_measure_width(text,size,font),1
    return (left+r"\N"+right,size2,
            max(_measure_width(left,size2,font),
                _measure_width(right,size2,font)),2)


def phrase_groups(words: Sequence[Word]) -> list[list[Word]]:
    """Join spoken words into readable 2–5-word phrases, never into single pops.

    Whisper's word timestamps define phrase boundaries; short natural pauses
    stay inside a single phrase. A rare isolated word remains only if a pause
    or punctuation makes it unavoidable.
    """
    ordered=sorted(
        ((max(0.0,float(a)),float(b),safe_text(w)) for a,b,w in words
         if b>a and safe_text(w)),
        key=lambda row:(row[0],row[1]),
    )
    groups: list[list[Word]]=[]
    current: list[Word]=[]
    for a,b,word in ordered:
        if current:
            last=current[-1]
            total_chars=sum(len(w[2])+1 for w in current)+len(word)
            boundary=(
                len(current)>=5
                or (a-last[1])>0.42
                or (b-current[0][0])>2.55
                or total_chars>42
                or bool(re.search(r"[.!?…]$",last[2]))
            )
            if boundary:
                groups.append(current)
                current=[]
        current.append((a,b,word))
    if current:groups.append(current)
    # Avoid a one-word flash at the end of a sentence where the timings allow
    # that word to join its preceding phrase without excessive width.
    if len(groups)>1 and len(groups[-1])==1:
        previous=groups[-2]
        tail=groups[-1][0]
        gap=tail[0]-previous[-1][1]
        if gap<=0.44 and not re.search(r"[.!?…]$",previous[-1][2]):
            if len(previous)>=4:
                # 5+1 words feels like an abrupt single flash. Redistribute
                # to 4+2 instead, preserving the spoken word order.
                groups[-1].insert(0,previous.pop())
            elif sum(len(x[2])+1 for x in previous)+len(tail[2])<=44:
                previous.append(tail)
                groups.pop()
    return groups


def _line_length(
    group: Sequence[Word], indexes: Sequence[int], main_index: int,
    base: int, accent: int, little: FontSpec, big: FontSpec,
) -> float:
    total=0.0
    for j,i in enumerate(indexes):
        text=group[i][2].upper() if i==main_index else group[i][2]
        total+=_measure_width(text,accent if i==main_index else base,
                              big if i==main_index else little)
        if j:total+=base*0.37
    return total


def _phrase_layout(
    group: Sequence[Word], little: FontSpec, big: FontSpec,
) -> tuple[list[list[int]],int,int,float,int]:
    """Pick one balanced two-line composition and fit both fonts together."""
    emphasis=pick_main_word(group)
    indexes=list(range(len(group)))
    options=[ [indexes] ]
    if len(group)>=2:
        options.extend([
            [indexes[:cut],indexes[cut:]]
            for cut in range(1,len(group))
        ])
    for base in range(30,21,-1):
        accent=min(42,round(base*1.37))
        matches=[]
        for lines in options:
            widths=[_line_length(group,line,emphasis,base,accent,little,big)
                    for line in lines]
            widest=max(widths)
            # Prefer 2-line phrases (small context + highlighted main word)
            # when at least three words. Single-line phrases are fine if short.
            balance=abs(widths[0]-widths[1]) if len(lines)==2 else 0
            penalty=(0 if len(lines)==2 and len(group)>=3 else
                     26 if len(lines)==1 and len(group)>=3 else 8)
            if widest<=452:
                matches.append((widest*0.32+balance*0.14+penalty,
                                lines,widest))
        if matches:
            score,chosen,width=min(matches,key=lambda item:item[0])
            return chosen,base,accent,width,emphasis
    # Fallback retains EVERY spoken word. A long single word may shrink,
    # but the transcript is never silently truncated.
    for base in range(20,14,-1):
        accent=max(18,int(base*1.22))
        choices=[]
        for lines in options:
            widest=max(_line_length(group,line,emphasis,base,accent,little,big)
                       for line in lines)
            if widest<=452:
                choices.append((widest,lines))
        if choices:
            widest,lines=min(choices,key=lambda x:x[0])
            return lines,base,accent,widest,emphasis
    lines=options[-1]
    widest=max(_line_length(group,line,emphasis,15,18,little,big)
               for line in lines)
    return lines,15,18,widest,emphasis


def phrase_geometry(
    words: Sequence[Word], caption_position: str,
    small_font_profile: str="modern", font_profile: str="bold",
) -> list[tuple[float,float,float,int,int]]:
    """(start,end,visual_width,center_x,center_y) shared with emoji compositor."""
    little=choose_font(small_font_profile)
    big=choose_font(font_profile)
    y={"top":410,"middle":692,"bottom":868}[caption_position]
    result=[]
    phrases=phrase_groups(words)
    for i,group in enumerate(phrases):
        lines,base,accent,width,main=_phrase_layout(group,little,big)
        next_start=(phrases[i+1][0][0] if i+1<len(phrases) else None)
        a=group[0][0]
        b=max(group[-1][1]+0.15,a+0.66)
        if next_start is not None:b=min(b,max(a+0.25,next_start-0.015))
        result.append((a,b,min(455,width),CENTER_X,y))
    return result


def build_reference_dynamic_ass(
    words: Sequence[Word],
    *,
    color: str="auto",
    caption_position: str="middle",
    font_profile: str="bold",
    small_font_profile: str="modern",
    caption_variant: str="editorial",
    background_style: str="occasional",
    animation_style: str="float",
) -> tuple[str,int]:
    """Gentle phrase-level Reels typography: one phrase, one animated layer.

    Instead of popping every word separately, all words appear in one
    synchronized event, with only the meaningful word larger and tinted.
    A plate, if selected, is part of THAT SAME dialogue style, so it can
    never float independently from the words.
    """
    if caption_position not in ("top","middle","bottom"):
        raise ValueError("Неверное положение субтитров.")
    if caption_variant not in COLOR_PALETTES:
        raise ValueError("Неизвестный вариант цвета титров.")
    if background_style not in ("off","occasional","frequent","always"):
        raise ValueError("Недопустимая подложка субтитров.")
    if animation_style not in ("float","pop","slide"):
        raise ValueError("Недопустимый тип анимации.")

    little=choose_font(small_font_profile)
    big=choose_font(font_profile)
    accent_hex,base_hex=COLOR_PALETTES[caption_variant]
    accent_color=ass_color(accent_hex if color=="auto" else color)
    small_color=ass_color(base_hex)
    y={"top":410,"middle":692,"bottom":868}[caption_position]
    # A small soft shadow on ALL text. No gigantic blurry black bars.
    header=(
        "[Script Info]\nScriptType: v4.00+\n"
        "PlayResX: 720\nPlayResY: 1280\nWrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Phrase,{little.name},30,{small_color},{small_color},"
        "&H98201418,&HD31A1520,"
        f"{little.bold},{little.italic},0,0,"
        f"{little.scale_x},{little.scale_y},0,0,1,0.65,0.75,5,72,72,20,1\n"
        f"Style: PhrasePlate,{little.name},30,{small_color},{small_color},"
        "&H98201418,&HBA1A1520,"
        f"{little.bold},{little.italic},0,0,"
        f"{little.scale_x},{little.scale_y},0,0,3,1.4,0.45,5,72,72,20,1\n"
        "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    phrases=phrase_groups(words)
    events=[]
    for index,group in enumerate(phrases):
        if not group:continue
        lines,base_size,big_size,width,main=_phrase_layout(group,little,big)
        start=group[0][0]
        natural_end=group[-1][1]+0.16
        next_start=(phrases[index+1][0][0] if index+1<len(phrases)
                    else None)
        end=max(natural_end,start+0.66)
        if next_start is not None:
            end=min(end,max(start+0.24,next_start-0.015))
        if end-start<0.12:continue
        duration_ms=max(120,int((end-start)*1000))
        # 250–340ms entrance, independent of word count; no harsh scale jump.
        fade_in=min(340,max(145,int(duration_ms*.24)))
        fade_out=min(235,max(90,int(duration_ms*.18)))
        if fade_in+fade_out>duration_ms*.8:
            fade_in=int(duration_ms*.35)
            fade_out=int(duration_ms*.20)
        rise=min(520,max(260,int(duration_ms*.45)))
        delta=8
        if animation_style=="float":
            move=rf"\move(360,{y+delta},360,{y},0,{rise})"
        elif animation_style=="slide":
            move=rf"\move({360+delta},{y},360,{y},0,{rise})"
        else:
            # Tiny settle instead of the old abrupt 91% -> 100% pop.
            move=rf"\move(360,{y+4},360,{y},0,{rise})"

        plate=(
            background_style=="always"
            or background_style=="frequent" and index%3==0
            or background_style=="occasional" and index%6==2
        )
        style="PhrasePlate" if plate else "Phrase"
        parts=[]
        for number,line in enumerate(lines):
            if number:parts.append(r"\N")
            for j,k in enumerate(line):
                if j:parts.append(" ")
                clean=safe_text(group[k][2])
                if k==main:
                    parts.append(
                        "{"+rf"\fn{big.name}\b{big.bold}\i{big.italic}"
                        +rf"\fs{big_size}\fscx{big.scale_x}\fscy{big.scale_y}"
                        +rf"\c{accent_color}"+"}"
                        +clean.upper()
                        +"{"+rf"\fn{little.name}\b{little.bold}\i{little.italic}"
                        +rf"\fs{base_size}\fscx{little.scale_x}\fscy{little.scale_y}"
                        +rf"\c{small_color}"+"}"
                    )
                else:parts.append(clean)
        prefix=(
            "{"+r"\an5"+move+rf"\fad({fade_in},{fade_out})"
            +rf"\fs{base_size}"
            +rf"\fscx{little.scale_x}\fscy{little.scale_y}"
            +r"\blur0.20\clip(72,175,648,1105)"+"}"
        )
        events.append(
            f"Dialogue: 2,{ass_time(start)},{ass_time(end)},"
            f"{style},,0,0,0,,{prefix}{''.join(parts)}\n"
        )
    return header+"".join(events),len(events)
