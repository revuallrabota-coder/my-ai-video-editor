"""Unit/smoke tests: signature subtitles must be animated and FFmpeg-renderable."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from signature_captions import build_signature_ass, split_groups


class SignatureCaptionTests(unittest.TestCase):
    WORDS = [
        (0.10, 0.42, "Сегодня"),
        (0.42, 0.82, "разберём"),
        (0.83, 1.22, "маникюр"),
        (1.63, 1.94, "Обрати"),
        (1.94, 2.26, "внимание"),
        (2.26, 2.58, "сюда"),
    ]

    def test_two_levels_animated(self) -> None:
        ass, count = build_signature_ass(
            self.WORDS, color="#EBC0C8", hook="НАШ СТИЛЬ"
        )
        self.assertGreaterEqual(count, 4)
        self.assertIn("Style: Whisper", ass)
        self.assertIn("Style: Accent,Liberation Serif", ass)
        self.assertIn(r"\move(", ass)
        self.assertIn(r"\fad(", ass)
        self.assertIn(r"\t(0,", ass)
        self.assertIn("НАШ СТИЛЬ", ass)
        self.assertIn("РАЗБЕРЁМ", ass)
        self.assertIn("маникюр", ass)  # нижняя белая строка
        self.assertIn("Сегодня", ass)  # верхняя белая строка
        self.assertNotIn("random zoom", ass)

    def test_does_not_break_on_untrusted_words(self) -> None:
        ass, count = build_signature_ass([
            (0.1, 1.0, r"{\danger}"),
            (1.0, 1.4, "слово")
        ])
        self.assertGreater(count, 0)
        self.assertNotIn(r"\danger", ass)

    def test_breaks_on_speaking_pause(self) -> None:
        groups = split_groups(self.WORDS)
        self.assertGreaterEqual(len(groups), 2)

    def test_ffmpeg_renders_animated_ass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="signature_test_") as tmp:
            root = Path(tmp)
            ass, count = build_signature_ass(
                self.WORDS, hook="РАЗБОР МАНИКЮРА"
            )
            self.assertGreater(count, 0)
            subtitle = root / "signature.ass"
            subtitle.write_text(ass, encoding="utf-8")
            video = root / "test.mp4"
            # Filenames generated internally with no colon/backslash injection.
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=#47312c:s=720x1280:r=15:d=3",
                "-vf", "subtitles=" + str(subtitle),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-an", str(video),
            ], check=True, capture_output=True, timeout=120)
            self.assertGreater(video.stat().st_size, 10000)


if __name__ == "__main__":
    unittest.main()
