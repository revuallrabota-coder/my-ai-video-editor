"""Download an explicitly shared Yandex Disk video, never arbitrary URLs."""
import re
import time
from pathlib import Path
from urllib.parse import urlsplit, urljoin

import requests
from bot_api_editor import call_api, send_text

API="https://cloud-api.yandex.net/v1/disk/public/resources"
MAX_BYTES=1_000_000_000
MAX_TOTAL_BYTES=3_000_000_000
MAX_FILES=12
SUFFIXES={".mp4",".mov",".m4v",".webm",".mkv"}

def public_link(text):
    value=str(text).strip()
    if re.fullmatch(r"https://(?:disk\.(?:360\.)?yandex\.(?:ru|com)|yadi\.sk)/[di]/[A-Za-z0-9_-]{4,160}/?",value):
        return value
    return None

def public_links(text):
    """Extract supported links in message order, including a pasted list."""
    result=[]
    for candidate in re.findall(r"https://[^\s<>]+",str(text)):
        link=public_link(candidate.rstrip(".,;!)]}"))
        if link:
            result.append(link)
    return list(dict.fromkeys(result))

def download_host(url):
    try:
        p=urlsplit(url)
        host=p.hostname or ""
        return (p.scheme=="https" and not p.username and not p.password
                and p.port in (None,443) and
                (host in ("downloader.disk.yandex.ru","downloader.disk.yandex.net",
                          "downloader.dst.yandex.ru","downloader.dst.yandex.net")
                 or bool(re.fullmatch(r"(?:[a-z0-9-]+\.)+(?:disk|dst)\.yandex\.(?:net|ru|com)",host))
                 or bool(re.fullmatch(r"(?:[a-z0-9-]+\.)+storage\.yandex\.net",host))))
    except ValueError:
        return False

def fetch_public_video(link,folder,session=None,*,index=1,remaining=MAX_TOTAL_BYTES):
    if not public_link(link):
        raise ValueError("Нужна ссылка на отдельный файл Яндекс Диска.")
    session=session or requests.Session()
    params={"public_key":link}
    try:
        with session.get(API,params=params,timeout=(10,30),allow_redirects=False) as r:
            if r.status_code!=200:
                raise ValueError("Яндекс не открыл ссылку. Проверь общий доступ и лимит скачивания.")
            meta=r.json()
        name=str(meta.get("name",""))
        size=meta.get("size")
        ext=Path(name).suffix.lower()
        if meta.get("type")!="file" or ext not in SUFFIXES:
            raise ValueError("Нужна ссылка на один видеофайл MP4, MOV, M4V, WEBM или MKV, не папку.")
        if not isinstance(size,int) or not 4096<=size<=MAX_BYTES:
            raise ValueError("Для пробной загрузки через Диск принимаю видео до 1 ГБ.")
        if size>remaining:
            raise ValueError("Общий размер исходников не должен превышать 3 ГБ.")
        with session.get(API+"/download",params=params,timeout=(10,30),allow_redirects=False) as r:
            if r.status_code!=200:
                raise ValueError("Яндекс не разрешил скачивание. Проверь доступ или дневной лимит.")
            href=r.json().get("href","")
        folder.mkdir(parents=True,exist_ok=True)
        target=folder/(f"clip_{index:03d}"+ext)
        deadline=time.monotonic()+900
        for _ in range(5):
            if not download_host(href):
                host=urlsplit(href).hostname or ""
                safe_host=host if re.fullmatch(r"[a-zA-Z0-9.-]{1,253}",host) else "неизвестный"
                raise ValueError("Яндекс вернул неподдерживаемый домен скачивания: "+safe_host+".")
            with session.get(href,stream=True,timeout=(15,60),allow_redirects=False,
                             headers={"Accept-Encoding":"identity"}) as r:
                if r.is_redirect:
                    href=urljoin(href,r.headers.get("Location",""))
                    continue
                if r.status_code!=200:
                    raise ValueError("Скачивание с Яндекс Диска недоступно.")
                count=0
                try:
                    with target.open("wb") as out:
                        for chunk in r.iter_content(1024*1024):
                            if not chunk:
                                continue
                            count+=len(chunk)
                            if count>size or time.monotonic()>deadline:
                                raise ValueError("Превышен размер или время скачивания.")
                            out.write(chunk)
                    if count!=size:
                        raise ValueError("Яндекс вернул неполный исходник.")
                except BaseException:
                    target.unlink(missing_ok=True)
                    raise
                return target
        raise ValueError("Слишком много перенаправлений Яндекс Диска.")
    except requests.RequestException:
        raise ValueError("Сеть Яндекс Диска недоступна или скачивание прервалось.") from None

def receive_yandex_source(token,owner,folder,stage):
    from telegram_editor import duration_and_audio
    prompt=call_api(token,"sendMessage",{"chat_id":owner,"text":
        "✅ Настройки сохранены. Пришли ссылки на 1–12 видео с Яндекс Диска: "
        "можно все в одном сообщении или по одной. До 1 ГБ на файл, 3 ГБ "
        "и 10 минут суммарно. После всех ссылок напиши /montage, чтобы начать "
        "нарезку и монтаж в порядке отправки. /cancel — отмена. "
        "Отключай общий доступ только после подтверждения скачивания каждого файла. "
        "Жду ссылки 30 минут."})
    min_id=int(prompt["message_id"])
    deadline=time.monotonic()+1800
    offset=None
    clips=[]
    seen=set()
    total=0
    duration=0.0
    while time.monotonic()<deadline:
        args={"limit":30,"timeout":15,"allowed_updates":'["message"]'}
        if offset is not None:args["offset"]=offset
        for update in call_api(token,"getUpdates",args,timeout=35):
            offset=update["update_id"]+1
            msg=update.get("message",{})
            if (msg.get("from",{}).get("id")!=owner or msg.get("chat",{}).get("id")!=owner
                or msg.get("chat",{}).get("type")!="private" or msg.get("message_id",0)<=min_id):
                continue
            text=str(msg.get("text","")).strip()
            if text.lower()=="/cancel":
                raise ValueError("Загрузка через Яндекс Диск отменена.")
            if text.lower() in ("/montage","готово","начать монтаж"):
                if not clips:
                    send_text(token,owner,"Сначала пришли хотя бы одну ссылку на видео.")
                    continue
                send_text(token,owner,f"🎬 Начинаю монтаж {len(clips)} видео в порядке отправки.")
                return clips
            links=public_links(text)
            if not links:
                if text:
                    send_text(token,owner,"Пришли ссылки на видео с Яндекс Диска или /montage для запуска.")
                continue
            for link in links:
                if link in seen:
                    send_text(token,owner,"Это видео уже добавлено. Повторно не скачиваю.")
                    continue
                if len(clips)>=MAX_FILES or total>=MAX_TOTAL_BYTES:
                    send_text(token,owner,"Лимит проекта достигнут. Напиши /montage.")
                    break
                stage("downloading","Скачиваю исходное видео с Яндекс Диска.")
                send_text(token,owner,f"📥 Скачиваю видео №{len(clips)+1}.")
                target=None
                try:
                    started=time.monotonic()
                    target=fetch_public_video(link,folder,index=len(clips)+1,remaining=MAX_TOTAL_BYTES-total)
                    seconds,audio=duration_and_audio(target)
                    if not 0<seconds or duration+seconds>600:
                        raise ValueError("Общая длительность видео должна быть не больше 10 минут.")
                except Exception as exc:
                    if target is not None:target.unlink(missing_ok=True)
                    # Do not expose signed download URLs or ffmpeg internals.
                    reason=str(exc) if isinstance(exc,ValueError) else "Не удалось прочитать видео."
                    send_text(token,owner,reason+" Пришли другую ссылку или /montage для уже добавленных видео.")
                    stage("waiting_telegram","Ожидаю остальные ссылки с Яндекс Диска.")
                    continue
                elapsed=max(0.1,time.monotonic()-started)
                seen.add(link)
                clips.append(target)
                total+=target.stat().st_size
                duration+=seconds
                send_text(token,owner,
                    f"✅ Видео №{len(clips)} скачано: {target.stat().st_size/1e6:.1f} МБ за {elapsed:.1f} сек. "
                    f"Всего {len(clips)} видео, {duration:.0f} сек. "
                    "Общий доступ к этому файлу можно отключить. "
                    "Пришли ещё ссылку или напиши /montage.")
                stage("waiting_telegram",f"Добавлено {len(clips)} видео. Жду ссылки или /montage.")
    raise TimeoutError("Не получено подтверждение /montage за 30 минут. Запусти монтаж заново.")
