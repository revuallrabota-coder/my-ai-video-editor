"""Automated checks for the optional red/white text style from user samples."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from contrast_captions import build_contrast_ass


class ContrastCaptionTests(unittest.TestCase):
    def test_caption_elements_and_no_foreign_watermark(self) -> None:
        words=[
            (0.10,0.48,"Работа"),
            (0.49,0.87,"мастера"),
            (0.88,1.25,"становится"),
            (1.28,1.75,"сложнее"),
        ]
        ass,count=build_contrast_ass(words,hook="РАЗБОР РАБОТЫ")
        self.assertGreaterEqual(count,2)
        self.assertIn("Style: Strong,Liberation Sans",ass)
        self.assertIn("Style: Small,Liberation Sans",ass)
        self.assertIn(r"\fad(",ass)
        self.assertIn(r"\move(",ass)
        self.assertIn("РАЗБОР РАБОТЫ",ass)
        self.assertNotIn("Cheat Code",ass)

    def test_ffmpeg_can_render(self) -> None:
        words=[
            (0.11,0.36,"Сегодня"),
            (0.40,0.81,"покажу"),
            (0.82,1.30,"маникюр"),
        ]
        content,events=build_contrast_ass(words)
        self.assertGreater(events,0)
        with tempfile.TemporaryDirectory(prefix="contrast_test_") as tmp:
            directory=Path(tmp)
            ass_file=directory/"contrast.ass"
            out=directory/"output.mp4"
            ass_file.write_text(content,encoding="utf-8")
            subprocess.run(
                ["ffmpeg","-hide_banner","-loglevel","error","-y",
                 "-f","lavfi","-i","color=c=#254e4a:s=720x1280:r=15:d=2",
                 "-vf","ass="+str(ass_file),
                 "-c:v","libx264","-preset","ultrafast","-crf","32",
                 "-an",str(out)],
                capture_output=True,text=True,check=True,timeout=120
            )
            self.assertGreater(out.stat().st_size,3000)


if __name__=="__main__":
    unittest.main()
