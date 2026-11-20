"""Первый тест видеомонтажа без api_id и api_hash.

Запускается вручную в GitHub Actions, использует только обычный Telegram
Bot API и уже созданные TELEGRAM_BOT_TOKEN и OWNER_TELEGRAM_ID.

ОГРАНИЧЕНИЕ: Telegram getFile скачивает не более 20 MB. Для 1 GB
понадобится независимая загрузка через Mini App и собственное хранилище.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

import requests

# Общая функция монтажа. Не требует авторизации MTProto.
from telegram_editor import edit_video, audio_filterchain
from reference_editor import montage_by_reference

LOG = logging.getLogger("bot_api_editor")
API_ROOT = "https://api.telegram.org/bot"
FILE_ROOT = "https://api.telegram.org/file/bot"
MAX_FILE_BYTES = 20_000_000
MAX_REPLY_BYTES = 48_000_000
WAIT_SECONDS = 900


def call_api(token: str, method: str, data: dict | None = None, *, timeout: int = 40) -> dict:
    try:
        response = requests.post(
            API_ROOT + token + "/" + method,
            data=data or {},
            timeout=timeout,
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as err:
        raise RuntimeError("Не удалось соединиться с Telegram Bot API.") from None
    if not response.ok or not payload.get("ok"):
        desc = str(payload.get("description", ""))
        if "webhook" in desc.lower():
            raise RuntimeError(
                "У бота включён webhook. Эта тестовая версия работает "
                "через getUpdates; отключать действующий webhook автоматически нельзя."
            )
        raise RuntimeError("Telegram отклонил запрос " + method + ".")
    return payload["result"]


def send_text(token: str, chat_id: int, text: str) -> None:
    call_api(token, "sendMessage", {"chat_id": chat_id, "text": text})


def download_video(token: str, file_id: str, path: Path) -> None:
    file_meta = call_api(token, "getFile", {"file_id": file_id})
    file_path = file_meta.get("file_path")
    if not file_path:
        raise RuntimeError("Telegram не вернул путь к видео.")
    try:
        with requests.get(
            FILE_ROOT + token + "/" + file_path,
            stream=True, timeout=(15, 120)
        ) as response:
            if not response.ok:
                raise RuntimeError("Не удалось скачать видео из Telegram.")
            count = 0
            with path.open("wb") as dst:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    count += len(chunk)
                    if count > MAX_FILE_BYTES:
                        raise ValueError("Файл слишком большой для стандартного Telegram Bot API (максимум 20 МБ).")
                    dst.write(chunk)
    except requests.RequestException:
        raise RuntimeError("Ошибка при скачивании файла из Telegram.") from None


def send_result(token: str, chat_id: int, result: Path, caption: str) -> None:
    if result.stat().st_size > MAX_REPLY_BYTES:
        raise RuntimeError(
            "Смонтированный файл получился больше лимита отправки Telegram "
            "(около 50 МБ). В следующей версии добавим отдельную загрузку."
        )
    try:
        with result.open("rb") as stream:
            resp = requests.post(
                API_ROOT + token + "/sendDocument",
                data={"chat_id": chat_id, "caption": caption + "\n📁 Исходное качество MP4."},
                files={"document": (result.name, stream, "video/mp4")},
                timeout=(30, 180),
            )
            payload = resp.json()
        if not resp.ok or not payload.get("ok"):
            raise RuntimeError("Telegram не принял готовое видео.")
    except (requests.RequestException, ValueError):
        raise RuntimeError("Не удалось передать готовое видео обратно в Telegram.") from None


def select_video(message: dict) -> dict | None:
    video = message.get("video")
    if video:
        return video
    doc = message.get("document")
    if not doc:
        return None
    name = str(doc.get("file_name", "")).lower()
    if str(doc.get("mime_type", "")).startswith("video/") or name.endswith((".mp4", ".mov", ".m4v")):
        return doc
    return None


def render_result(
    token: str, chat_id: int, original_file: Path, reference_file: Path,
    output_file: Path, *, mode: str, color: str, audio_profile: str,
    subtitle_style: str, hook: str, camera_style: str, speed: float,
    filter_style: str, caption_position: str, font_profile: str,
    reviewed_words: list[tuple[float, float, str]] | None,
    caption_animation: str = "word_pop",
    sound_effects: str = "off",
    emoji_mode: str = "off",
    hook_position: str = "start",
    quality: str = "high",
    subtitle_delay: float = 0.30,
) -> None:
    """Рендер только из одобренной версии текста."""
    try:
        if mode in ("reference", "my_style"):
            details = montage_by_reference(
                original_file,
                reference_file if mode == "reference" else None,
                output_file, color, audio_profile, subtitle_style, hook,
                camera_style, speed, filter_style,
                caption_position, font_profile,
                words_override=reviewed_words,
                caption_animation=caption_animation,
                sound_effects=sound_effects, emoji_mode=emoji_mode,
                hook_position=hook_position, quality=quality,
                subtitle_delay=subtitle_delay,
            )
            caption = (
                "🎬 Монтаж готов! "
                f"Длительность: {details['before']} → {details['after']} сек.\n"
                "Голос сохранён, субтитры из подтверждённого текста."
            )
        else:
            details = edit_video(
                original_file, output_file, mode, color, audio_profile,
                subtitle_style, hook, speed, filter_style,
                caption_position, font_profile, reviewed_words,
                caption_animation, sound_effects, emoji_mode, hook_position,
                quality, subtitle_delay,
            )
            caption = (
                "✅ Готово! "
                f"Длительность: {details['before']} → {details['after']} сек.\n"
                "Субтитры из подтверждённого текста."
            )
        caption += (
            "\n✨ Эмодзи: " + str(details.get("emoji_count", 0))
            + " · 🔊 Акцентов: " + str(details.get("sfx_count", 0))
            + (" · 🪧 Хук добавлен" if hook and hook_position != "off" else "")
        )
        send_result(token, chat_id, output_file, caption)
        LOG.info("Готовое видео отправлено")
    except ValueError as err:
        send_text(token, chat_id, "⚠️ " + str(err)[:300])
        LOG.warning("Ошибка исходника/настроек: %s", err)
    except Exception:
        LOG.exception("Не удалось выполнить монтаж")
        send_text(
            token, chat_id,
            "⚠️ Не удалось смонтировать ролик. Проверь журнал "
            "«Запустить тестовый монтаж» в GitHub Actions."
        )


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    owner = os.environ.get("OWNER_TELEGRAM_ID")
    if not token or not owner:
        raise RuntimeError(
            "Не хватает двух защищённых настроек GitHub: "
            "TELEGRAM_BOT_TOKEN и OWNER_TELEGRAM_ID."
        )
    try:
        owner_id = int(owner.strip())
    except ValueError:
        raise RuntimeError("OWNER_TELEGRAM_ID должен быть числом.") from None

    mode = os.environ.get("MONTAGE_MODE", "auto")
    color = os.environ.get("SUBTITLE_COLOR", "auto")
    audio_profile = os.environ.get("AUDIO_PROFILE", "balanced")
    audio_filterchain(audio_profile)  # early validation
    selected_subtitle_style = os.environ.get("SUBTITLE_STYLE", "signature")
    # GitHub Actions ограничивает число отдельных полей формы.
    # Одна настройка выбирает и палитру, и способ появления текста.
    caption_animation = (
        "phrase_float" if selected_subtitle_style.endswith("_phrases")
        else "word_pop"
    )
    subtitle_style = selected_subtitle_style.removesuffix("_phrases")
    if subtitle_style not in ("signature", "classic", "contrast", "reference_dynamic"):
        raise ValueError("Неизвестный стиль субтитров.")
    hook = os.environ.get("HOOK_TEXT", "").strip()[:70]
    hook_position = "start"
    sound_effects = "soft" if mode in ("my_style", "reference") else "off"
    emoji_mode = "on" if mode in ("my_style", "reference") else "off"
    camera_style = os.environ.get("CAMERA_STYLE", "cinematic_pan")
    if camera_style not in ("cinematic_pan", "editorial", "enhanced", "soft_punch", "gentle", "off"):
        raise ValueError("Неверный режим камеры.")
    try:
        speed = float(os.environ.get("VIDEO_SPEED", "1.0"))
    except ValueError:
        raise ValueError("Скорость видео должна быть числом.") from None
    if not 0.8 <= speed <= 1.5:
        raise ValueError("Допустимая скорость: от 0.8 до 1.5.")
    subtitle_delay = float(os.environ.get("SUBTITLE_DELAY", "0.30"))
    if not -0.5 <= subtitle_delay <= 1.5:
        raise ValueError("SUBTITLE_DELAY от -0.5 до +1.5 сек.")
    quality = os.environ.get("EXPORT_QUALITY", "high")
    from export_profiles import get_export_profile
    get_export_profile(quality)
    filter_style = os.environ.get("VIDEO_FILTER", "none")
    caption_position = os.environ.get("CAPTION_POSITION", "middle")
    font_profile = os.environ.get("FONT_PROFILE", "elegant")
    if caption_position not in ("top", "middle", "bottom"):
        raise ValueError("Недопустимое положение субтитров.")
    from font_presets import choose_font
    choose_font(font_profile)  # Проверка существования выбранного шрифта
    if filter_style not in ("none", "warm"):
        raise ValueError("Неизвестный фильтр видео.")
    if mode not in ("auto", "captions", "cuts", "reference", "my_style"):
        raise RuntimeError("Неизвестный режим обработки.")

    # Старые сообщения не используем. Отправляй файлы только после приглашения.
    recent = call_api(token, "getUpdates", {"offset": -1, "limit": 1, "timeout": 0})
    offset = recent[-1]["update_id"] + 1 if recent else None
    if mode == "my_style":
        prompt = (
            "💗 Режим «Мой стиль» запущен!\n"
            "Пришли ОДНО новое исходное видео до 20 МБ и 2 минут.\n"
            "Я сделаю смену крупности и анимированные субтитры "
            "и улучшу звучание твоей речи. Референс повторно присылать не нужно."
        )
    elif mode == "reference":
        prompt = (
            "🎬 Режим «По референсу» запущен!\n\n"
            "Шаг 1 из 2: пришли СЕЙЧАС видео-референс до 20 МБ "
            "и длительностью до 2 минут.\n"
            "После подтверждения пришли своё исходное видео (тоже до 20 МБ).\n"
            "Из референса берём темп смены кадров, а не копируем все эффекты 1:1."
        )
    else:
        prompt = (
            "🎬 Монтажёр запущен!\n"
            "Пришли СЕЙЧАС одно новое видео длительностью до 2 минут "
            "и размером до 20 МБ.\n"
            "api_id и api_hash не нужны."
        )
    prompt += (
        "\n\n✨ Новые эффекты: /effects — посмотреть настройки."
        "\n/sfx off|soft|punch — звуковые акценты."
        "\n/emoji on|off — всплывающие эмодзи."
        "\n/hook start ТЕКСТ — хук в начале на подложке."
        "\n/hook end ТЕКСТ — хук в конце."
        "\n/hook both ТЕКСТ — хук и там, и там."
        "\n/hook off — выключить."
        "\n/sync 0.4 — задержать титры; /sync 0 — без задержки."
    )
    send_text(token, owner_id, prompt)
    LOG.info("Ожидаем входящие видео от владельца, режим=%s, максимум 15 минут.", mode)

    # Сохраняем reference.mp4 между первым и вторым сообщением только
    # во временной директории работающего GitHub Actions runner.
    with tempfile.TemporaryDirectory(prefix="montage_") as tmp:
        folder = Path(tmp)
        reference_file = folder / "reference.mp4"
        original_file = folder / "original.mp4"
        output_file = folder / "ready.mp4"
        has_reference = False
        pending_words = None
        pending_chat_id = None

        end = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < end:
            remaining = max(1, int(end - time.monotonic()))
            data = {
                "limit": 20,
                "timeout": min(20, remaining),
                "allowed_updates": '["message"]',
            }
            if offset is not None:
                data["offset"] = offset
            updates = call_api(token, "getUpdates", data, timeout=45)
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                sender = message.get("from", {}).get("id")
                chat = message.get("chat", {})
                if sender != owner_id or chat.get("type") != "private":
                    continue

                chat_id = chat["id"]
                raw_text = str(message.get("text", "")).strip()
                if raw_text == "/help":
                    send_text(token, chat_id, prompt)
                    continue

                # Управление эффектами внутри Telegram. Не требует
                # дополнительных полей GitHub Actions (их лимит — 10).
                low = raw_text.lower()
                if low == "/effects":
                    send_text(
                        token, chat_id,
                        "🎛 Эффекты текущего ролика:\n"
                        f"Звуковые акценты: {sound_effects}\n"
                        f"Эмодзи: {emoji_mode}\n"
                        f"Хук: {hook_position} ({hook or 'текст не задан'})\n\n"
                        "Команды:\n"
                        "/sfx soft | /sfx punch | /sfx off\n"
                        "/emoji on | /emoji off\n"
                        "/hook start ТЕКСТ\n"
                        "/hook end ТЕКСТ\n"
                        "/hook both ТЕКСТ\n"
                        "/hook off"
                    )
                    continue
                if low.startswith("/sfx"):
                    parts=low.split()
                    if len(parts)!=2 or parts[1] not in ("off","soft","punch"):
                        send_text(token,chat_id,"Выбери: /sfx off, /sfx soft или /sfx punch")
                    else:
                        sound_effects=parts[1]
                        send_text(token,chat_id,f"🔊 Звуковые акценты: {sound_effects}")
                    continue
                if low.startswith("/emoji"):
                    parts=low.split()
                    if len(parts)!=2 or parts[1] not in ("on","off"):
                        send_text(token,chat_id,"Выбери: /emoji on или /emoji off")
                    else:
                        emoji_mode=parts[1]
                        send_text(token,chat_id,f"✨ Эмодзи: {emoji_mode}")
                    continue
                if low.startswith("/hook"):
                    parts=raw_text.split(maxsplit=2)
                    if len(parts)==2 and parts[1].lower()=="off":
                        hook=""
                        hook_position="off"
                        send_text(token,chat_id,"Хук выключен.")
                    elif (len(parts)==3 and parts[1].lower() in ("start","end","both")
                          and parts[2].strip()):
                        hook_position=parts[1].lower()
                        hook=parts[2].strip()[:58]
                        send_text(
                            token,chat_id,
                            "🪧 Хук установлен: "
                            + ("в начале" if hook_position=="start" else
                               "в конце" if hook_position=="end" else "в начале и конце")
                            + "\n" + hook
                        )
                    else:
                        send_text(
                            token,chat_id,
                            "Формат: /hook start ТЕКСТ, /hook end ТЕКСТ, "
                            "/hook both ТЕКСТ или /hook off"
                        )
                    continue

                if low.startswith("/sync"):
                    parts = low.split()
                    if len(parts) != 2:
                        send_text(token, chat_id, "Пример: /sync 0.4 — титры позже речи; /sync 0 — без задержки.")
                        continue
                    try:
                        value = float(parts[1].replace(",", "."))
                        if not -0.5 <= value <= 1.5:
                            raise ValueError()
                        subtitle_delay = value
                    except ValueError:
                        send_text(token, chat_id, "Укажи число от -0.5 до 1.5: /sync 0.4")
                        continue
                    send_text(token, chat_id, f"⏱ Сдвиг субтитров: {subtitle_delay:+.2f} сек.")
                    continue

                if pending_words is not None and pending_chat_id == chat_id:
                    if raw_text.lower() == "/ok":
                        reviewed_words = pending_words
                    elif raw_text.lower().startswith("/fix "):
                        from speech_review import apply_word_fixes
                        try:
                            reviewed_words = apply_word_fixes(
                                pending_words, raw_text[5:].strip()
                            )
                        except ValueError as err:
                            send_text(token, chat_id, "⚠️ " + str(err))
                            continue
                    elif raw_text.lower().startswith("/text "):
                        from speech_review import align_corrected_words
                        from telegram_editor import duration_and_audio
                        seconds, _ = duration_and_audio(original_file)
                        try:
                            reviewed_words = align_corrected_words(
                                pending_words, raw_text[6:].strip(), seconds
                            )
                        except ValueError as err:
                            send_text(token, chat_id, "⚠️ " + str(err))
                            continue
                    else:
                        if raw_text:
                            send_text(
                                token, chat_id,
                                "Ответь /ok, /fix ошибка=верно или "
                                "/text ПОЛНЫЙ ПРАВИЛЬНЫЙ ТЕКСТ"
                            )
                        continue
                    send_text(token, chat_id, "✅ Текст принят. Монтирую видео…")
                    render_result(
                        token, chat_id, original_file, reference_file,
                        output_file, mode=mode, color=color,
                        audio_profile=audio_profile, subtitle_style=subtitle_style,
                        hook=hook, camera_style=camera_style, speed=speed,
                        filter_style=filter_style, caption_position=caption_position,
                        font_profile=font_profile, reviewed_words=reviewed_words,
                        caption_animation=caption_animation,
                        sound_effects=sound_effects, emoji_mode=emoji_mode,
                        hook_position=hook_position, quality=quality,
                        subtitle_delay=subtitle_delay,
                    )
                    return

                media = select_video(message)
                if media is None:
                    continue
                size = media.get("file_size", 0)
                if size and size > MAX_FILE_BYTES:
                    send_text(
                        token, chat_id,
                        "⚠️ Этот файл больше 20 МБ. Пока Telegram Bot API "
                        "не может скачать такое видео. Пришли сжатую копию до 20 МБ."
                    )
                    continue

                if mode == "reference" and not has_reference:
                    try:
                        send_text(token, chat_id, "📥 Получаю видео-пример и проверяю формат…")
                        download_video(token, media["file_id"], reference_file)
                        # Проверяем длительность и наличие видеодорожки заранее.
                        from telegram_editor import duration_and_audio
                        duration_and_audio(reference_file)
                        has_reference = True
                        send_text(
                            token, chat_id,
                            "✅ Референс принят!\n\n"
                            "Шаг 2 из 2: теперь пришли СВОЁ исходное видео "
                            "до 20 МБ и до 2 минут.\n"
                            "Я сохраню твой голос и применю к видео ритм референса."
                        )
                        LOG.info("Референс получен и проверен.")
                    except ValueError as err:
                        reference_file.unlink(missing_ok=True)
                        send_text(token, chat_id, "⚠️ " + str(err)[:300])
                    except Exception:
                        reference_file.unlink(missing_ok=True)
                        LOG.exception("Ошибка загрузки референса")
                        send_text(token, chat_id, "⚠️ Не удалось прочитать референс. Пришли другой файл MP4/MOV.")
                    continue

                # До рендера показываем настоящую расшифровку речи.
                try:
                    download_video(token, media["file_id"], original_file)
                    if mode == "cuts":
                        render_result(
                            token, chat_id, original_file, reference_file,
                            output_file, mode=mode, color=color,
                            audio_profile=audio_profile, subtitle_style=subtitle_style,
                            hook=hook, camera_style=camera_style, speed=speed,
                            filter_style=filter_style, caption_position=caption_position,
                            font_profile=font_profile, reviewed_words=None,
                            caption_animation=caption_animation,
                            sound_effects=sound_effects, emoji_mode=emoji_mode,
                            hook_position=hook_position, quality=quality,
                        subtitle_delay=subtitle_delay,
                        )
                        return
                    from telegram_editor import transcribe_words, duration_and_audio
                    from speech_review import plain_transcript
                    duration_and_audio(original_file)
                    send_text(
                        token, chat_id,
                        "🎧 Видео получено. Распознаю речь более точной "
                        "моделью. Сначала пришлю текст для проверки."
                    )
                    pending_words = transcribe_words(
                        original_file, model_size="medium", language="ru"
                    )
                    pending_chat_id = chat_id
                    draft = plain_transcript(pending_words)
                    if draft:
                        msg = (
                            "📝 Черновик субтитров:\n\n" + draft[:3000]
                            + ("\n\n(Часть текста скрыта.)" if len(draft) > 3000 else "")
                        )
                    else:
                        msg = "⚠️ Речь не удалось уверенно разобрать."
                    send_text(token, chat_id, msg)
                    send_text(
                        token, chat_id,
                        "Проверь слова ДО монтажа:\n"
                        "/ok — всё верно;\n"
                        "/fix ошибка=правильно — исправить отдельные слова;\n"
                        "/text ТВОЙ ПОЛНЫЙ ТЕКСТ — заменить все слова.\n\n"
                        "После подтверждения наложу анимацию и сделаю зум. "
                        "При больших исправлениях таймкоды приблизительные. "
                        "На ответ даётся 15 минут."
                    )
                    end = time.monotonic() + WAIT_SECONDS
                except ValueError as err:
                    send_text(token, chat_id, "⚠️ " + str(err)[:300])
                    return
                except Exception:
                    LOG.exception("Ошибка распознавания речи")
                    send_text(
                        token, chat_id,
                        "⚠️ Не удалось распознать речь. Открой журнал "
                        "GitHub Actions. Монтаж не запущен."
                    )
                    return
                continue
        LOG.info("Превышено время ожидания.")
        send_text(
            token, owner_id,
            "Время ожидания 15 минут истекло. Для нового монтажа снова "
            "запусти GitHub Actions."
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
