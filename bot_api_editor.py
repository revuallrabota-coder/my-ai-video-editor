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
                API_ROOT + token + "/sendVideo",
                data={"chat_id": chat_id, "caption": caption, "supports_streaming": "true"},
                files={"video": (result.name, stream, "video/mp4")},
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
    color = os.environ.get("SUBTITLE_COLOR", "#E8A0C0")
    audio_profile = os.environ.get("AUDIO_PROFILE", "balanced")
    audio_filterchain(audio_profile)  # early validation
    subtitle_style = os.environ.get("SUBTITLE_STYLE", "signature")
    if subtitle_style not in ("signature", "classic"):
        raise ValueError("Неизвестный стиль субтитров.")
    hook = os.environ.get("HOOK_TEXT", "").strip()[:70]
    if mode not in ("auto", "captions", "cuts", "reference", "my_style"):
        raise RuntimeError("Неизвестный режим обработки.")

    # Старые сообщения не используем. Отправляй файлы только после приглашения.
    recent = call_api(token, "getUpdates", {"offset": -1, "limit": 1, "timeout": 0})
    offset = recent[-1]["update_id"] + 1 if recent else None
    if mode == "my_style":
        prompt = (
            "💗 Режим «Мой стиль» запущен!\n"
            "Пришли ОДНО новое исходное видео до 20 МБ и 2 минут.\n"
            "Я сделаю плавные приближения, всплывающие розовые субтитры "
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

                send_text(token, chat_id, "🎧 Исходник получен. Делаю монтаж и улучшаю звучание речи…")
                try:
                    download_video(token, media["file_id"], original_file)
                    if mode in ("reference", "my_style"):
                        details = montage_by_reference(
                            original_file,
                            reference_file if mode == "reference" else None,
                            output_file, color, audio_profile, subtitle_style, hook
                        )
                        if mode == "reference":
                            caption = (
                                "✅ Монтаж по референсу готов!\n"
                                f"Видео: {details['before']} → {details['after']} сек.\n"
                                f"Ритм: ~{details['reference_pace_seconds']} сек.\n"
                                "Мягкие приближения и всплывающие субтитры.\n"
                                "Не копируются все сторонние вставки и эффекты."
                            )
                        else:
                            caption = (
                                "💗 Reels в твоём стиле готов!\n"
                                f"Видео: {details['before']} → {details['after']} сек.\n"
                                "Плавные зумы, двухуровневые субтитры и твой голос."
                            )
                    else:
                        details = edit_video(
                            original_file, output_file, mode, color, audio_profile,
                            subtitle_style, hook
                        )
                        caption = (
                            "✅ Готово!\n"
                            f"Видео: {details['before']} → {details['after']} сек.\n"
                            "Оригинальная речь сохранена."
                        )
                    send_result(token, chat_id, output_file, caption)
                    LOG.info("Готовое видео отправлено.")
                except ValueError as err:
                    send_text(token, chat_id, "⚠️ " + str(err)[:300])
                    LOG.warning("Некорректный исходный файл: %s", err)
                except Exception:
                    LOG.exception("Не удалось выполнить монтаж")
                    send_text(
                        token, chat_id,
                        "⚠️ Монтаж не завершён. Открой журнал этого запуска "
                        "в GitHub Actions, там виден проблемный шаг."
                    )
                return
        LOG.info("Превышено время ожидания.")
        send_text(
            token, owner_id,
            "Время ожидания 15 минут истекло. Для нового монтажа снова "
            "запусти GitHub Actions."
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
