"""GitHub Actions: restore multi-source 500 MB projects from Cloudflare KV.

Cloudflare Worker verifies Telegram initData on upload and GitHub's bot
secret on downloads. Never print raw file, worker tokens, or full URLs.
Temporary upload fragments are deleted after processing.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import requests

from bot_api_editor import call_api, send_result, send_text
from speech_review import (
    align_corrected_words, apply_word_fixes, plain_transcript,
)
from telegram_editor import duration_and_audio, transcribe_words

LOG = logging.getLogger("private_upload_montage")
MAX_BYTES = 500_000_000  # legacy KV route
MAX_R2_BYTES = 4_000_000_000  # Paid R2 path, when configured
MAX_DO_BYTES = 3_000_000_000  # Free Durable Objects, one project


def read_chunked_project(
    worker_url: str, upload_id: str, token: str, folder: Path,
) -> tuple[dict, list[Path]]:
    """Restore each original video independently in the user's chosen order."""
    if not re.fullmatch(r"https://[a-z0-9-]+(?:\.[a-z0-9-]+)*\.workers\.dev", worker_url):
        raise ValueError("Неожиданный адрес Cloudflare Worker.")
    if not re.fullmatch(r"[a-f0-9-]{36}", upload_id):
        raise ValueError("Неверный идентификатор загрузки.")
    base = worker_url.rstrip("/") + "/internal/upload/" + upload_id
    headers = {"Authorization": "Bearer " + token}
    session = requests.Session()
    meta = None
    for attempt in range(10):
        try:
            response = session.get(base + "/manifest", headers=headers, timeout=45)
            if response.status_code in (404, 409):
                time.sleep(min(3 + attempt * 2, 15))
                continue
            response.raise_for_status()
            meta = response.json()
            break
        except (requests.RequestException, ValueError):
            if attempt == 9:
                raise
            time.sleep(min(3 + attempt * 2, 15))
    if not isinstance(meta, dict):
        raise RuntimeError("Не удалось получить файлы из Cloudflare.")
    if meta.get("transport") in ("telegram","yandex"):
        return meta, []
    storage = meta.get("storage","kv")
    if storage not in ("kv","r2","do"):
        raise ValueError("Неизвестный тип хранилища проекта.")
    cap = (MAX_DO_BYTES if storage=="do" else
           MAX_R2_BYTES if storage=="r2" else MAX_BYTES)
    part_cap = 800 if storage=="do" else 1100 if storage=="r2" else 165
    size = meta.get("size")
    parts = meta.get("parts")
    chunk_size = meta.get("chunk_size")
    files = meta.get("files")
    if not isinstance(files, list):
        # Compatibility with existing one-file sessions.
        files = [{"name":meta.get("original_name","original.mp4"),
                  "size":size,"parts":parts,"offset":0}]
    if not isinstance(size,int) or size<4096 or size>cap or \
       not isinstance(chunk_size,int) or chunk_size!=4_000_000 or \
       not isinstance(parts,int) or not 1<=parts<=part_cap or \
       not 1<=len(files)<=12:
        raise ValueError("Недостоверные размеры проекта из Cloudflare.")
    validated=[]
    expected_offset=0
    total=0
    for item in files:
        if not isinstance(item,dict):
            raise ValueError("Повреждён список исходных видео.")
        name=item.get("name")
        file_size=item.get("size")
        count=item.get("parts")
        offset=item.get("offset")
        if not isinstance(name,str) or not re.search(
            r"\.(mp4|mov|m4v|webm|mkv)$",name,re.I
        ) or not isinstance(file_size,int) or \
           not 4096<=file_size<=cap or \
           not isinstance(count,int) or count!=(file_size+chunk_size-1)//chunk_size or \
           not isinstance(offset,int) or offset!=expected_offset:
            raise ValueError("Не совпадает список видео и фрагментов.")
        expected_offset+=count
        total+=file_size
        validated.append((name,file_size,count,offset))
    if total!=size:
        raise ValueError("Размеры проекта и всех видео не совпадают.")
    asset_files=meta.get("assets",[])
    if not isinstance(asset_files,list) or len(asset_files)>4:
        raise ValueError("Недостоверный список архивов эффектов.")
    asset_size=0
    for item in asset_files:
        if not isinstance(item,dict):
            raise ValueError("Повреждён перечень эффектов.")
        name=item.get("name")
        file_size=item.get("size")
        count=item.get("parts")
        offset=item.get("offset")
        if not isinstance(name,str) or not name.lower().endswith(".zip") or \
           not isinstance(file_size,int) or not 100<=file_size<=100_000_000 or \
           not isinstance(count,int) or count!=(file_size+chunk_size-1)//chunk_size or \
           not isinstance(offset,int) or offset!=expected_offset:
            raise ValueError("Не совпадают архивы эффектов и их фрагменты.")
        expected_offset+=count
        asset_size+=file_size
        validated.append((name,file_size,count,offset))
    if expected_offset!=parts or asset_size>100_000_000 or \
       asset_size!=meta.get("asset_size",0):
        raise ValueError("Размеры архива эффектов не совпадают с проектом.")

    folder.mkdir(parents=True,exist_ok=True)
    targets=[]
    downloaded=0
    for file_no,(name,file_size,count,offset) in enumerate(validated):
        ext=Path(name).suffix.lower()
        target=(folder/f"clip_{file_no+1:03d}{ext}" if file_no<len(files)
                else folder/f"asset_{file_no-len(files)+1:02d}.zip")
        with target.open("wb") as output:
            for index in range(count):
                part_no=offset+index
                expected=min(chunk_size,file_size-index*chunk_size)
                data=None
                for attempt in range(12):
                    try:
                        response=session.get(
                            base + "/chunk/" + str(part_no), headers=headers,
                            timeout=(20,90)
                        )
                        if response.status_code in (404,409):
                            time.sleep(min(3+attempt*2,15))
                            continue
                        response.raise_for_status()
                        data=response.content
                        break
                    except requests.RequestException:
                        if attempt==11:
                            raise
                        time.sleep(min(3+attempt*2,15))
                if data is None or len(data)!=expected:
                    raise RuntimeError(
                        "Не удалось восстановить часть "+str(index+1)+
                        " исходного видео №"+str(file_no+1)
                    )
                output.write(data)
                downloaded+=len(data)
                LOG.info("Downloaded source %d/%d, chunk %d/%d",
                         file_no+1,len(validated),index+1,count)
        if target.stat().st_size!=file_size:
            raise RuntimeError("Размер восстановленного видео не совпадает.")
        if file_no<len(files):
            targets.append(target)
    if downloaded!=size+asset_size:
        raise RuntimeError("Видео и графические ZIP-пакеты восстановлены не полностью.")
    return meta,targets


def read_chunked_video(
    worker_url: str, upload_id: str, token: str, target: Path,
) -> dict:
    """Compatibility wrapper for callers expecting a single video file."""
    meta,files=read_chunked_project(worker_url,upload_id,token,target.parent)
    if len(files)!=1:
        raise ValueError("Для нескольких видео используй read_chunked_project.")
    import shutil
    shutil.move(str(files[0]),str(target))
    return meta


def release_upload(worker_url: str, upload_id: str, token: str) -> None:
    """Delete source chunks in safe groups of 30 KV operations per request."""
    url=worker_url.rstrip("/")+"/internal/upload/"+upload_id+"/release"
    try:
        with requests.Session() as session:
            position=0
            for _ in range(50):
                response=session.delete(
                    url+"?from="+str(position),
                    headers={"Authorization":"Bearer "+token},timeout=70
                )
                if not response.ok:
                    response.raise_for_status()
                report=response.json()
                if not report.get("has_more"):
                    return
                next_pos=report.get("next")
                if not isinstance(next_pos,int) or next_pos<=position:
                    break
                position=next_pos
            LOG.warning("KV cleanup incomplete; remaining fragments have TTL.")
    except (requests.RequestException,ValueError):
        LOG.warning("KV cleanup unavailable; keys have automatic TTL.")



def publish_large_mp4(worker_url: str, upload_id: str, token: str, file: Path,
                      *, storage: str="kv") -> None:
    """Keep the original-quality output in private KV or R2, without shrinking."""
    size=file.stat().st_size
    limit=3_000_000_000 if storage in ("r2","do") else 250_000_000
    if size>limit:
        raise ValueError("Готовый MP4 превышает доступный объём временного хранилища.")
    url=worker_url.rstrip("/")+"/internal/upload/"+upload_id+"/result"
    headers={"Authorization":"Bearer "+token}
    chunk_size=4_000_000
    parts=(size+chunk_size-1)//chunk_size
    with requests.Session() as session:
        response=session.post(url+"/start",headers=headers,json={"size":size},timeout=40)
        response.raise_for_status()
        with file.open("rb") as stream:
            for i in range(parts):
                data=stream.read(chunk_size)
                for attempt in range(10):
                    try:
                        response=session.put(
                            url+"/"+str(i),headers=headers,data=data,timeout=(20,120)
                        )
                        if response.ok:
                            break
                        if response.status_code not in (409,429,500,502,503,504):
                            response.raise_for_status()
                    except requests.RequestException:
                        if attempt == 9:
                            raise
                    if attempt == 9:
                        raise RuntimeError(
                            "Не удалось передать часть готового MP4 №"+str(i+1)
                        )
                    time.sleep(min(3+attempt*2,15))
                LOG.info("Secure output uploaded part %d/%d",i+1,parts)
        for attempt in range(10):
            response=session.post(url+"/finish",headers=headers,timeout=50)
            if response.ok:
                return
            if response.status_code!=409:
                response.raise_for_status()
            time.sleep(min(3+attempt*2,15))
        raise RuntimeError("Не удалось проверить MP4 после передачи.")


def wait_for_transcript_review(
    token: str, chat_id: int,
    raw_words: list[tuple[float,float,str]],
    duration: float,
    delay: float,
) -> tuple[list[tuple[float,float,str]],float]:
    transcript = plain_transcript(raw_words)
    if not transcript:
        raise ValueError("Не удалось распознать речь. Попробуй другой исходник.")
    # Clear stale update offset before requesting a NEW confirmation.
    recent = call_api(token, "getUpdates", {"offset":-1, "limit":1,"timeout":0})
    offset = recent[-1]["update_id"]+1 if recent else None
    send_text(
        token,chat_id,
        "📝 Черновик субтитров для видео:\n\n"
        + transcript[:3500]
        + "\n\n⏱ Сдвиг титров: +"+str(round(delay,2))+" сек.\n"
        "Ответь /ok или /fix ошибка=правильно, /text ПОЛНЫЙ ТЕКСТ.\n"
        "Если надписи выходят рано, перед /ok отправь /sync 0.5 "
        "(можно до 1.5 сек)."
    )
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        args={"limit":20,"timeout":15,"allowed_updates":'["message"]'}
        if offset is not None:
            args["offset"]=offset
        updates=call_api(token,"getUpdates",args,timeout=35)
        for update in updates:
            offset=update["update_id"]+1
            message=update.get("message",{})
            if message.get("from",{}).get("id")!=chat_id or \
                    message.get("chat",{}).get("type")!="private":
                continue
            text=str(message.get("text","")).strip()
            lower=text.lower()
            if lower.startswith("/sync "):
                try:
                    new_delay=float(text.split(maxsplit=1)[1].replace(",","."))
                    if not -0.5 <= new_delay <= 1.5:
                        raise ValueError()
                    delay=new_delay
                    send_text(token,chat_id,"⏱ Смещение титров: "+str(round(delay,2))+" сек.")
                except ValueError:
                    send_text(token,chat_id,"Значение /sync от -0.5 до 1.5 сек.")
                continue
            if lower=="/ok":
                return raw_words,delay
            if lower.startswith("/fix "):
                return apply_word_fixes(raw_words,text[5:]),delay
            if lower.startswith("/text "):
                return align_corrected_words(raw_words,text[6:],duration),delay
            if lower:
                send_text(token,chat_id,"Ожидаю /ok, /fix, /text или /sync 0.4.")
    raise TimeoutError("Не получено подтверждение субтитров за 15 минут.")



def receive_telegram_source(token,owner,folder,stage):
    """Accept one new owner video in the current serialized montage job."""
    import asyncio
    from bot_api_editor import select_video, download_video
    api_id=os.environ.get("TELEGRAM_API_ID","").strip()
    api_hash=os.environ.get("TELEGRAM_API_HASH","").strip()
    large_ready=bool(api_id and api_hash)
    if large_ready and (not api_id.isdigit() or not re.fullmatch(r"[a-fA-F0-9]{32}",api_hash)):
        raise ValueError("Проверь TELEGRAM_API_ID и TELEGRAM_API_HASH в GitHub.")
    folder.mkdir(parents=True,exist_ok=True)
    prompt=call_api(token,"sendMessage",{"chat_id":owner,"text":
        "✅ Настройки монтажа приняты. Пришли ОДНО исходное видео как файл (без сжатия). "
        +("До 3 ГБ, если Telegram позволяет такой размер. " if large_ready else
          "Пока доступно до 20 МБ. Для больших файлов нужно добавить TELEGRAM_API_ID и TELEGRAM_API_HASH в GitHub. ")
        +"После отправки можешь закрыть приложение. /cancel — отмена. Ожидаю 30 минут."})
    min_id=int(prompt["message_id"])
    deadline=time.monotonic()+1800
    offset=None
    while time.monotonic()<deadline:
        args={"limit":30,"timeout":15,"allowed_updates":'["message"]'}
        if offset is not None:args["offset"]=offset
        updates=call_api(token,"getUpdates",args,timeout=35)
        for update in updates:
            offset=update["update_id"]+1
            msg=update.get("message",{})
            if (msg.get("from",{}).get("id")!=owner or msg.get("chat",{}).get("id")!=owner
                or msg.get("chat",{}).get("type")!="private" or msg.get("message_id",0)<=min_id):
                continue
            if str(msg.get("text","")).strip().lower()=="/cancel":
                raise ValueError("Загрузка через Telegram отменена.")
            media=select_video(msg)
            if not media:continue
            size=int(media.get("file_size") or 0)
            if not 4096<=size<=MAX_DO_BYTES:
                send_text(token,owner,"Пришли видео от 4 КБ до 3 ГБ.")
                continue
            if size>20_000_000 and not large_ready:
                send_text(token,owner,"Для этого размера нужны TELEGRAM_API_ID и TELEGRAM_API_HASH. Сейчас можно прислать файл до 20 МБ или отменить /cancel.")
                continue
            suffix=Path(media.get("file_name") or "source.mp4").suffix.lower()
            if suffix not in (".mp4",".mov",".m4v",".webm",".mkv"):suffix=".mp4"
            target=folder/("clip_001"+suffix)
            stage("downloading","Скачиваю исходник с серверов Telegram.")
            send_text(token,owner,"📥 Видео получено. Теперь сервер скачивает его сам, мини-приложение не нужно.")
            if size<=20_000_000:
                download_video(token,media["file_id"],target)
            else:
                async def fetch_source():
                    from telethon import TelegramClient
                    from telethon.sessions import MemorySession
                    client=TelegramClient(MemorySession(),int(api_id),api_hash,receive_updates=False)
                    await client.start(bot_token=token)
                    try:
                        original=await client.get_messages(None,ids=int(msg["message_id"]))
                        if (not original or original.sender_id!=owner or not original.is_private
                                or not original.file or original.file.size!=size):
                            raise ValueError("Не удалось подтвердить исходное сообщение Telegram.")
                        result=await client.download_media(original,file=str(target))
                        if not result:raise RuntimeError("Telegram не вернул исходный файл.")
                    finally:
                        await client.disconnect()
                asyncio.run(fetch_source())
            if not target.is_file() or target.stat().st_size!=size:
                raise RuntimeError("Исходник Telegram скачан не полностью.")
            return target
    raise TimeoutError("Видео не получено за 30 минут. Запусти отправку заново.")


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    owner = int(os.environ["OWNER_TELEGRAM_ID"])
    upload_id = os.environ["UPLOAD_ID"]
    worker_url = os.environ["UPLOAD_WORKER_URL"].rstrip("/")
    from montage_progress import publish_progress

    def stage(name: str, message: str = "") -> None:
        # A failed status update must NEVER abort or delay the final Reels.
        publish_progress(worker_url,upload_id,token,name,message)

    with tempfile.TemporaryDirectory(prefix="private-video-") as tmp:
        root = Path(tmp)
        source = root/"original.mp4"
        reference = root/"reference.mp4"
        out = root/"finished-reels.mp4"
        try:
            stage("downloading","📥 Скачиваю все исходные видео в монтаж.")
            metadata,clips=read_chunked_project(
                worker_url,upload_id,token,root/"source_clips"
            )
            # This is critical for 3 GB on the Free plan's 5 GB TOTAL DO
            # storage. The verified source files are now local to GitHub;
            # free the remote shards BEFORE generating/uploading the master.
            if metadata.get("transport")=="yandex":
                from yandex_source import receive_yandex_source
                stage("waiting_telegram","Ожидаю ссылку на видео с Яндекс Диска.")
                clips=[receive_yandex_source(token,owner,root/"source_clips",stage)]
            elif metadata.get("transport")=="telegram":
                stage("waiting_telegram","Ожидаю исходное видео в чате Telegram.")
                clips=[receive_telegram_source(token,owner,root/"source_clips",stage)]
            elif metadata.get("storage")=="do":
                release_upload(worker_url,upload_id,token)
                send_text(token,owner,
                    "🧹 Исходники загружены на сервер монтажа. "
                    "Освобождаю бесплатное облачное хранилище перед экспортом.")
            config=metadata.get("settings") or {}
            mode=config.get("mode","my_style")
            talk_scene=str(config.get("talk_scene","off"))
            if talk_scene not in ("off","contour","cream","pistachio","burgundy_brown"):
                raise ValueError("Недопустимый формат разговорного Reels.")
            scene_name={
                "off":"Обычное видео","contour":"Contour Talk",
                "cream":"Cream Talk",
                "pistachio":"Pistachio Talk",
                "burgundy_brown":"Burgundy & Brown",
            }[talk_scene]
            send_text(token,owner,
                "🎨 Подтверждённый стиль монтажа: "+scene_name+". "
                "Расположение текста, графика и композиция взяты из этого проекта.")

            asset_packs=sorted((root/"source_clips").glob("asset_*.zip"))
            private_assets=None
            if asset_packs:
                from private_effect_assets import prepare_private_effect_assets
                private_assets=prepare_private_effect_assets(
                    asset_packs,root/"private_assets"
                )
                send_text(token,owner,
                    "🎨 Приватные наборы проверены: "+str(private_assets.selected_files)+
                    " файлов, предметных PNG: "+str(
                        sum(len(v) for v in __import__("semantic_object_overlays").inventory(
                            private_assets.photos).values())
                    )+", анимированных фонов: "+str(
                        len(private_assets.backgrounds)
                    )+". Они применяются по смыслу речи, а не случайно.")
            from clip_montage import join_clips
            stage("joining","🎞️ Склеиваю выбранные фрагменты в порядке загрузки.")
            seconds,audio=join_clips(
                clips,source,quality=str(config.get("export_quality","high"))
            )
            send_text(token,owner,
                "🎞️ Объединил "+str(len(clips))+
                " видео в один ролик. Анализирую общую звуковую дорожку.")
            if not 0 < seconds <= 600:
                raise ValueError("Видео должно быть не длиннее 10 минут.")
            if not audio and mode!="cuts":
                raise ValueError("В видео отсутствует речь / звуковая дорожка.")
            delay=float(config.get("subtitle_delay",0.0))
            repeat_cuts=()
            if mode=="cuts":
                words=None
                if audio:
                    from speech_review import plan_speech_repeats
                    raw=transcribe_words(source,model_size="small",language="ru")
                    words,repeat_cuts=plan_speech_repeats(raw)
            else:
                stage("transcribing","🎧 Распознаю оригинальную речь и таймкоды.")
                send_text(token,owner,"🎧 Видео получено. Распознаю речь и готовлю черновик.")
                # Short talking Reels are particularly sensitive to a single
                # wrong accent word. Use the stronger recognizer for short
                # clips; keep the existing cheaper setting for long projects.
                recognition_model="medium" if seconds<=35 else "small"
                words=transcribe_words(
                    source,model_size=recognition_model,language="ru"
                )
                if mode!="captions":
                    from speech_review import plan_speech_repeats
                    words,repeat_cuts=plan_speech_repeats(words)
                    if repeat_cuts:
                        send_text(token,owner,"✂️ Найдено повторных дублей: "+str(len(repeat_cuts))+
                            ". Оставляю последние варианты. Ранние дубли вырежу из видео и звука; "
                            "ниже текст без этих повторов для проверки.")
                stage("review","📝 Текст готов. Жду проверки КАЖДОГО слова перед монтажом.")
                words,delay=wait_for_transcript_review(token,owner,words,seconds,delay)
                stage("planning","🧠 Подбираю смысловые вставки по тексту.")
                # Explain WHY an illustration appears, never hide arbitrary
                # decorative insert choices from the author of the Reels.
                if talk_scene!="off":
                    send_text(token,owner,
                        "✨ В студийном стиле оставляю только редкие "
                        "небольшие акценты, подтверждённые речью. "
                        "Огромные старые карточки и случайные картинки выключены.")
                if (talk_scene=="off" and
                    config.get("insert_style","reference_soft")=="reference_soft"):
                    from semantic_editing import choose_semantic_cues
                    plan=choose_semantic_cues(
                        words,seconds,str(config.get("insert_density","subtle"))
                    )
                    if plan:
                        descriptions={
                            "error":"акцент на ошибке",
                            "inspect":"лупа на важной детали",
                            "success":"показать исправление",
                            "compare":"сравнить два варианта",
                            "time":"указать время",
                            "speech":"выделить вопрос",
                            "camera":"сцена про съёмку",
                            "phone":"показать приложение",
                            "next":"переход к следующему шагу",
                        }
                        lines=[
                            str(round(c.start,1))+" с: "+
                            descriptions.get(c.kind,c.reason)
                            for c in plan[:6]
                        ]
                        send_text(token,owner,
                            "🧠 План смыслового монтажа по речи:\n"+
                            "\n".join(lines)+
                            "\n\nСлучайные вставки не добавляю.")
                    else:
                        send_text(token,owner,
                            "🧠 По этой речи крупных смысловых вставок не нужно: "
                            "сохраню чистый монтаж и аккуратные субтитры.")
                send_text(token,owner,"✅ Текст принят. Монтирую с сохранением Full HD.")
            stage("rendering","🎬 Накладываю субтитры, анимации и эффекты.")
            selected_style=str(config.get("subtitle_style","reference_dynamic"))
            animation="phrase_float" if selected_style.endswith("_phrases") else "word_pop"
            style=selected_style.removesuffix("_phrases")
            if style not in ("reference_dynamic","signature","contrast","classic"):
                raise ValueError("Недопустимый стиль субтитров.")
            quality=str(config.get("export_quality","high"))
            audio_profile=str(config.get("audio_profile","balanced"))
            color=str(config.get("color","auto"))
            sound=str(config.get("sound_effects","soft"))
            emoji=str(config.get("emoji_mode","on"))
            subtitle_style=style
            caption_extras = dict(
                small_font_profile=str(config.get("small_font_profile","refined")),
                caption_variant=str(config.get("caption_variant","reference_soft")),
                background_style=str(config.get("background_style","occasional")),
                subject_layout=str(config.get("subject_layout","standard")),
                talk_scene=str(config.get("talk_scene","off")),
                animation_style=str(config.get("animation_style","float")),
                subtitle_sfx=str(config.get("subtitle_sfx","soft")),
                pause_removal=str(config.get("pause_removal","tight")),
                top_title=str(config.get("top_title","")),
                top_title_mode=str(config.get("top_title_mode","auto")),
                # Small emoji never enable oversized themed cards.
                guide_effect=str(config.get("guide_effect","auto")),
                insert_style=str(config.get("insert_style","reference_soft")),
                insert_density=str(config.get(
                    "insert_density",
                    "balanced",
                )),
                insert_sound=str(config.get(
                    "insert_sound",
                    "off" if str(config.get("sound_effects","soft"))=="off" else "on",
                )),
                private_assets=private_assets,
                repeat_cuts=tuple(repeat_cuts),
            )
            if mode in ("my_style", "reference"):
                from reference_editor import montage_by_reference
                stats=montage_by_reference(
                    source,None,out,color=color,
                    audio_profile=audio_profile,subtitle_style=subtitle_style,
                    hook=str(config.get("hook","")),
                    camera_style=str(config.get("camera_style","cinematic_pan")),
                    speed=float(config.get("video_speed","1.2")),
                    filter_style=str(config.get("video_filter","none")),
                    caption_position=str(config.get("caption_position","middle")),
                    font_profile=str(config.get("font_profile","old_money")),
                    words_override=words,
                    caption_animation=animation,
                    sound_effects=sound,emoji_mode=emoji,
                    hook_position=str(config.get("hook_position","off")),
                    quality=quality,subtitle_delay=delay,
                    **caption_extras,
                )
            else:
                from telegram_editor import edit_video
                stats=edit_video(
                    source,out,mode,color,audio_profile,subtitle_style,
                    str(config.get("hook","")),
                    float(config.get("video_speed","1.2")),
                    str(config.get("video_filter","none")),
                    str(config.get("caption_position","middle")),
                    str(config.get("font_profile","elegant")),
                    words,animation,sound,emoji,
                    str(config.get("hook_position","off")),
                    quality,delay,
                    **caption_extras,
                )
            if str(stats.get("filter_applied","none"))!=str(
                config.get("video_filter","none")
            ):
                raise RuntimeError(
                    "Выбранный фильтр не был передан в реальный рендер."
                )
            if str(stats.get("talk_scene","off"))!=talk_scene:
                raise RuntimeError(
                    "Сервер применил не тот стиль. "
                    "Готовое видео не отправляю как правильное."
                )
            # Сохраняем фактические результаты наложения, а не обещаем
            # эмодзи и звук, если они не были добавлены рендерером.
            effect_report = (
                "\n✂️ Удалено повторных дублей: " + str(len(repeat_cuts))
                + "\n✨ Эмодзи: " + str(stats.get("emoji_count", 0))
                + " · 🔊 акценты: " + str(stats.get("sfx_count", 0))
                + " · 🎵 звуки титров: " + str(stats.get("caption_sfx_count", 0))
                + " · 🧠 смысловые акценты: " + str(stats.get("semantic_cue_count", 0))
                + " · 🎞 графика/вставки: " + str(stats.get("insert_count", 0))
                + " · 🔠 крупные анимированные слова: " + str(stats.get("kinetic_word_count", 0))
                + " · 🎨 фильтр видео: " + str(stats.get("filter_applied", "none"))
                + " · 🎁 предметы из твоего ZIP: " + str(stats.get("speech_object_count", 0))
                + " · ✨ Приёмы из гайда: " + str(stats.get("guide_effect_count", 0))
                + " (" + ", ".join(stats.get("guide_effects_rendered",[])[:5]) + ")"
                + " · 🎨 иконки из ZIP: " + str(stats.get("private_asset_count", 0))
                + " · 🔔 звуки вставок: " + str(stats.get("insert_sfx_count", 0))
            )
            LOG.info("Reels effects counts %s", {
                k:stats.get(k,0) for k in
                ("emoji_count","sfx_count","caption_sfx_count","insert_count",
                 "insert_sfx_count","semantic_cue_count","private_asset_count")
            })
            if not out.is_file() or out.stat().st_size < 1000:
                raise RuntimeError("FFmpeg не создал готовый MP4.")
            # Never deliver a crop/square montage as a correctly rendered Reels.
            from telegram_editor import media_info
            video_stream=next((
                s for s in media_info(out).get("streams",[])
                if s.get("codec_type")=="video"
            ),{})
            width=int(video_stream.get("width") or 0)
            height=int(video_stream.get("height") or 0)
            if width<360 or height<640 or abs(width/height-9/16)>.006:
                raise RuntimeError(
                    "Экспорт получился не в вертикальном формате 9:16. "
                    "Ролик не отправляю, исправь настройки рендера."
                )
            selected_guide=str(config.get("guide_effect","off"))
            # A manually checked favorite is a required visual outcome, not a
            # semantic suggestion. Never send a plain talking-head video while
            # claiming that the user-selected carousel has been applied.
            if (selected_guide.startswith("multi:") and
                str(config.get("insert_style","reference_soft"))!="off" and
                float(stats.get("after",0))>=6.0 and
                int(stats.get("guide_effect_count",0))<1):
                raise RuntimeError(
                    "Отмеченные вручную анимации не появились в MP4. "
                    "Отправка остановлена: нужно проверить создание карусели."
                )
            if (selected_guide.startswith("multi:") and
                str(config.get("insert_sound","off"))=="on" and
                int(stats.get("guide_effect_count",0))>0 and
                int(stats.get("insert_sfx_count",0))<
                int(stats.get("guide_effect_count",0))):
                raise RuntimeError(
                    "Выбранная анимация создана, но звук перехода пропал. "
                    "Отправка некорректного монтажа остановлена."
                )
            if (selected_guide not in ("off","auto") and
                not selected_guide.startswith("multi:") and
                str(config.get("insert_style","reference_soft"))!="off" and
                len(words)>=3 and float(stats.get("after",0))>=4 and
                int(stats.get("guide_effect_count",0))<1):
                raise RuntimeError(
                    "Выбран эффект из PDF, но рендер его не создал. "
                    "Готовый MP4 не отправляю как корректный."
                )
            # A 40-second speaking Reels with explicitly selected cutaways
            # must not silently export as a static branded template.
            # No relevant noun or visual concept means a CLEAN talking Reels,
            # not an export failure. Do not require a made-up animation merely
            # because the default automatic mode is switched on.
            if (talk_scene!="off" and
                str(config.get("insert_style","reference_soft"))!="off" and
                str(config.get("guide_effect","auto")) not in ("auto","off") and
                not str(config.get("guide_effect","auto")).startswith("multi:") and
                len(words)>=10 and float(stats.get("after",0))>=12 and
                int(stats.get("insert_count",0))<1):
                raise RuntimeError(
                    "Ты выбрала конкретный приём, но рендер его не создал. "
                    "Отправка неполного монтажа остановлена."
                )
            if (str(config.get("subtitle_sfx","soft"))=="typewriter" and
                len(words)>=6 and int(stats.get("caption_sfx_count",0))<1):
                raise RuntimeError(
                    "Выбран звук печатающей машинки, но в экспорте он не появился."
                )
            stage("publishing","📦 Экспорт MP4 9:16 с выбранными эффектами. Отправляю видео.")
            from telegram_delivery import telegram_copy,send_video_to_telegram
            # Direct delivery is the PRIMARY outcome, not a secondary
            # download button hidden behind the Mini App setup wizard.
            large=out.stat().st_size>48_000_000
            if large:
                send_text(token,owner,
                    "📦 Ролик готов. Делаю отдельную версию до 48 МБ "
                    "для отправки прямо в Telegram. Исходный мастер не заменяю.")
            telegram_file=telegram_copy(out,root/"telegram-reels.mp4")
            caption=(
                "🎬 Готовый Reels · "+scene_name+"! "
                "Видео воспроизводится прямо в Telegram.\n"
                "🎞 Убраны паузы; скорость и субтитры синхронизированы."
                +effect_report
            )
            sent=False
            send_error=None
            try:
                send_video_to_telegram(token,owner,telegram_file,caption)
                sent=True
            except Exception as exc:
                send_error=str(exc)
                LOG.exception("Telegram upload failed; keeping a download backup.")
            master_saved=False
            if large and out.stat().st_size<=(3_000_000_000 if metadata.get("storage") in ("r2","do") else 250_000_000):
                # Optional *high-quality master* for an iPad backup. The owner
                # does not need to open the app to receive the playable copy.
                try:
                    publish_large_mp4(worker_url,upload_id,token,out,
                                      storage=metadata.get("storage","kv"))
                    master_saved=True
                except Exception:
                    LOG.exception("Optional Full HD master backup failed.")
            if sent:
                send_text(token,owner,
                    "✅ Готовый Reels отправлен выше прямо в Telegram."+
                    (" 💾 Мастер-версия без уменьшения размера также доступна "
                     "в Mini App до автоудаления через 3 дня."
                     if master_saved else ""))
            elif master_saved:
                send_text(token,owner,
                    "⚠️ Telegram отклонил автоматическую отправку MP4. "
                    "Сохранила мастер-версию в Mini App; "
                    "видео не потеряно. Ошибка: "+str(send_error)[:150])
                raise RuntimeError("Telegram не принял файл, доступна резервная копия.")
            else:
                raise RuntimeError("Telegram не принял итоговый файл: "+
                                   str(send_error)[:150])
            stage("done","✅ Видео смонтировано и доступно в Telegram или Mini App.")

        except Exception as exc:
            stage("failed","⚠️ Ошибка монтажа: "+str(exc)[:140])
            LOG.exception("Private upload montage failed")
            send_text(
                token,owner,
                "⚠️ Монтаж видео завершился с ошибкой: "
                + str(exc)[:220]
                + "\nПроверь журнал GitHub Actions → upload-video-50mb."
            )
            raise
        finally:
            release_upload(worker_url,upload_id,token)


if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    main()
