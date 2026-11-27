"""Combine ordered original clips into a single speech-synchronized Reels timeline.

Normalize mismatched codec/resolution/frame rate/audio layouts independently,
then stream-copy the compatible segments together. Captions and motion graphics
are applied ONCE on this joined result, not separately to each source clip.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Sequence

from telegram_editor import duration_and_audio

LOG = logging.getLogger("clip_montage")
MAX_CLIPS = 12
MAX_SECONDS = 600.0


def join_clips(
    clips: Sequence[Path],
    target: Path,
    quality: str = "high",
) -> tuple[float, bool]:
    """Return (duration, at_least_one_source_has_audio).

    Never silently drop speech or trim clips. Refuse projects longer than the
    ten-minute project limit rather than losing requested footage.
    """
    if not 1 <= len(clips) <= MAX_CLIPS:
        raise ValueError("В одном проекте поддерживается от 1 до 12 видео.")
    if quality not in ("high", "balanced"):
        raise ValueError("Неизвестное качество монтажа.")
    durations=[]
    original_audio=[]
    for clip in clips:
        if not clip.is_file() or clip.stat().st_size < 4096:
            raise ValueError("Один из исходных видеофайлов отсутствует или пуст.")
        seconds, audio = duration_and_audio(clip)
        durations.append(seconds)
        original_audio.append(audio)
    total=sum(durations)
    if total>MAX_SECONDS:
        raise ValueError(
            "Общая продолжительность всех видео больше десяти минут. "
            "Выбери более короткие фрагменты: монтаж не должен обрезать твою речь."
        )
    if len(clips)==1:
        # No additional quality degradation for a single source.
        import shutil
        shutil.copyfile(clips[0], target)
        return total, original_audio[0]

    # Frame sizes must match before concat; portrait sources fill the canvas,
    # landscape sources get neutral letterboxing instead of warped faces.
    width,height=(1080,1920) if quality=="high" else (720,1280)
    vf=(
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        "setsar=1,fps=30,format=yuv420p"
    )
    target.parent.mkdir(parents=True,exist_ok=True)
    prepared=[]
    for i,(clip,audio) in enumerate(zip(clips,original_audio)):
        intermediate=target.parent/f"prepared_{i:02d}.mp4"
        args=["ffmpeg","-hide_banner","-loglevel","error","-y",
              "-i",str(clip)]
        if not audio:
            args+=["-f","lavfi","-i","anullsrc=r=48000:cl=stereo"]
        args+=["-map","0:v:0","-map",("0:a:0" if audio else "1:a:0"),
               "-vf",vf,"-af","apad",
               "-c:v","libx264","-preset","veryfast","-crf","18",
               "-pix_fmt","yuv420p","-r","30",
               "-c:a","aac","-b:a","160k","-ar","48000","-ac","2",
               "-shortest","-movflags","+faststart",str(intermediate)]
        LOG.info("Normalizing selected clip %d/%d",i+1,len(clips))
        run=subprocess.run(args,capture_output=True,text=True,timeout=1500)
        if run.returncode!=0:
            raise RuntimeError(
                "Не удалось привести исходное видео №"+
                str(i+1)+" к общему формату. Проверь файл MP4/MOV."
            )
        prepared.append(intermediate)

    manifest=target.parent/"ordered_concat.txt"
    manifest.write_text(
        "".join("file '"+str(p.resolve()).replace("'","'\\''")+"'\n"
                for p in prepared),encoding="utf-8"
    )
    run=subprocess.run([
        "ffmpeg","-hide_banner","-loglevel","error","-y",
        "-f","concat","-safe","0","-i",str(manifest),
        "-map","0:v:0","-map","0:a:0",
        "-c","copy","-movflags","+faststart",str(target)
    ],capture_output=True,text=True,timeout=900)
    if run.returncode!=0 or not target.is_file() or target.stat().st_size<4096:
        raise RuntimeError("Не удалось соединить исходные видео в один MP4.")
    seconds,has_audio=duration_and_audio(target)
    if seconds>MAX_SECONDS+0.001:
        raise ValueError("После соединения длительность превысила десять минут.")
    return seconds, any(original_audio)
