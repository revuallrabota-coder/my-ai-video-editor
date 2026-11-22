"""Speech-matched transparent PNG props from PRIVATE uploaded ZIP archives.

No source image is committed or uploaded to GitHub. Only PNGs whose names
start with sticker_<concept>_... are considered. Other photographs,
transition mattes, decor/backgrounds and unrelated assets are never
randomly dropped on top of the person.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

WORD_STEMS = {
    "gift": ("подар", "дарю", "дарил", "поздрав", "gift", "present"),
    "snow": ("снеж", "снег", "snow", "snowflake"),
    "winter": ("зим", "winter", "мороз"),
    "mug": ("чашк", "кружк", "какао", "горячий шоколад", "cocoa", "mug"),
    "deer": ("олен", "deer"),
    "envelope": ("письм", "конверт", "открытк", "letter", "mail", "envelope"),
    "tea": ("чай", "чаю", "чаем", "улун", "tea", "oolong"),
    "cinnamon": ("кориц", "пряност", "специ", "cinnamon"),
    "stars": ("звезд", "звёзд", "сиян", "звездоч", "stars"),
    "cookie": ("печен", "печён", "cookie", "cookies"),
    "cake": ("кекс", "маффин", "пирог", "выпечк", "cake", "muffin"),
    "breakfast": ("завтрак", "тост", "хлеб", "breakfast", "toast"),
    "book": ("книг", "чита", "чтени", "book"),
    "shoes": ("туфл", "обув", "каблук", "shoes"),
    "crystal": ("хрусталь", "магич", "будущее", "предсказ", "crystal"),
    "date_jan": ("январ", "january"),
    "date_feb": ("феврал", "february"),
    "date_dec": ("декабр", "december"),
    "year_2027": ("2027", "две тысячи двадцать седьм"),
    "phone": ("телефон", "смартфон", "мобильн", "phone"),
    "social": ("подпис", "лайк", "сохран", "коммент", "репост",
               "like", "comment", "share", "subscribe"),
    "record": ("пластинк", "винил", "музык", "vinyl", "record"),
    "heart": ("сердц", "любов", "романтик", "heart"),
    "folder": ("папк", "документ", "архив", "folder"),
    "scroll": ("приглашен", "сертификат", "грамот", "certificate"),
}
# Precise filename stems mean creators can provide more than one image
# for a concept without accidental detection from inside a random filename.

@dataclass(frozen=True)
class ObjectCue:
    start: float
    end: float
    concept: str
    path: Path


def inventory(photos: Sequence[Path]) -> dict[str,list[Path]]:
    out:dict[str,list[Path]]={}
    for path in photos:
        # The ZIP extractor names all photos "photo_" + basename.
        name=path.name.lower()
        for concept in WORD_STEMS:
            if (name.startswith(f"photo_sticker_{concept}_") or
                name==f"photo_sticker_{concept}.png"):
                out.setdefault(concept,[]).append(path)
                break
    for items in out.values():
        items.sort(key=lambda p:p.name)
    return out


def choose_object_cues(
    words: Sequence[tuple[float,float,str]],
    duration: float,
    photos: Sequence[Path],
    density: str = "balanced",
) -> list[ObjectCue]:
    if density not in ("subtle","balanced","dynamic"):
        raise ValueError("Неправильная частота предметных вставок.")
    available=inventory(photos)
    if not available or duration<2.0 or not words:
        return []
    # Stop sound effects and large props from turning the whole talking head
    # into an incomprehensible parade of stickers.
    gap={"subtle":5.8,"balanced":4.2,"dynamic":3.1}[density]
    limit={"subtle":4,"balanced":7,"dynamic":10}[density]
    candidates=[]
    for start,end,token in sorted(words,key=lambda row:row[0]):
        text=str(token).casefold().replace("ё","е")
        start=float(start)
        if not 0.45<=start<=duration-1.0:
            continue
        for concept,stems in WORD_STEMS.items():
            if concept not in available:
                continue
            matched=any(stem.replace("ё","е") in text for stem in stems)
            if not matched:
                continue
            # Negated mentions should not trigger a cheerful visual.
            context=" ".join(str(w).casefold().replace("ё","е")
                             for a,b,w in words
                             if start-.8<=float(a)<=start+1.0)
            if concept=="gift" and any(x in context for x in (
                "не подарок","без подарка","не дарю")):
                continue
            candidates.append((start,concept))
    selected=[]
    last=-gap
    count={}
    for start,concept in sorted(candidates):
        if start-last<gap:
            continue
        photos_for_concept=available[concept]
        idx=count.get(concept,0)%len(photos_for_concept)
        end=min(duration-.08,start+1.4)
        if end-start<0.75:
            continue
        selected.append(ObjectCue(start,end,concept,photos_for_concept[idx]))
        count[concept]=count.get(concept,0)+1
        last=start
        if len(selected)>=limit:
            break
    return selected
