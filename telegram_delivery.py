"""Make every finished Reels playable in the owner's Telegram chat.

Telegram's cloud Bot API limits direct file upload to 50 MB. Preserve the
full-quality master when useful, but provide a separate H.264/AAC MP4 sized
under 48 MB for direct Telegram delivery, instead of forcing the owner back
through five Mini App screens. Never silently claim that a file was delivered.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

import requests

from telegram_editor import duration_and_audio, media_info

LOG=logging.getLogger("telegram_delivery")
TELEGRAM_SAFE_BYTES=48_000_000
TARGET_BYTES=45_000_000


def telegram_copy(master: Path, dest: Path, *, max_bytes: int=TELEGRAM_SAFE_BYTES,
                  target_bytes: int=TARGET_BYTES) -> Path:
    """Return master as-is if small, else re-encode a pitch-preserving copy.

    The full-resolution original is not overwritten. Two-pass H.264 is used
    because CRF cannot guarantee a <=50MB upload limit.
    """
    if not master.is_file() or master.stat().st_size<1024:
        raise ValueError("Готовое видео отсутствует.")
    if master.stat().st_size<=max_bytes:
        return master
    duration,has_audio=duration_and_audio(master)
    if duration<=0:
        raise ValueError("Некорректная длительность готового видео.")
    dest.parent.mkdir(parents=True,exist_ok=True)
    audio_bps=128000 if has_audio else 0
    base=int((target_bytes*8/duration-audio_bps)*.965)
    # A two-minute clip can use ~2.75 Mbps video + 128 kbps audio.
    if base<120000:
        raise ValueError("Ролик слишком длинный для безопасной отправки через Telegram.")
    probe=media_info(master)
    video=next((s for s in probe.get("streams",[])
                if s.get("codec_type")=="video"),{})
    w,h=int(video.get("width",720)),int(video.get("height",1280))
    # Retain Full HD if bitrate budget permits; a long clip needs 720p
    # to keep titles clear within 48MB, but original stays untouched.
    vf=([] if base>=3_500_000 or max(w,h)<=1280 else
        ["-vf","scale=720:1280:force_original_aspect_ratio=decrease,"
                "pad=720:1280:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1,format=yuv420p"])
    for attempt,multiplier in enumerate((1.0,.78,.60)):
        bitrate=max(120000,int(base*multiplier))
        with tempfile.TemporaryDirectory(prefix="tg_pass_") as work:
            log=str(Path(work)/"stats")
            common=["ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-i",str(master),"-map","0:v:0",*vf,
                    "-c:v","libx264","-preset","veryfast",
                    "-pix_fmt","yuv420p","-b:v",str(bitrate),
                    "-passlogfile",log]
            first=subprocess.run([
                *common,"-pass","1","-an","-f","null","-"
            ],capture_output=True,text=True,timeout=1500)
            if first.returncode:
                raise RuntimeError("Не удалось подготовить Telegram-версию ролика.")
            second=[
                *common,"-pass","2",
                "-movflags","+faststart"
            ]
            if has_audio:
                second += ["-map","0:a:0","-c:a","aac","-b:a","128k","-ar","48000"]
            else:
                second += ["-an"]
            second.append(str(dest))
            run=subprocess.run(second,capture_output=True,text=True,timeout=1500)
            if run.returncode or not dest.exists():
                raise RuntimeError("Не удалось создать MP4 для Telegram.")
        if 1024<dest.stat().st_size<=max_bytes:
            LOG.info("Telegram MP4 ready: %.1f MB, attempt %d",
                     dest.stat().st_size/1_000_000,attempt+1)
            return dest
    raise RuntimeError("Не удалось уменьшить MP4 до лимита Telegram 48 МБ.")


def _vertical_geometry(file: Path) -> tuple[int,int,int]:
    """Actual encoded dimensions for Telegram's inline player metadata."""
    import math
    info=media_info(file)
    stream=next((v for v in info.get("streams",[])
                 if v.get("codec_type")=="video"),{})
    width,height=int(stream.get("width") or 0),int(stream.get("height") or 0)
    if width<360 or height<640 or abs(width/height-9/16)>.006:
        raise ValueError(
            "Telegram-копия не в 9:16. "
            f"Получено {width}x{height}, ожидаем вертикальный Reels."
        )
    duration,_=duration_and_audio(file)
    if duration<=0:
        raise ValueError("У Telegram-копии неверная длительность.")
    return width,height,max(1,math.ceil(duration))


def _telegram_thumbnail(file: Path, output: Path, duration: int) -> Path | None:
    """Attach a true vertical 9:16 preview, not Telegram's square guess."""
    command=[
        "ffmpeg","-hide_banner","-loglevel","error","-y",
        "-ss",f"{min(1.0,duration*.2):.2f}","-i",str(file),
        "-vf","scale=180:320:force_original_aspect_ratio=decrease:"
              "flags=lanczos,pad=180:320:(ow-iw)/2:(oh-ih)/2,"
              "setsar=1,format=yuvj420p",
        "-frames:v","1","-q:v","5",str(output)
    ]
    try:
        result=subprocess.run(command,capture_output=True,
                              text=True,timeout=60)
        if result.returncode==0 and output.is_file() and (
            100 < output.stat().st_size < 190000
        ):
            return output
        LOG.warning("Telegram thumbnail not available; will use metadata.")
    except (OSError,subprocess.TimeoutExpired):
        LOG.warning("Telegram thumbnail preparation unavailable.")
    return None


def send_video_to_telegram(token: str, owner: int, file: Path,
                           caption: str) -> None:
    """Send 9:16 Reels with explicit player metadata and matching thumbnail.

    Do NOT sendVideoNote: it is inherently a rounded square. If Telegram's
    player rejects the video, the standard MP4 document remains a fallback.
    """
    if file.stat().st_size>TELEGRAM_SAFE_BYTES:
        raise ValueError("Telegram-версия превышает безопасный размер 48 МБ.")
    width,height,duration=_vertical_geometry(file)
    endpoint="https://api.telegram.org/bot"+token+"/"
    with tempfile.TemporaryDirectory(prefix="tg_preview_") as work:
        thumb=_telegram_thumbnail(file,Path(work)/"reels-cover.jpg",duration)
        for method,field in (("sendVideo","video"),("sendDocument","document")):
            try:
                from contextlib import ExitStack
                with ExitStack() as stack:
                    stream=stack.enter_context(file.open("rb"))
                    values={"chat_id":str(owner),"caption":caption[:950]}
                    uploaded={field:(file.name,stream,"video/mp4")}
                    if method=="sendVideo":
                        values.update({
                            "supports_streaming":"true",
                            "width":str(width),
                            "height":str(height),
                            "duration":str(duration)
                        })
                        if thumb is not None:
                            cover=stack.enter_context(thumb.open("rb"))
                            uploaded["thumbnail"]=(
                                "reels-cover.jpg",cover,"image/jpeg"
                            )
                    reply=requests.post(
                        endpoint+method,data=values,files=uploaded,
                        timeout=(30,240)
                    )
                    body=reply.json()
                if reply.ok and body.get("ok"):
                    if method=="sendVideo":
                        telegram_video=body.get("result",{}).get("video") or {}
                        out_w=int(telegram_video.get("width") or 0)
                        out_h=int(telegram_video.get("height") or 0)
                        LOG.info("Telegram sent Reels original=%sx%s server=%sx%s",
                                 width,height,out_w,out_h)
                        if out_w and out_h and (
                            abs(out_w/out_h-9/16)>.006
                        ):
                            LOG.warning(
                                "Telegram server reported incorrect player "
                                "geometry %sx%s despite 9:16 upload.",
                                out_w,out_h
                            )
                    else:
                        LOG.info("Sent vertical MP4 as Telegram document.")
                    return
                LOG.warning("Telegram %s rejected video (%s)",method,
                            str(body.get("description",""))[:160])
            except (requests.RequestException,ValueError):
                LOG.warning("Telegram %s network failure",method)
    raise RuntimeError("Telegram не принял итоговое видео. Оригинал сохранён.")
