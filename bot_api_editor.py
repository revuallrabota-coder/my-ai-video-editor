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
from telegram_editor import edit_video

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
    if mode not in ("auto", "captions", "cuts"):
        raise RuntimeError("Неизвестный режим обработки.")

    # Отбрасываем все старые обновления: реагируем только на сообщения после запуска.
    recent = call_api(
        token, "getUpdates", {"offset": -1, "limit": 1, "timeout": 0}
    )
    offset = recent[-1]["update_id"] + 1 if recent else None

    # Это также проверяет, что пользователь уже нажал /start в своём боте.
    send_text(
        token, owner_id,
        "🎬 Монтажёр запущен!\n"
        "Пришли СЕЙЧАС одно новое видео длительностью до 2 минут "
        "и размером до 20 МБ.\n"
        "Оставшиеся api_id и api_hash для этого теста НЕ нужны."
    )
    LOG.info("Готов принять новое видео. Ожидание максимум 15 минут.")

    end = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < end:
        remaining = max(1, int(end - time.monotonic()))
        data = {"limit": 20, "timeout": min(20, remaining), "allowed_updates": '["message"]'}
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
            media = select_video(message)
            if media is None:
                continue
            size = media.get("file_size", 0)
            if size > MAX_FILE_BYTES:
                send_text(
                    token, chat_id,
                    "⚠️ Видео больше 20 МБ. Telegram не позволяет "
                    "обычному боту скачать такой файл. Для первого теста "
                    "отправь короткий клип до 20 МБ."
                )
                continue
            LOG.info("Получено тестовое видео. Начинаю монтаж.")
            send_text(token, chat_id, "✂️ Видео получено. Монтирую и добавляю субтитры…")
            try:
                with tempfile.TemporaryDirectory(prefix="montage_") as tmp:
                    root = Path(tmp)
                    original = root / "original.mp4"
                    ready = root / "ready.mp4"
                    download_video(token, media["file_id"], original)
                    details = edit_video(original, ready, mode, color)
                    send_result(
                        token, chat_id, ready,
                        "✅ Готово!\n"
                        f"Было: {details['before']} сек.\n"
                        f"Стало: {details['after']} сек.\n"
                        "Сохранена исходная речь.",
                    )
            except ValueError as err:
                send_text(token, chat_id, "⚠️ " + str(err)[:300])
                LOG.warning("Ошибка проверки исходного файла")
            except Exception:
                LOG.exception("Ошибка во время монтажа")
                send_text(
                    token, chat_id,
                    "⚠️ Монтаж не завершён. Открой журнал задания в GitHub Actions, "
                    "чтобы выяснить, на каком шаге возникла ошибка."
                )
            return
    LOG.info("Время ожидания истекло; файл не получен.")
    send_text(token, owner_id, "Время ожидания 15 минут истекло. Для нового видео снова запусти GitHub Actions.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
