"""Regression: centered Reels captions must not overrun safe-area margins."""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from font_presets import choose_font
from reference_dynamic_captions import (
    TEXT_SAFE_WIDTH, _measure_width, build_reference_dynamic_ass,
    fit_caption_size,
)


class CaptionSafeAreaTests(unittest.TestCase):
    def test_long_cyrillic_and_two_word_accent_fit_into_screen(self):
        examples = [
            "ПАРАЛЛЕЛЬНА",
            "МАНИКЮР",
            "НЕВОЗМОЖНО",
            "ПРОФЕССИОНАЛЬНЫЙ",
            "СВЕРХПОПУЛЯРНЫЙ",
        ]
        for preset in ("old_money", "street", "vintage", "bold"):
            font = choose_font(preset)
            for word in examples:
                with self.subTest(preset=preset, word=word):
                    size = fit_caption_size(word, 90, font)
                    self.assertLessEqual(size, 90)
                    self.assertGreaterEqual(size, 24)
                    self.assertLessEqual(
                        _measure_width(word, size, font),
                        TEXT_SAFE_WIDTH * 0.91 + 2.0,
                    )

    def test_no_random_horizontal_scattering_or_duplicate_context(self):
        words = [
            (0.1,0.42,"Я"),(0.44,0.74,"так"),
            (0.76,1.25,"параллельна"),
            (1.6,1.9,"работа"),(1.94,2.4,"мастера"),
        ]
        ass, count = build_reference_dynamic_ass(
            words,
            background_style="always",
            font_profile="old_money",
            small_font_profile="refined",
        )
        self.assertGreater(count, 1)
        self.assertNotIn(r"\fs107", ass)
        self.assertEqual(count, len(re.findall(r"^Dialogue:",ass,re.M)))
        self.assertEqual(
            len(re.findall(r"^Dialogue: 2,",ass,re.M)),
            len(re.findall(r"^Dialogue: 0,",ass,re.M)),
        )
        # Both subtitle and its plate share the exact x=360 anchor.
        for line in ass.splitlines():
            if line.startswith("Dialogue:"):
                self.assertRegex(line,r"\\(?:move|pos)\(360,")
        # Text is never rendered again as a separate distant extra line.
        self.assertNotIn("Dialogue: 1,", ass)

    def test_ffmpeg_renders_long_emphasis_inside_9_by_16(self):
        from PIL import Image, ImageChops
        with tempfile.TemporaryDirectory(prefix="caption_safearea_") as tmp:
            root = Path(tmp)
            ass_file, png_file = root/"subtitles.ass", root/"frame.png"
            ass, _ = build_reference_dynamic_ass(
                [(0.05,0.85,"ПАРАЛЛЕЛЬНА")],
                color="auto",font_profile="old_money",
                background_style="always",animation_style="float",
            )
            ass_file.write_text(ass,encoding="utf-8")
            cmd=[
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=black:s=720x1280:r=10:d=0.8",
                "-vf",f"ass={ass_file}","-ss","0.35","-frames:v","1",
                str(png_file),
            ]
            subprocess.run(cmd,check=True,capture_output=True,timeout=60)
            with Image.open(png_file) as img:
                rgb=img.convert("RGB")
                bbox=ImageChops.difference(
                    rgb,Image.new("RGB",rgb.size,"black")
                ).getbbox()
            self.assertIsNotNone(bbox)
            left,top,right,bottom=bbox
            self.assertGreaterEqual(left,50)
            self.assertLessEqual(right,670)
            self.assertGreater(top,100)
            self.assertLess(bottom,1170)


if __name__=="__main__":
    unittest.main()
