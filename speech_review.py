"""Сопоставление исправленной пользователем расшифровки и времени речи.

Без автоматического выдумывания текста. Когда исправлений много, тайминг
является приблизительным: Whisper не выполняет forced alignment.
"""
from __future__ import annotations

import difflib
import re
from typing import Sequence

Word = tuple[float, float, str]


def plain_transcript(words: Sequence[Word]) -> str:
    return " ".join(text.strip() for _, _, text in words if text.strip()).strip()


def _normal(word: str) -> str:
    return re.sub(r"[^\wа-яё-]+", "", word, flags=re.IGNORECASE).lower()



# Adjacent, text-confirmed retakes only: do not remove a repeated topic
# elsewhere in the video, or emphatic "очень очень", "да да", etc.
_REPEAT_EMPHASIS = frozenset("да нет не очень точно прямо совсем совсем-совсем много мало сильно супер быстро медленно чуть еще вот ну так то и а в на с по из за у к это все как что чтобы".split())
_REPEAT_FILLERS = frozenset(("э","ээ","эээ","эм","мм","м","а","ну"))


# Discourse words and common hesitations are not evidence of a shared take.
_RETAKE_STOP = frozenset("я мне меня мы вы вам ты тебе кажется как будто буквально просто вот ну это и а но для в на с из у к о об по за от что чтобы потому который которая которые так же там здесь очень вообще реально действительно прям прямо".split())
_RETAKE_CUES = frozenset(("нет","заново","стоп","погодите","подожди","сначала"))
_HESITATION = re.compile(r"^(?:э{1,5}|эм+|м{2,6}|хм+|ээм+)$")

def _retake_key(word: str) -> str:
    k=_normal(word).replace("ё","е")
    # Light stemming of inflected nouns/verbs; leave short words alone.
    if len(k)>=6:
        k=re.sub(r"(?:ами|ями|ого|ему|ому|ыми|ими|ов|ев|ей|ам|ям|ах|ях|ом|ем|а|я|ы|и|у|ю|е|о)$","",k)
    return k

def _restart_content(keys, start, end):
    return [_retake_key(k) for k in keys[start:end]
            if k and k not in _RETAKE_STOP and k not in _RETAKE_CUES
            and not _HESITATION.fullmatch(k)]

def _strong_restart(a,b):
    if len(a)<3 or len(b)<3:
        return False
    # A shared opening, not merely a topic mentioned later in the sentence.
    for width in range(min(7,len(a),len(b)),2,-1):
        x,y=a[:width],b[:width]
        m=difflib.SequenceMatcher(a=x,b=y,autojunk=False)
        common=sum(k.size for k in m.get_matching_blocks())
        if common>=3 and m.ratio()>=.72 and (x[0]==y[0] or x[:2]==y[:2]):
            return True
    return False

def _find_restarted_takes(original,keys):
    n=len(keys)
    if n<6:return []
    starts=[0]
    for i in range(1,n):
        prev=original[i-1]
        if (re.search(r"[.!?…]$",prev[2].strip()) or keys[i-1] in _RETAKE_CUES
                or original[i][0]-prev[1]>=.65):
            starts.append(i)
    pairs=[]
    for pos,i in enumerate(starts):
        for j in starts[pos+1:]:
            if j-i>100 or original[j][0]-original[i][0]>55:break
            # Long intervening explanations are only dropped if there is an
            # explicit rejection/restart cue immediately before the later take.
            cue=keys[j-1] in _RETAKE_CUES
            if not cue and (j-i>25 or sum(bool(re.search(r"[.!?…]$",w[2].strip())) for w in original[i:j])>1):
                continue
            if j-i<3 or original[j][0]<original[j-1][1]:continue
            a=_restart_content(keys,i,min(j,i+16))
            b=_restart_content(keys,j,min(n,j+16))
            if _strong_restart(a,b):
                pairs.append((i,j))
                break
    # Merge chained retries. The last take is always retained.
    return pairs

def _speech_cut(original,i,j):
    if not 0<=i<j<=len(original):return None
    a,b=original[i][0],original[j-1][1]
    if a<0 or b<=a or any(w[1]<=w[0] for w in original[i:j]):return None
    if i and original[i-1][1]>a:return None
    if j<len(original) and original[j][0]<b:return None
    left=max(0.,a-.045,original[i-1][1] if i else 0.)
    right=min(b+.045,original[j][0] if j<len(original) else b+.045)
    return (left,right)


def plan_speech_repeats(words: Sequence[Word]) -> tuple[list[Word], list[tuple[float,float]]]:
    """Keep latest exact or high-confidence rephrased retake; return source cuts.

    Match normalized opening content and explicit restart cues. A short hesitation
    between attempts is allowed; unrelated intervening words are protected.
    Never cut across overlapping word timestamps.
    """
    original=list(words)
    keys=[_normal(w[2]).replace("ё","е") for w in original]
    n=len(original)
    removed=set()
    cuts=[]
    # First catch rephrased restarts, including a rejected full earlier take.
    for a,b in _find_restarted_takes(original,keys):
        cut=_speech_cut(original,a,b)
        if cut:
            cuts.append(cut)
            removed.update(range(a,b))
    i=0
    while i<n-1:
        if i in removed:
            i+=1
            continue
        match=None
        for length in range(min(40,(n-i)//2),0,-1):
            if not all(keys[i:i+length]):
                continue
            if length==1 and (len(keys[i])<3 or keys[i] in _REPEAT_EMPHASIS):
                continue
            end=i+length
            for j in range(end,min(end+(3 if length>1 else 1),n-length+1)):
                if any(k not in _REPEAT_FILLERS for k in keys[end:j]):
                    break
                if any(k in removed for k in range(i,j+length)):
                    continue
                if keys[i:end]!=keys[j:j+length]:
                    continue
                gap=original[j][0]-original[end-1][1]
                # For a single word require a short hesitation, not normal
                # emphatic rapid repetition. Longer exact repeats can be immediate.
                if gap < (0.18 if length==1 else 0.0) or gap>3.0:
                    continue
                if any(original[k][1]<=original[k][0] for k in range(i,j+length)):
                    continue
                if any(original[k+1][0]-original[k][1]>3.0 for k in range(i,j+length-1)):
                    continue
                if original[i][0]<0 or (i and original[i-1][1]>original[i][0]) or original[j-1][1]>original[j][0]:
                    continue
                match=j
                break
            if match is not None:
                break
        if match is None:
            i+=1
            continue
        j=match
        left=max(0.0,original[i][0]-.06,original[i-1][1] if i else 0.0)
        right=min(original[j][0],original[j-1][1]+.06)
        if right>left and right>=original[j-1][1]:
            cuts.append((left,right))
            removed.update(range(i,j))
        i=j  # chained retakes leave the last occurrence
    # Remove nonlexical hesitation sounds. Keep meaningful Russian words
    # such as "ну", "нет", "просто" unless they are part of a rejected take.
    for k,key in enumerate(keys):
        if k not in removed and _HESITATION.fullmatch(key):
            cut=_speech_cut(original,k,k+1)
            if cut:
                cuts.append(cut);removed.add(k)
    # A standalone burst of 3+ "нет" before a new sentence is a rejected take
    # marker, not a negation inside a sentence.
    k=0
    while k<n:
        if keys[k]!="нет":k+=1;continue
        end=k+1
        while end<n and keys[end]=="нет":end+=1
        if (end-k>=3 and end<n and re.search(r"[.!?…]$",original[end-1][2].strip())
                and (k==0 or re.search(r"[.!?…]$",original[k-1][2].strip()))):
            cut=_speech_cut(original,k,end)
            if cut:
                cuts.append(cut);removed.update(range(k,end))
        k=end
    retained=[w for k,w in enumerate(original) if k not in removed]
    if not retained or len(cuts)>80:
        return original,[]
    return retained,sorted(cuts)


def align_corrected_words(
    original: Sequence[Word], corrected: str, duration: float,
) -> list[Word]:
    """Возвращает ТОЛЬКО слова пользователя, оставляя доступные таймкоды.

    Совпавшие слова используют точные времена из Whisper. Остальные
    слова получают приблизительные времена внутри исправленного блока.
    """
    new_words = corrected.split()
    if not new_words:
        raise ValueError("Исправленный текст пустой.")
    if len(new_words) > 1000 or len(corrected) > 6000:
        raise ValueError("Исправленный текст слишком длинный (максимум 6000 символов).")

    if not original:
        end = max(0.2, float(duration))
        step = end / len(new_words)
        return [(i * step, max(i * step + 0.05, (i + 1) * step), w)
                for i, w in enumerate(new_words)]

    a = [_normal(x[2]) for x in original]
    b = [_normal(x) for x in new_words]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    output: list[Word] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "delete":
            continue
        if tag == "equal":
            output.extend((float(original[i1+k][0]), float(original[i1+k][1]), new_words[j1+k])
                          for k in range(j2-j1))
            continue
        count = j2 - j1
        if not count:
            continue
        left = float(original[i1][0]) if i1 < len(original) else float(original[-1][1])
        if i2 > i1:
            right = float(original[i2 - 1][1])
        elif i1 < len(original):
            right = float(original[i1][1])
        else:
            right = min(float(duration), left + max(0.16, 0.18 * count))
        if right <= left:
            right = left + max(0.15, 0.14 * count)
        step = (right-left) / count
        for j in range(count):
            start = max(0.0, left+j*step)
            output.append((start, max(start+0.04, left+(j+1)*step), new_words[j1+j]))
    return output


def apply_word_fixes(
    original: Sequence[Word],
    replacements: str,
) -> list[Word]:
    """Команда /fix ошибка=правильно; ошибка2=правильно2.

    Удобно для пары ошибок без переписывания всей речи.
    Времена слов сохраняются; совпадающие ошибочные слова заменяются все.
    """
    rules: dict[str, str] = {}
    for part in replacements.split(";"):
        if not part.strip():
            continue
        if "=" not in part:
            raise ValueError("Формат: /fix неверно=верно; другое=правильно")
        wrong, right = (x.strip() for x in part.split("=",1))
        if not _normal(wrong) or not right or len(right) > 80:
            raise ValueError("Укажи слово до и после знака =")
        rules[_normal(wrong)] = right
    if not rules or len(rules) > 20:
        raise ValueError("Можно исправить от 1 до 20 слов за сообщение.")
    fixed: list[Word] = []
    replaced = 0
    for a,b,word in original:
        key = _normal(word)
        if key in rules:
            fixed.append((a,b,rules[key]))
            replaced+=1
        else:
            fixed.append((a,b,word))
    if not replaced:
        raise ValueError("Не нашла указанных ошибочных слов в расшифровке.")
    return fixed


def map_words_to_ranges(
    original: Sequence[Word], kept: Sequence, speed: float = 1.0,
) -> list[Word]:
    """Преобразует таймкоды исходника в склеенное и ускоренное видео."""
    mapped: list[Word] = []
    timeline = 0.0
    for segment in kept:
        a, b = float(segment.start), float(segment.end)
        for start, end, word in original:
            left = max(float(start), a)
            right = min(float(end), b)
            if right <= left + 0.025:
                continue
            t0 = (timeline + left-a) / speed
            t1 = (timeline + right-a) / speed
            mapped.append((max(0.0,t0), max(t0+0.03,t1), word))
        timeline += b-a
    mapped.sort(key=lambda item: (item[0], item[1]))
    return mapped


def shift_word_timestamps(
    words: Sequence[Word],
    delay_seconds: float = 0.30,
    total_duration: float | None = None,
) -> list[Word]:
    """Смещает ТОЛЬКО титры, а не голос/видео. Плюс = позже.

    Применяется после монтажа на финальной временной шкале.
    Не растягивает речь и не меняет скорость воспроизведения.
    """
    delay = float(delay_seconds)
    if not -0.5 <= delay <= 1.5:
        raise ValueError("Смещение субтитров: от -0.5 до +1.5 сек.")
    result: list[Word] = []
    for start, end, word in words:
        a = max(0.0, float(start) + delay)
        b = float(end) + delay
        if total_duration is not None:
            if a >= float(total_duration) - 0.015:
                continue
            b = min(b, float(total_duration))
        if b > a + 0.025 and word.strip():
            result.append((a, b, word))
    return result
