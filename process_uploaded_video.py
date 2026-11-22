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
MAX_BYTES = 500_000_000  # entire multi-video project


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
        raise RuntimeError("Не удалось получить загруженные файлы из Cloudflare KV.")
    size = meta.get("size")
    parts = meta.get("parts")
    chunk_size = meta.get("chunk_size")
    files = meta.get("files")
    if not isinstance(files, list):
        # Compatibility with existing one-file sessions.
        files = [{"name":meta.get("original_name","original.mp4"),
                  "size":size,"parts":parts,"offset":0}]
    if not isinstance(size,int) or size<4096 or size>MAX_BYTES or \
       not isinstance(chunk_size,int) or chunk_size!=4_000_000 or \
       not isinstance(parts,int) or not 1<=parts<=165 or \
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
           not 4096<=file_size<=MAX_BYTES or \
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
            for _ in range(7):
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
        "📝 Черновик субтитров для видео до 500 МБ:\n\n"
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
            send_text(token,owner,"📥 Получаю исходные видео (до 500 МБ суммарно) через защищённый Cloudflare.")
            metadata,clips=read_chunked_project(
                worker_url,upload_id,token,root/"source_clips"
            )
            config=metadata.get("settings") or {}
            mode=config.get("mode","my_style")
            talk_scene=str(config.get("talk_scene","off"))
            if talk_scene not in ("off","contour","cream"):
                raise ValueError("Недопустимый формат разговорного Reels.")
            scene_name={
                "off":"Обычное видео","contour":"Contour Talk",
                "cream":"Cream Talk",
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
                    " подходящих MOV/WAV, шаблоны Adobe не используются напрямую.")
            from clip_montage import join_clips
            stage("joining","🎞️ Склеиваю выбранные фрагменты в порядке загрузки.")
            seconds,audio=join_clips(
                clips,source,quality=str(config.get("export_quality","high"))
            )
            send_text(token,owner,
                "🎞️ Объединил "+str(len(clips))+
                " видео в один ролик. Анализирую общую звуковую дорожку.")
            if not 0 < seconds <= 125:
                raise ValueError("Видео должно быть не длиннее 2 минут.")
            if not audio and mode!="cuts":
                raise ValueError("В видео отсутствует речь / звуковая дорожка.")
            delay=float(config.get("subtitle_delay",0.0))
            if mode=="cuts":
                words=None
            else:
                stage("transcribing","🎧 Распознаю оригинальную речь и таймкоды.")
                send_text(token,owner,"🎧 Видео получено. Распознаю речь и готовлю черновик.")
                words=transcribe_words(source,model_size="small",language="ru")
                stage("review","📝 Текст готов. Жду твоего /ok или исправлений в Telegram.")
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
            if str(stats.get("talk_scene","off"))!=talk_scene:
                raise RuntimeError(
                    "Сервер применил не тот стиль. "
                    "Готовое видео не отправляю как правильное."
                )
            # Сохраняем фактические результаты наложения, а не обещаем
            # эмодзи и звук, если они не были добавлены рендерером.
            effect_report = (
                "\n✨ Эмодзи: " + str(stats.get("emoji_count", 0))
                + " · 🔊 акценты: " + str(stats.get("sfx_count", 0))
                + " · 🎵 звуки титров: " + str(stats.get("caption_sfx_count", 0))
                + " · 🧠 смысловые акценты: " + str(stats.get("semantic_cue_count", 0))
                + " · 🎞 графика/вставки: " + str(stats.get("insert_count", 0))
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
            stage("publishing","📦 Экспорт MP4 завершён. Отправляю готовое видео.")
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
            if large and out.stat().st_size<=250_000_000:
                # Optional *high-quality master* for an iPad backup. The owner
                # does not need to open the app to receive the playable copy.
                try:
                    publish_large_mp4(worker_url,upload_id,token,out)
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
                "⚠️ Монтаж 500 МБ завершился с ошибкой: "
                + str(exc)[:220]
                + "\nПроверь журнал GitHub Actions → upload-video-50mb."
            )
        finally:
            release_upload(worker_url,upload_id,token)


if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    main()
