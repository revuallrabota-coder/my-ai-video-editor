"""Проверка аудиоконвейера на синтетическом видео без приватных файлов."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from telegram_editor import Segment, audio_filterchain, base_video, duration_and_audio


def run(*args: str) -> None:
    subprocess.run(list(args), check=True, capture_output=True, text=True)


class AudioPipelineTests(unittest.TestCase):
    def test_profiles_are_validated(self) -> None:
        self.assertEqual(audio_filterchain("off"), "")
        self.assertIn("afftdn", audio_filterchain("balanced"))
        self.assertIn("loudnorm", audio_filterchain("strong"))
        with self.assertRaises(ValueError):
            audio_filterchain("ultra_noisy_untrusted")

    def test_sound_is_preserved_in_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="audio_smoke_") as directory:
            path = Path(directory)
            source = path / "source.mp4"
            run(
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=15:duration=1.6",
                "-f", "lavfi", "-i", "sine=frequency=430:sample_rate=48000:duration=1.6",
                "-filter_complex", "[1:a]volume=0.05[spoken]",
                "-map", "0:v:0", "-map", "[spoken]",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-shortest", str(source),
            )
            for profile in ("off", "balanced", "strong"):
                with self.subTest(profile=profile):
                    output = path / f"{profile}.mp4"
                    base_video(source, output, [Segment(0, 1.4)], True, audio_profile=profile, quality="balanced")
                    duration, audio = duration_and_audio(output)
                    self.assertTrue(audio)
                    self.assertGreater(duration, 1.25)
                    self.assertLess(duration, 1.65)
                    self.assertGreater(output.stat().st_size, 10000)
            # Сопоставляем выбранные в записи настройки: ускорение ×1.1
            # и тёплая цветокоррекция с обязательным сохранением аудио.
            chosen = path / "x11_warm.mp4"
            base_video(
                source, chosen, [Segment(0, 1.4)], True,
                audio_profile="balanced", speed=1.1, filter_style="warm", quality="balanced",
            )
            faster_duration, has_audio = duration_and_audio(chosen)
            self.assertTrue(has_audio)
            self.assertGreater(faster_duration, 1.15)
            self.assertLess(faster_duration, 1.38)
            self.assertGreater(chosen.stat().st_size, 10000)


if __name__ == "__main__":
    unittest.main()
