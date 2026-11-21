"""Speech-led editorial montage plan, with restrained asset selection.

A cue is a visual statement tied to the actual transcript, not a random
animation. Silence or ordinary discussion may correctly produce NO inserts.
This module does not call external LLMs or infer unseen visual content.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Sequence


@dataclass(frozen=True)
class SemanticCue:
    start: float
    end: float
    kind: str
    label: str
    reason: str
    emphasis: float = 1.0


# Longer / rarer patterns outrank superficial words; avoid generic "маникюр"
# or "видео" triggers that would paste the same sticker onto every clip.
PATTERNS: tuple[tuple[str, tuple[str,...], float, str], ...] = (
    ("error", ("ошиб", "неправиль", "брак", "косяк", "кошмар",
               "испорчен", "плохое", "плохо"), 3.1, "ошибка или проблема"),
    ("inspect", ("рассмотр", "присмотр", "приближ", "детал",
                 "найди", "обрати вниман", "посмотри"), 2.6, "показать детали"),
    ("success", ("исправ", "результат", "получилось", "готово",
                 "правильн", "идеальн"), 2.9, "решение или результат"),
    ("compare", ("сравн", "отличие", "разниц", "до и после",
                 "до после", "вариант"), 2.7, "сравнение"),
    ("time", ("секунд", "минут", "часов", "времени", "время",
              "долго", "быстро"), 2.4, "время или скорость"),
    ("speech", ("объясн", "почему", "вопрос", "ответ",
                "комментар", "напиши", "расскажу"), 2.4, "объяснение или вопрос"),
    ("camera", ("съёмк", "съемк", "снима", "монтаж",
                "кадр", "оператор", "камер"), 2.8, "съёмка или монтаж"),
    ("phone", ("смартфон", "телефон", "приложени"), 3.0, "телефон или приложение"),
    ("next", ("следующ", "перейди", "листай", "свайп",
              "шаг", "покажу"), 2.5, "следующее действие"),
)
# Weak words need multiple independent clues in their short utterance.
CONTEXT: dict[str, tuple[str,...]] = {
    "error": ("маникюр", "ногт", "покрыт", "работ", "цвет",
              "френч", "видно", "как", "здесь", "тут", "посмотри"),
    "inspect": ("ошиб", "детал", "ногт", "проблем", "здесь", "эт",
                "место", "линия", "видно", "посмотри"),
    "success": ("вот", "теперь", "покаж", "итог", "после",
                "получ", "работ", "исправ", "сравн"),
    "compare": ("отлич", "разниц", "эти", "два", "вариант",
                "до", "после", "цвет", "форм", "вместо"),
    "time": ("сдел", "найди", "выполн", "прошл", "длится",
             "скорост", "работ", "готов"),
    "speech": ("расскаж", "отвеч", "вопрос", "почему", "объяс",
               "клиент", "ошиб", "причин"),
    "camera": ("снима", "запис", "монтаж", "кадр", "ролик",
               "покаж", "съём", "видео"),
    "phone": ("откр", "покаж", "приложен", "экран",
              "телефон", "бот", "делай"),
    "next": ("посмотр", "фото", "кадр", "видео", "покаж",
             "листа", "шаг", "экран"),
}
ICON_NAME = {
    "error": "X.mov",
    "inspect": "Magnifying Glass.mov",
    "success": "Checkmark.mov",
    "compare": "Arrow Left and Right.mov",
    "time": "Clock.mov",
    "speech": "Speech Bubble.mov",
    "camera": "Camera Icon.mov",
    "phone": "Smart Phone.mov",
    "next": "Arrow Right.mov",
}
# Full-frame editorial scenes, which briefly replace a talking head, should be
# rarer than little transparent icons.
FULL_STAGE_KINDS = {"compare", "camera"}
WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.I)


def _clean(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower().replace("ё", "е")))


def choose_semantic_cues(
    words: Sequence[tuple[float,float,str]],
    duration: float,
    density: str = "balanced",
) -> list[SemanticCue]:
    if density not in {"subtle","balanced","dynamic"}:
        raise ValueError("Unknown semantic edit density.")
    if duration < 4.0 or not words:
        return []
    valid=sorted(((float(a),float(b),_clean(str(w)))
                  for a,b,w in words if b>a and _clean(str(w))),
                 key=lambda x:x[0])
    if not valid:return []
    min_gap={"subtle":12.5,"balanced":9.0,"dynamic":6.8}[density]
    max_cues={"subtle":4,"balanced":6,"dynamic":8}[density]
    # Each cue must be supported by the actually spoken short phrase.
    candidates=[]
    for i,(start,end,token) in enumerate(valid):
        if start<2.25 or start>duration-1.45:
            continue
        near=[w for a,b,w in valid if start-1.3<=a<=start+1.65]
        context=" ".join(near)
        if not context:continue
        for kind,stems,score,reason in PATTERNS:
            if not any(_clean(stem) in token for stem in stems):
                continue
            # "not a mistake" explicitly prevents a warning animation.
            if kind=="error" and any(p in context for p in (
                    "не ошибка", "нет ошибки", "не является ошибк",
                    "без ошибок", "никакой ошибки")):
                continue
            if kind=="success" and "не получилось" in context:
                continue
            matching=sum(1 for stem in CONTEXT[kind] if stem in context)
            # Strong explicit concepts are enough; ambiguous weak signals
            # require support from a second nearby term.
            strong=(kind in {"error","success","compare","phone","time"} and (
                any(stem in token for stem in ("ошиб","брак","исправ",
                    "результат","сравн","отличи","приложен","телефон",
                    "секунд","минут")))
            if not strong and matching<2:
                continue
            label=token.upper()[:20]
            weight=score+min(1.5,matching*.24)
            if kind=="inspect" and any(text in context for text in (
                "найди ошиб", "найти ошиб", "посмотри на ошиб",
                "обрати внимание")):
                weight+=1.2
            candidates.append((weight,start,kind,label,reason))
    # Highest-confidence cue in a cluster, then enforce significant empty
    # space to preserve the person's face and the original speech rhythm.
    ranked=sorted(candidates,key=lambda c:(-c[0],c[1]))
    selected=[]
    for weight,start,kind,label,reason in ranked:
        if any(abs(start-prev[0])<min_gap for prev in selected):
            continue
        length=2.0 if kind in FULL_STAGE_KINDS else 1.15
        end=min(duration-.05,start+length)
        if end-start<.65:continue
        selected.append((start,end,kind,label,reason,weight))
        if len(selected)>=max_cues:break
    selected.sort(key=lambda s:s[0])
    return [SemanticCue(start,end,kind,label,reason,round(weight,2))
            for start,end,kind,label,reason,weight in selected]


def plan_for_editorial_scenes(
    words: Sequence[tuple[float,float,str]], duration: float,
    density: str = "balanced",
) -> list[SemanticCue]:
    """Only substantial story transitions, never every phrase or filler word."""
    return [c for c in choose_semantic_cues(words,duration,density)
            if c.kind in FULL_STAGE_KINDS]
