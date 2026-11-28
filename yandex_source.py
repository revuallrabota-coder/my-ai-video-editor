"""Download an explicitly shared Yandex Disk video, never arbitrary URLs."""
import re
import time
from pathlib import Path
from urllib.parse import urlsplit, urljoin

import requests
from bot_api_editor import call_api, send_text

API="https://cloud-api.yandex.net/v1/disk/public/resources"
MAX_BYTES=1_000_000_000
SUFFIXES={".mp4",".mov",".m4v",".webm",".mkv"}

def public_link(text):
    value=str(text).strip()
    if re.fullmatch(r"https://(?:disk\.yandex\.(?:ru|com)|yadi\.sk)/[di]/[A-Za-z0-9_-]{4,160}/?",value):
        return value
    return None

def download_host(url):
    try:
        p=urlsplit(url)
        host=p.hostname or ""
        return (p.scheme=="https" and not p.username and not p.password
                and p.port in (None,443) and
                (host in ("downloader.disk.yandex.ru","downloader.disk.yandex.net",
                          "downloader.dst.yandex.ru","downloader.dst.yandex.net")
                 or bool(re.fullmatch(r"[a-z0-9-]+\.disk\.yandex\.(?:net|ru)",host))))
    except ValueError:
        return False

def fetch_public_video(link,folder,session=None):
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
        with session.get(API+"/download",params=params,timeout=(10,30),allow_redirects=False) as r:
            if r.status_code!=200:
                raise ValueError("Яндекс не разрешил скачивание. Проверь доступ или дневной лимит.")
            href=r.json().get("href","")
        folder.mkdir(parents=True,exist_ok=True)
        target=folder/("clip_001"+ext)
        deadline=time.monotonic()+900
        for _ in range(5):
            if not download_host(href):
                raise ValueError("Яндекс вернул неподдерживаемый адрес скачивания.")
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
    prompt=call_api(token,"sendMessage",{"chat_id":owner,"text":
        "✅ Настройки сохранены. Загрузи ОДНО видео до 1 ГБ в Яндекс Диск, "
        "нажми «Поделиться ссылкой» и пришли сюда ссылку на файл. "
        "Используй только видео, которым готова поделиться по ссылке. "
        "После скачивания отключи общий доступ на Диске. /cancel — отмена. "
        "Жду ссылку 30 минут."})
    min_id=int(prompt["message_id"])
    deadline=time.monotonic()+1800
    offset=None
    while time.monotonic()<deadline:
        args={"limit":30,"timeout":15,"allowed_updates":'["message"]'}
        if offset is not None:
            args["offset"]=offset
        for update in call_api(token,"getUpdates",args,timeout=35):
            offset=update["update_id"]+1
            msg=update.get("message",{})
            if (msg.get("from",{}).get("id")!=owner or msg.get("chat",{}).get("id")!=owner
                or msg.get("chat",{}).get("type")!="private" or msg.get("message_id",0)<=min_id):
                continue
            text=str(msg.get("text","")).strip()
            if text.lower()=="/cancel":
                raise ValueError("Загрузка через Яндекс Диск отменена.")
            link=public_link(text)
            if not link:
                if text:
                    send_text(token,owner,"Пришли только ссылку на видео с Яндекс Диска.")
                continue
            stage("downloading","Скачиваю исходное видео с Яндекс Диска.")
            send_text(token,owner,"📥 Получила ссылку. Скачиваю видео на сервер монтажа.")
            try:
                started=time.monotonic()
                target=fetch_public_video(link,folder)
            except ValueError as exc:
                send_text(token,owner,str(exc)+" Пришли исправленную ссылку или /cancel.")
                stage("waiting_telegram","Ожидаю рабочую ссылку на Яндекс Диск.")
                continue
            seconds=max(0.1,time.monotonic()-started)
            send_text(token,owner,
                f"✅ Исходник скачан: {target.stat().st_size/1e6:.1f} МБ за {seconds:.1f} сек. "
                "Теперь можно отключить общий доступ на Яндекс Диске. Продолжаю монтаж.")
            return target
    raise TimeoutError("Не получила ссылку за 30 минут. Запусти монтаж заново.")
