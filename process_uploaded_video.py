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

from bot_api_editor import call_api, send_result, send_text
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


def publish_large_mp4(worker_url: str, upload_id: str, token: str, file: Path) -> None:
    """Keep the original-quality output in private KV instead of recompressing."""
    size=file.stat().st_size
    if size>250_000_000:
        raise ValueError("Готовый MP4 больше 250 МБ: временное хранилище переполнится.")
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
                response=session.put(
                    url+"/"+str(i),headers=headers,data=data,timeout=(20,120)
                )
                response.raise_for_status()
                LOG.info("Secure output uploaded part %d/%d",i+1,parts)
        for attempt in range(10):
            response=session.post(url+"/finish",headers=headers,timeout=50)
            if response.ok:
                return
            if response.status_code!=409:
                response.raise_for_status()
            time.sleep(min(3+attempt*2,15))
        raise RuntimeError("Не удалось проверить MP4 в KV после передачи.")


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
            quality=str(config.get("export_quality","high"))
            audio_profile=str(config.get("audio_profile","balanced"))
            color=str(config.get("color","auto"))
            sound=str(config.get("sound_effects","soft"))
            emoji=str(config.get("emoji_mode","on"))
            subtitle_style=style
            caption_extras = dict(
                small_font_profile=str(config.get("small_font_profile","modern")),
                caption_variant=str(config.get("caption_variant","editorial")),
                background_style=str(config.get("background_style","occasional")),
                animation_style=str(config.get("animation_style","float")),
                subtitle_sfx=str(config.get("subtitle_sfx","soft")),
                # Existing Cloudflare already sends caption_variant.
                # The matching insert style is selected on the GitHub runner,
                # so users need no extra Cloudflare deploy for new cutaway looks.
                insert_style=str(config.get(
                    "insert_style",
                    str(config.get("caption_variant","editorial"))
                    if str(config.get("emoji_mode","on"))=="on" else "off",
                )),
                insert_density=str(config.get(
                    "insert_density",
                    "subtle" if style=="reference_dynamic" else "balanced",
                )),
                insert_sound=str(config.get(
                    "insert_sound",
                    "off" if str(config.get("sound_effects","soft"))=="off" else "on",
                )),
            )
            if mode in ("my_style", "reference"):
                from reference_editor import montage_by_reference
                stats=montage_by_reference(
                    source,None,out,color=color,
                    audio_profile=audio_profile,subtitle_style=subtitle_style,
                    hook=str(config.get("hook","")),
                    camera_style=str(config.get("camera_style","cinematic_pan")),
                    speed=float(config.get("video_speed","1.0")),
                    filter_style=str(config.get("video_filter","none")),
                    caption_position=str(config.get("caption_position","middle")),
                    font_profile=str(config.get("font_profile","elegant")),
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
                    float(config.get("video_speed","1.0")),
                    str(config.get("video_filter","none")),
                    str(config.get("caption_position","middle")),
                    str(config.get("font_profile","elegant")),
                    words,animation,sound,emoji,
                    str(config.get("hook_position","off")),
                    quality,delay,
                    **caption_extras,
                )
            # Сохраняем фактические результаты наложения, а не обещаем
            # эмодзи и звук, если они не были добавлены рендерером.
            effect_report = (
                "\n✨ Эмодзи: " + str(stats.get("emoji_count", 0))
                + " · 🔊 акценты: " + str(stats.get("sfx_count", 0))
                + " · 🎵 звуки титров: " + str(stats.get("caption_sfx_count", 0))
                + " · 🖼 винтажные вставки: " + str(stats.get("insert_count", 0))
                + " · 🔔 звуки вставок: " + str(stats.get("insert_sfx_count", 0))
            )
            LOG.info("Reels effects counts %s", {
                k:stats.get(k,0) for k in
                ("emoji_count","sfx_count","caption_sfx_count","insert_count","insert_sfx_count")
            })
            if not out.is_file() or out.stat().st_size < 1000:
                raise RuntimeError("FFmpeg не создал готовый MP4.")
            if out.stat().st_size<=48_000_000:
                send_result(
                    token,owner,out,
                    "🎬 Reels готов! Субтитры привязаны к речи, Full HD "
                    "и монтаж сохранены в MP4." + effect_report
                )
            else:
                send_text(
                    token,owner,
                    "🎞 Ролик смонтирован в высоком качестве ("+
                    str(round(out.stat().st_size/1_000_000,1))+
                    " МБ). Он больше лимита отправки Telegram, "
                    "поэтому сохраняю оригинальный MP4 для скачивания "
                    "через мини-приложение." + effect_report
                )
                publish_large_mp4(worker_url,upload_id,token,out)
                send_text(
                    token,owner,
                    "✅ MP4 готов! Открой своё Telegram Mini App, "
                    "перейди к последнему экрану и нажми "
                    "«Проверить готовность / скачать Full HD»."
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
