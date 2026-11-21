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


def send_video_to_telegram(token: str, owner: int, file: Path,
                           caption: str) -> None:
    """Send playable video first, fallback to a normal document if rejected."""
    if file.stat().st_size>TELEGRAM_SAFE_BYTES:
        raise ValueError("Telegram-версия превышает безопасный размер 48 МБ.")
    endpoint="https://api.telegram.org/bot"+token+"/"
    for method,field in (("sendVideo","video"),("sendDocument","document")):
        try:
            with file.open("rb") as stream:
                values={"chat_id":str(owner),"caption":caption[:950]}
                if method=="sendVideo":
                    values["supports_streaming"]="true"
                reply=requests.post(
                    endpoint+method,data=values,
                    files={field:(file.name,stream,"video/mp4")},timeout=(30,240)
                )
                body=reply.json()
            if reply.ok and body.get("ok"):
                LOG.info("Sent playable Reels to Telegram by %s",method)
                return
            LOG.warning("Telegram %s rejected video (%s)",method,
                        str(body.get("description",""))[:160])
        except (requests.RequestException,ValueError):
            LOG.warning("Telegram %s network failure",method)
    raise RuntimeError("Telegram не принял итоговое видео. Оригинал не потерян.")
