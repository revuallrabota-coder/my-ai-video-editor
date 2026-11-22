"""Manually chosen top-of-video title independent of spoken subtitles and hook.

Uses a compact editorial label in the safe upper band, not the old
auto-generated three-line hero when a manual title mode is selected.
"""
from __future__ import annotations
import re
from signature_captions import safe_text,ass_time,ass_color

TITLE_MODES = frozenset(("auto","off","intro","always"))
MAX_TITLE_CHARS = 70


def clean_top_title(text: str) -> str:
    return safe_text(str(text or ""))[:MAX_TITLE_CHARS].strip()


def title_lines(text: str) -> tuple[str,int]:
    """Keep one or two balanced lines within ~540 ASS pixels."""
    clean=clean_top_title(text)
    if not clean:
        return "",32
    terms=clean.split(" ")
    if len(clean)<=31 or len(terms)==1:
        lines=[clean]
    else:
        candidates=[(" ".join(terms[:i])," ".join(terms[i:]))
                    for i in range(1,len(terms))]
        left,right=min(candidates,key=lambda p:(max(len(p[0]),len(p[1])),
                                                  abs(len(p[0])-len(p[1]))))
        lines=[left,right]
    longest=max(len(s) for s in lines)
    # Cyrillic uppercase averages ~19px at fs32; chosen font can vary.
    size=max(23,min(34,round(560/max(longest*.62,14))))
    return r"\N".join(s.upper() for s in lines),size


def append_top_title(
    ass_text: str, title: str, mode: str,
    duration: float, *, color: str="auto",
    studio_scene: bool=False,
) -> str:
    """Append timed ASS title; no text or 'off' means no added graphics."""
    if mode not in TITLE_MODES:
        raise ValueError("Допустимые режимы названия: auto, off, intro, always.")
    clean=clean_top_title(title)
    if not clean or mode in ("off","auto") or duration<=0.25:
        return ass_text
    if "\n[Events]\n" not in ass_text:
        raise ValueError("В файле субтитров отсутствует раздел Events.")
    rendered,fontsize=title_lines(clean)
    # Safe top band: under the typical interface overlay, above subtitles.
    start=0.10
    end=min(duration,3.8) if mode=="intro" else duration
    if end-start<.2:
        return ass_text
    fadein=min(280,round((end-start)*1000*.24))
    fadeout=min(240,round((end-start)*1000*.2))
    ink=ass_color(color) if studio_scene and re.fullmatch(r"#[0-9a-fA-F]{6}",color) else "&H00FFFFFF&"
    style=(
        f"Style: CustomTopTitle,DejaVu Sans,32,{ink},{ink},"
        "&H78231924,&HD0000000,1,0,0,0,100,100,0,0,1,1.15,1.2,5,64,64,30,1\n"
    )
    # Sharp-corner ASS opaque boxes are never used on manually chosen titles.
    # The title appears at 144 on the 720x1280 ASS canvas and stays put.
    event=(
        f"Dialogue: 8,{ass_time(start)},{ass_time(end)},"
        "CustomTopTitle,,0,0,0,,"
        "{"+rf"\an5\pos(360,141)\fs{fontsize}\fad({fadein},{fadeout})"
        +r"\blur0.6\clip(66,76,654,204)"+"}"
        +rendered+"\n"
    )
    return ass_text.replace("\n[Events]\n","\n"+style+"\n[Events]\n",1)+event
