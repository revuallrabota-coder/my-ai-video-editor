"""Personal Telegram Mini App video editor backend.

Direct upload -> transcription review -> FFmpeg render -> authenticated download.
Single owner, one job at a time, ephemeral disk. Requires HTTPS hosting.
Never store bot token in GitHub Pages or client-side source.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from font_presets import choose_font
from reels_effects import validate_effects

LOG = logging.getLogger("mini_editor")
logging.basicConfig(level=logging.INFO)

DEFAULT_ORIGIN = "https://revuallrabota-coder.github.io"
ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ORIGINS", DEFAULT_ORIGIN).split(",")
    if origin.strip().startswith("https://")
]
app = FastAPI(title="Personal Video Editor", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["X-Telegram-Init-Data", "Content-Type"],
    expose_headers=["Content-Disposition"],
)

MAX_FILE_MB = max(10, min(300, int(os.getenv("MAX_FILE_MB", "50"))))
MAX_BYTES = MAX_FILE_MB * 1024 * 1024
MAX_VIDEO_SECONDS = 125
TTL_SECONDS = 2 * 60 * 60
LOCK = threading.RLock()


@dataclass
class Job:
    ident: str
    folder: Path
    settings: dict
    status: str = "queued"
    message: str = "Подготавливаем видео"
    transcript: str = ""
    words: list[tuple[float, float, str]] = field(default_factory=list)
    output: Path | None = None
    created: float = field(default_factory=time.monotonic)
    input_duration: float = 0.0
    error: str = ""
    owner: int = 0

JOBS: dict[str, Job] = {}


def authenticated_user(init_data: str | None) -> int:
    """Telegram documented Mini App initData HMAC verification (not Unsafe)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    owner_id = os.getenv("OWNER_TELEGRAM_ID", "")
    if not token or not owner_id:
        raise HTTPException(503, "Сервер не настроен: проверь защищённые переменные.")
    if not init_data or len(init_data) > 12000:
        raise HTTPException(401, "Открой приложение из меню своего Telegram-бота.")
    params = dict(parse_qsl(init_data, keep_blank_values=True))
    supplied_hash = params.pop("hash", "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", supplied_hash):
        raise HTTPException(401, "Telegram-подпись отсутствует.")
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(params.items())
    )
    secret = hmac.new(
        b"WebAppData", token.encode("utf-8"), hashlib.sha256
    ).digest()
    expected = hmac.new(
        secret, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, supplied_hash.lower()):
        raise HTTPException(401, "Подпись Telegram не совпадает.")
    try:
        issued = int(params["auth_date"])
        user_id = int(json.loads(params["user"])["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(401, "Telegram-данные неполные.") from None
    if abs(time.time()-issued) > 86400:
        raise HTTPException(401, "Открой Mini App заново через Telegram.")
    if user_id != int(owner_id):
        raise HTTPException(403, "Монтаж разрешён только владельцу бота.")
    return user_id


def cleanup() -> None:
    cutoff = time.monotonic() - TTL_SECONDS
    for ident, job in list(JOBS.items()):
        if job.created < cutoff and job.status in ("done", "error", "needs_review"):
            JOBS.pop(ident, None)
            shutil.rmtree(job.folder, ignore_errors=True)


def get_job(ident: str, owner: int) -> Job:
    with LOCK:
        cleanup()
        job = JOBS.get(ident)
        if job is None or job.owner != owner:
            raise HTTPException(404, "Задание не найдено или удалено.")
        return job


def validate_settings(config: dict) -> dict:
    def option(name, allowed, default):
        value = str(config.get(name, default))
        if value not in allowed:
            raise HTTPException(400, f"Недопустимая настройка: {name}")
        return value

    mode = option("mode", {"my_style","auto","captions","cuts","reference"}, "my_style")
    style = option(
        "subtitle_style",
        {"reference_dynamic","signature","contrast","classic",
         "signature_phrases","contrast_phrases","classic_phrases"},
        "reference_dynamic",
    )
    font = option("font_profile", {
        "elegant","clean","bold","bebas","platform","bubble","script","modern","old_money","vintage","street","refined","roboto","open_sans","noto_sans","ubuntu","carlito","lato_black","modern_condensed",
    }, "old_money")
    choose_font(font)
    small_font = option("small_font_profile",{
        "elegant","clean","bold","bebas","platform","bubble","script","modern","old_money","vintage","street","refined","roboto","open_sans","noto_sans","ubuntu","carlito","lato_black","modern_condensed",
    },"refined")
    choose_font(small_font)
    caption_variant=option("caption_variant",{
        "reference_soft","editorial","luxe","minimal","neon","pop","old_money","vintage","street","elegant"
    },"reference_soft")
    background_style=option("background_style",{
        "off","occasional","frequent","always"
    },"occasional")
    animation_style=option("animation_style",{
        "float","pop","slide"
    },"float")
    subtitle_sfx=option("subtitle_sfx",{
        "off","soft","tick"
    },"soft")
    retro_default=caption_variant
    insert_style=option("insert_style",{
        "off","retro","old_money","vintage","elegant","street",
        "editorial","minimal","neon","pop","luxe","reference_soft"
    },"reference_soft")
    insert_density=option("insert_density",{
        "subtle","balanced","dynamic"
    },"balanced")
    insert_sound=option("insert_sound",{"on","off"},"off")
    color = str(config.get("color", "auto"))
    if color != "auto" and not re.fullmatch(r"#[a-fA-F0-9]{6}", color):
        raise HTTPException(400, "Цвет должен быть auto или #RRGGBB")
    try:
        speed = float(config.get("speed", 1.0))
    except (TypeError, ValueError):
        raise HTTPException(400, "Неверная скорость.") from None
    if not 0.8 <= speed <= 1.5:
        raise HTTPException(400, "Скорость должна быть между 0.8 и 1.5.")
    try:
        subtitle_delay = float(config.get("subtitle_delay", 0.30))
    except (TypeError, ValueError):
        raise HTTPException(400, "Неверная синхронизация субтитров.") from None
    if not -0.5 <= subtitle_delay <= 1.5:
        raise HTTPException(400, "Сдвиг титров от -0.5 до +1.5 секунды.")
    hook_text = str(config.get("hook", "")).strip()[:58]
    sound = option("sound_effects", {"off","soft","punch"}, "off")
    emoji = option("emoji_mode", {"off","on"}, "off")
    hook_position = option("hook_position", {"start","end","both","off"}, "start")
    validate_effects(sound, emoji, hook_position)
    return {
        "mode": mode, "subtitle_style": style, "font_profile": font,
        "small_font_profile":small_font,"caption_variant":caption_variant,
        "background_style":background_style,"animation_style":animation_style,
        "subtitle_sfx":subtitle_sfx,
        "insert_style":insert_style,
        "insert_density":insert_density,
        "insert_sound":insert_sound,
        "color": color, "speed": speed,
        "filter_style": option("filter_style", {
            "none","warm","soft","cool","contrast","clean","film","matte","old_money","vintage","street","elegant",
        }, "none"),
        "camera_style": option("camera_style", {
            "cinematic_pan","editorial","enhanced","soft_punch","gentle","off",
        }, "cinematic_pan"),
        "audio_profile": option("audio_profile", {
            "balanced","strong","off",
        }, "balanced"),
        "caption_position": option("caption_position", {
            "top","middle","bottom",
        }, "middle"),
        "hook": hook_text,
        "subtitle_delay": subtitle_delay,
        "export_quality": option("export_quality", {"high","balanced"}, "high"),
        "sound_effects": sound,
        "emoji_mode": emoji,
        "hook_position": hook_position,
    }


def set_status(job: Job, status: str, message: str = "") -> None:
    with LOCK:
        job.status = status
        if message:
            job.message = message


def recognize(job: Job) -> None:
    try:
        from telegram_editor import duration_and_audio, transcribe_words
        source = job.folder / "original.mp4"
        duration, audio = duration_and_audio(source)
        if not 0 < duration <= MAX_VIDEO_SECONDS:
            raise ValueError("Видео должно быть не длиннее 2 минут.")
        job.input_duration = duration
        if job.settings["mode"] == "reference":
            reference = job.folder / "reference.mp4"
            ref_duration, _ = duration_and_audio(reference)
            if not 0 < ref_duration <= MAX_VIDEO_SECONDS:
                raise ValueError("Референс должен быть до 2 минут.")
        if not audio and job.settings["mode"] != "cuts":
            raise ValueError("В исходнике нет звуковой дорожки.")
        if job.settings["mode"] == "cuts":
            render(job, [])
            return
        set_status(job, "transcribing", "Распознаю речь для проверки текста")
        # tiny for 512MB RAM demo; small/medium require more memory.
        model = os.getenv("RECOGNITION_MODEL", "tiny")
        language = os.getenv("SPEECH_LANGUAGE", "ru")
        words = transcribe_words(source, model_size=model, language=language)
        with LOCK:
            job.words = words
            job.transcript = " ".join(w[2] for w in words).strip()
        set_status(job, "needs_review", "Проверь слова, затем нажми «Продолжить монтаж»")
    except Exception as exc:
        LOG.exception("Transcription failed")
        job.error = str(exc)[:450]
        set_status(job, "error", "Не получилось разобрать видео")


def render(job: Job, words: list[tuple[float, float, str]]) -> None:
    set_status(job, "rendering", "Накладываю субтитры, звук и анимации")
    s = job.settings
    mode = s["mode"]
    style = s["subtitle_style"]
    animation = "phrase_float" if style.endswith("_phrases") else "word_pop"
    style = style.removesuffix("_phrases")
    source = job.folder / "original.mp4"
    output = job.folder / "ready.mp4"
    try:
        if mode in ("my_style","reference"):
            from reference_editor import montage_by_reference
            result = montage_by_reference(
                source,
                job.folder / "reference.mp4" if mode=="reference" else None,
                output, s["color"], s["audio_profile"], style, s["hook"],
                s["camera_style"], s["speed"], s["filter_style"],
                s["caption_position"], s["font_profile"],
                words_override=words, caption_animation=animation,
                sound_effects=s["sound_effects"], emoji_mode=s["emoji_mode"],
                hook_position=s["hook_position"],
                quality=s["export_quality"],
                subtitle_delay=s["subtitle_delay"],
                small_font_profile=s["small_font_profile"],
                caption_variant=s["caption_variant"],
                background_style=s["background_style"],
                animation_style=s["animation_style"],
                subtitle_sfx=s["subtitle_sfx"],
                insert_style=s["insert_style"],
                insert_density=s["insert_density"],
                insert_sound=s["insert_sound"],
            )
        else:
            from telegram_editor import edit_video
            result = edit_video(
                source, output, mode, s["color"], s["audio_profile"],
                style, s["hook"], s["speed"], s["filter_style"],
                s["caption_position"], s["font_profile"], words,
                animation, s["sound_effects"], s["emoji_mode"],
                s["hook_position"],
                s["export_quality"], s["subtitle_delay"],
                s["small_font_profile"], s["caption_variant"],
                s["background_style"], s["animation_style"], s["subtitle_sfx"],
                s["insert_style"],s["insert_density"],s["insert_sound"],
            )
        if not output.is_file() or output.stat().st_size < 100:
            raise RuntimeError("Обработчик не создал готовый MP4.")
        with LOCK:
            job.output = output
        set_status(job, "done", "Видео готово! Можно скачать MP4.")
        LOG.info("Finished job %s: %s", job.ident, result)
    except Exception as exc:
        LOG.exception("Render failed")
        job.error = str(exc)[:450]
        set_status(job, "error", "Монтаж не завершён")


def save_upload(upload: UploadFile, path: Path) -> None:
    if not upload.filename or not upload.filename.lower().endswith(
        (".mp4",".mov",".m4v",".webm",".mkv")
    ):
        raise HTTPException(400, "Выбери видеофайл MP4 или MOV.")
    amount = 0
    with path.open("wb") as target:
        while True:
            chunk = upload.file.read(4 * 1024 * 1024)
            if not chunk:
                break
            amount += len(chunk)
            if amount > MAX_BYTES:
                raise HTTPException(413, f"Максимальный размер файла: {MAX_FILE_MB} МБ.")
            target.write(chunk)
    if amount == 0:
        raise HTTPException(400, "Видео пустое.")


class ReviewRequest(BaseModel):
    confirmed: bool = False
    corrected_text: str = Field("", max_length=6000)


@app.get("/api/health")
def health():
    return {"status": "online", "upload_limit_mb": MAX_FILE_MB}


@app.post("/api/jobs")
def submit(
    video: UploadFile = File(...),
    settings: str = Form(...),
    reference: UploadFile | None = File(None),
    x_telegram_init_data: str | None = Header(None),
):
    owner = authenticated_user(x_telegram_init_data)
    try:
        parsed = json.loads(settings)
    except json.JSONDecodeError:
        raise HTTPException(400, "Неверные настройки.") from None
    if not isinstance(parsed, dict):
        raise HTTPException(400, "Настройки должны быть объектом.")
    config = validate_settings(parsed)
    with LOCK:
        cleanup()
        if any(j.status in ("queued","transcribing","rendering","needs_review")
               for j in JOBS.values()):
            raise HTTPException(409, "Сначала заверши уже начатый монтаж.")
        folder = Path(tempfile.mkdtemp(prefix="mini_editor_"))
        ident = uuid.uuid4().hex
        job = Job(ident=ident, folder=folder, settings=config, owner=owner)
        JOBS[ident] = job
    try:
        save_upload(video, folder / "original.mp4")
        if config["mode"] == "reference":
            if reference is None:
                raise HTTPException(400, "Для этого режима прикрепи референс.")
            save_upload(reference, folder / "reference.mp4")
        set_status(job, "queued", "Файл получен, начинаю анализ")
        threading.Thread(target=recognize, args=(job,), daemon=True).start()
        return {"job_id": ident, "status": "queued"}
    except Exception:
        with LOCK:
            JOBS.pop(ident, None)
        shutil.rmtree(folder, ignore_errors=True)
        raise


@app.get("/api/jobs/{ident}")
def status(ident: str, x_telegram_init_data: str | None = Header(None)):
    owner = authenticated_user(x_telegram_init_data)
    job = get_job(ident, owner)
    return {
        "job_id": ident, "status": job.status,
        "message": job.message, "transcript": job.transcript if job.status=="needs_review" else "",
        "error": job.error if job.status=="error" else "",
    }


@app.post("/api/jobs/{ident}/review")
def approve(ident: str, body: ReviewRequest,
            x_telegram_init_data: str | None = Header(None)):
    owner = authenticated_user(x_telegram_init_data)
    job = get_job(ident, owner)
    with LOCK:
        if job.status != "needs_review":
            raise HTTPException(409, "Сейчас текст подтверждать нельзя.")
        words = list(job.words)
        if not body.confirmed:
            corrected = body.corrected_text.strip()
            if not corrected:
                raise HTTPException(400, "Напиши правильный текст.")
            from speech_review import align_corrected_words
            words = align_corrected_words(words, corrected, job.input_duration)
        job.status = "rendering"
        job.message = "Начинаю финальную обработку"
    threading.Thread(target=render, args=(job,words), daemon=True).start()
    return {"job_id": ident, "status": "rendering"}


@app.get("/api/jobs/{ident}/download")
def download(ident: str, x_telegram_init_data: str | None = Header(None)):
    owner = authenticated_user(x_telegram_init_data)
    job = get_job(ident, owner)
    if job.status != "done" or job.output is None or not job.output.is_file():
        raise HTTPException(409, "Готового видео пока нет.")
    return FileResponse(
        job.output, media_type="video/mp4", filename="my-edited-reels.mp4",
    )
