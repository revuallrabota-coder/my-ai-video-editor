"""Word-pop subtitles must render one spoken word per timed event."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from word_captions import build_word_pop_ass, word_events


class OneWordCaptionTests(unittest.TestCase):
    WORDS = [
        (0.05,0.37,"Сегодня"),
        (0.38,0.63,"мы"),
        (0.64,1.04,"проверим"),
        (1.12,1.48,"маникюр"),
        (1.55,1.86,"вместе"),
    ]

    def test_only_one_word_in_every_subtitle_event(self) -> None:
        ass, count = build_word_pop_ass(
            self.WORDS, style="signature", color="auto",
        )
        events = [line for line in ass.splitlines() if line.startswith("Dialogue: 0,")]
        self.assertEqual(len(events),len(self.WORDS))
        self.assertEqual(count,len(self.WORDS))
        for line, word in zip(events,self.WORDS):
            self.assertTrue(line.endswith(word[2].upper()))
            self.assertIn(r"\move(",line)
            self.assertIn(r"\fad(",line)
            self.assertIn(r"\fscx87",line)

    def test_no_overlaps_in_normal_word_timing(self) -> None:
        events = word_events(self.WORDS)
        self.assertEqual(len(events),len(self.WORDS))
        for i in range(len(events)-1):
            self.assertLessEqual(events[i][1],events[i+1][0])

    def test_styles_fonts_positions(self) -> None:
        pink,_ = build_word_pop_ass(
            self.WORDS, style="signature", font_profile="elegant",
            caption_position="middle",
        )
        red,_ = build_word_pop_ass(
            self.WORDS, style="contrast",font_profile="bold",
            caption_position="bottom",
        )
        self.assertIn("Liberation Serif",pink)
        self.assertIn("DejaVu Sans",red)
        self.assertIn(r"\move(360,1069,360,1055",red)
        self.assertNotEqual(pink,red)

    def test_rendered_by_ffmpeg(self) -> None:
        ass, count = build_word_pop_ass(
            self.WORDS, style="signature", hook="РАЗБОР",
        )
        self.assertEqual(count,len(self.WORDS)+1)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            subs=folder/"words.ass"
            video=folder/"words.mp4"
            subs.write_text(ass,encoding="utf-8")
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=#47312c:s=720x1280:r=15:d=2",
                "-vf","ass="+str(subs),"-c:v","libx264",
                "-preset","ultrafast","-crf","32","-an",str(video),
            ],check=True,capture_output=True,timeout=120)
            self.assertGreater(video.stat().st_size,3000)


if __name__=="__main__":
    unittest.main()
