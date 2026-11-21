"""Person-aware talking Reels captions.

For 'behind', place the uncaptioned person back over the rendered text.
For 'beside', additionally position the words in the emptier side column.
No segmentation is used in normal mode. A failed mask must never silently
turn the requested behind-person effect into captions over someone's face.
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import tempfile
import urllib.request
from contextlib import contextmanager
from pathlib import Path

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/"
             "image_segmenter/selfie_segmenter/float16/latest/"
             "selfie_segmenter.tflite")
MODEL_SHA256 = "191ac9529ae506ee0beefa6b2c945a172dab9d07d1e802a290e907ecdade60"
VALID_LAYOUTS = ("standard", "behind", "beside")
LOG = logging.getLogger("portrait_captions")


def check_layout(layout: str) -> str:
    if layout not in VALID_LAYOUTS:
        raise ValueError("Неизвестное расположение текста относительно человека.")
    return layout


@contextmanager
def _segmenter():
    try:
        import cv2
        import mediapipe as mp
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Для текста за человеком нужен MediaPipe. Проверь зависимости GitHub Actions."
        ) from exc
    with tempfile.TemporaryDirectory(prefix="portrait_model_") as directory:
        model = Path(directory) / "selfie_segmenter.tflite"
        try:
            with urllib.request.urlopen(MODEL_URL, timeout=45) as response:
                data = response.read(2_000_001)
            if len(data) > 2_000_000 or hashlib.sha256(data).hexdigest() != MODEL_SHA256:
                raise RuntimeError("Неверный файл модели отделения человека.")
            model.write_bytes(data)
        except Exception as exc:
            raise RuntimeError(
                "Не удалось загрузить модель отделения человека. Повтори монтаж."
            ) from exc
        options = mp.tasks.vision.ImageSegmenterOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            output_confidence_masks=True,
            output_category_mask=False,
        )
        with mp.tasks.vision.ImageSegmenter.create_from_options(options) as segmenter:
            yield segmenter, mp, cv2, np


def _person_mask(frame, segmenter, mp, cv2, np):
    # The original MediaPipe model is 256x256. Working on a downscaled frame
    # keeps CPU use reasonable for up to two minutes of video.
    mini = cv2.resize(frame, (256, 256), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(mini, cv2.COLOR_BGR2RGB)
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    result = segmenter.segment(image)
    if not result.confidence_masks:
        raise RuntimeError("Модель не вернула маску человека.")
    mask = np.asarray(result.confidence_masks[0].numpy_view(), dtype=np.float32)
    if not np.isfinite(mask).all():
        raise RuntimeError("Ошибка маски человека.")
    return np.clip(mask, 0., 1.)


def choose_text_side(video: Path) -> str:
    """Select the less occupied column using several representative frames."""
    with _segmenter() as (segmenter, mp, cv2, np):
        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            raise RuntimeError("Не удалось открыть видео для выбора положения текста.")
        centers = []
        try:
            count = max(1, round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
            for ratio in (0.12, 0.36, 0.62):
                capture.set(cv2.CAP_PROP_POS_FRAMES, round((count - 1) * ratio))
                ok, frame = capture.read()
                if not ok:
                    continue
                mask = _person_mask(frame, segmenter, mp, cv2, np)
                binary = mask > 0.55
                if float(binary.mean()) < 0.025:
                    continue
                ys, xs = np.nonzero(binary)
                centers.append(float(np.median(xs)) / mask.shape[1])
        finally:
            capture.release()
        if not centers:
            raise ValueError(
                "В видео не удалось обнаружить человека для режима «Текст рядом»."
            )
        # Person on the right => put text on the left, and conversely.
        return "left" if float(np.median(centers)) >= 0.5 else "right"


def protect_subject(
    clean_video: Path, captioned_video: Path, output: Path,
    *, quality: str = "high",
) -> None:
    """Overpaint the person from clean_video on the matching captioned frames.

    Both videos must have exactly the same camera transform, 30fps and
    dimensions. Copy audio from captioned_video without touching the voice.
    """
    from export_profiles import get_export_profile
    profile = get_export_profile(quality)
    with _segmenter() as (segmenter, mp, cv2, np):
        clean = cv2.VideoCapture(str(clean_video))
        titled = cv2.VideoCapture(str(captioned_video))
        if not clean.isOpened() or not titled.isOpened():
            clean.release()
            titled.release()
            raise RuntimeError("Не удалось открыть видеодорожки для наложения человека.")
        width = int(clean.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(clean.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(clean.get(cv2.CAP_PROP_FPS))
        if (width < 1 or height < 1 or fps < 1 or
            int(titled.get(cv2.CAP_PROP_FRAME_WIDTH)) != width or
            int(titled.get(cv2.CAP_PROP_FRAME_HEIGHT)) != height or
            abs(float(titled.get(cv2.CAP_PROP_FPS)) - fps) > .1):
            clean.release()
            titled.release()
            raise ValueError("Чистое видео и видео с субтитрами не синхронизированы.")
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-video_size", f"{width}x{height}", "-framerate", f"{fps:.6f}",
            "-i", "pipe:0", "-i", str(captioned_video),
            "-map", "0:v:0", "-map", "1:a:0?",
            "-c:v", "libx264", "-preset", profile.preset,
            "-crf", str(profile.crf), "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-shortest", "-movflags", "+faststart",
            str(output),
        ]
        output.parent.mkdir(parents=True, exist_ok=True)
        frame_count = 0
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errors)
            try:
                while True:
                    ok_clean, plain = clean.read()
                    ok_titled, with_text = titled.read()
                    if not ok_clean and not ok_titled:
                        break
                    if ok_clean != ok_titled:
                        raise RuntimeError(
                            "Видеодорожки разной длительности. Нельзя точно совместить маску."
                        )
                    low_mask = _person_mask(plain, segmenter, mp, cv2, np)
                    # Slight dilation covers skin and hair edges. Soft feathering
                    # avoids a hard cutout or shadow stuck behind a moving person.
                    alpha = cv2.dilate(low_mask, np.ones((3, 3), np.uint8))
                    alpha = cv2.resize(alpha, (width, height), interpolation=cv2.INTER_LINEAR)
                    alpha = np.clip((alpha - .16) / .55, 0., 1.)
                    alpha = cv2.GaussianBlur(alpha, (0, 0), 1.4)[:, :, None]
                    merged = (plain.astype(np.float32) * alpha +
                              with_text.astype(np.float32) * (1. - alpha))
                    if process.stdin is None:
                        raise RuntimeError("Не удалось передать видеокадры FFmpeg.")
                    process.stdin.write(np.clip(merged, 0, 255).astype(np.uint8).tobytes())
                    frame_count += 1
                if process.stdin:
                    process.stdin.close()
                if process.wait(timeout=240) != 0:
                    raise RuntimeError("FFmpeg не смог собрать видео с текстом за человеком.")
                if frame_count == 0:
                    raise RuntimeError("Не обнаружены кадры для монтажа.")
            except Exception:
                if process.poll() is None:
                    process.kill()
                process.wait()
                raise
            finally:
                clean.release()
                titled.release()
        LOG.info("Composited portrait over %d caption frames", frame_count)
