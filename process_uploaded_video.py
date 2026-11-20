"""GitHub Actions: download private 50 MB chunks from Cloudflare KV, edit, send MP4.

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

from bot_api_editor import call_api, render_result, send_text
from speech_review import (
    align_corrected_words, apply_word_fixes, plain_transcript,
)
from telegram_editor import duration_and_audio, transcribe_words

LOG = logging.getLogger("private_upload_montage")
MAX_BYTES = 50_000_000


def read_chunked_video(
    worker_url: str, upload_id: str, token: str, target: Path,
) -> dict:
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
        raise RuntimeError("Не удалось получить загруженный файл из Cloudflare KV.")
    size = meta.get("size")
    parts = meta.get("parts")
    chunk_size = meta.get("chunk_size")
    if (
        not isinstance(size, int) or size < 4096 or size > MAX_BYTES
        or not isinstance(chunk_size, int) or chunk_size != 4_000_000
        or not isinstance(parts, int) or parts != (size + chunk_size-1)//chunk_size
        or not 1 <= parts <= 13
    ):
        raise ValueError("Недостоверные размеры файла из Cloudflare.")
    downloaded = 0
    with target.open("wb") as file:
        for index in range(parts):
            data = None
            for attempt in range(12):
                try:
                    response = session.get(
                        base + "/chunk/" + str(index), headers=headers,
                        timeout=(20, 90),
                    )
                    if response.status_code in (404, 409):
                        time.sleep(min(3 + attempt * 2, 15))
                        continue
                    response.raise_for_status()
                    data = response.content
                    break
                except requests.RequestException:
                    if attempt == 11:
                        raise
                    time.sleep(min(3 + attempt * 2, 15))
            expected = min(chunk_size, size-index*chunk_size)
            if data is None or len(data) != expected:
                raise RuntimeError("Не удалось восстановить часть видео №" + str(index+1))
            file.write(data)
            downloaded += len(data)
            LOG.info("Downloaded secured video chunk %s/%s", index+1, parts)
    if downloaded != size:
        raise RuntimeError("Загруженное видео неполное.")
    return meta


def release_upload(worker_url: str, upload_id: str, token: str) -> None:
    try:
        requests.delete(
            worker_url.rstrip("/")+"/internal/upload/"+upload_id+"/release",
            headers={"Authorization":"Bearer "+token}, timeout=70
        )
    except requests.RequestException:
        LOG.warning("KV cleanup unavailable; keys have automatic TTL.")


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
        "📝 Черновик субтитров для видео до 50 МБ:\n\n"
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


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    owner = int(os.environ["OWNER_TELEGRAM_ID"])
    upload_id = os.environ["UPLOAD_ID"]
    worker_url = os.environ["UPLOAD_WORKER_URL"].rstrip("/")
    with tempfile.TemporaryDirectory(prefix="private-video-") as tmp:
        root = Path(tmp)
        source = root/"original.mp4"
        reference = root/"reference.mp4"
        out = root/"finished-reels.mp4"
        try:
            send_text(token,owner,"📥 Получаю исходник до 50 МБ через защищённый Cloudflare.")
            metadata=read_chunked_video(worker_url,upload_id,token,source)
            config=metadata.get("settings") or {}
            mode=config.get("mode","my_style")
            seconds,audio=duration_and_audio(source)
            if not 0 < seconds <= 125:
                raise ValueError("Видео должно быть не длиннее 2 минут.")
            if not audio and mode!="cuts":
                raise ValueError("В видео отсутствует речь / звуковая дорожка.")
            delay=float(config.get("subtitle_delay",0.30))
            if mode=="cuts":
                words=None
            else:
                send_text(token,owner,"🎧 Видео получено. Распознаю речь и готовлю черновик.")
                words=transcribe_words(source,model_size="small",language="ru")
                words,delay=wait_for_transcript_review(token,owner,words,seconds,delay)
                send_text(token,owner,"✅ Текст принят. Монтирую с сохранением Full HD.")
            selected_style=str(config.get("subtitle_style","reference_dynamic"))
            animation="phrase_float" if selected_style.endswith("_phrases") else "word_pop"
            style=selected_style.removesuffix("_phrases")
            if style not in ("reference_dynamic","signature","contrast","classic"):
                raise ValueError("Недопустимый стиль субтитров.")
            render_result(
                token,owner,source,reference,out,
                mode=mode,color=str(config.get("color","auto")),
                audio_profile=str(config.get("audio_profile","balanced")),
                subtitle_style=style,hook=str(config.get("hook","")),
                camera_style=str(config.get("camera_style","cinematic_pan")),
                speed=float(config.get("video_speed","1.0")),
                filter_style=str(config.get("video_filter","none")),
                caption_position=str(config.get("caption_position","middle")),
                font_profile=str(config.get("font_profile","elegant")),
                reviewed_words=words,caption_animation=animation,
                sound_effects=str(config.get("sound_effects","soft")),
                emoji_mode=str(config.get("emoji_mode","on")),
                hook_position=str(config.get("hook_position","off")),
                quality=str(config.get("export_quality","high")),
                subtitle_delay=delay,
            )
        except Exception as exc:
            LOG.exception("Private upload montage failed")
            send_text(
                token,owner,
                "⚠️ Монтаж 50 МБ завершился с ошибкой: "
                + str(exc)[:220]
                + "\nПроверь журнал GitHub Actions → upload-video-50mb."
            )
        finally:
            release_upload(worker_url,upload_id,token)


if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    main()
