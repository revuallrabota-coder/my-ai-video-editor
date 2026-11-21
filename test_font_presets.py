"""Smoke tests for Cyrillic typefaces from user's new video references."""
from __future__ import annotations
import subprocess
import tempfile
import unittest
from pathlib import Path

from font_presets import PRESETS, choose_font
from word_captions import build_word_pop_ass
from signature_captions import build_signature_ass


class ReferenceFontsTests(unittest.TestCase):
    WORDS = [(0.10,0.43,"Маникюр"),(0.45,0.85,"красивый"),
             (0.88,1.23,"сегодня")]

    def test_all_reference_fonts_are_selectable(self):
        self.assertEqual(len(PRESETS),19)
        for choice in ("bebas","platform","bubble","script","modern","old_money","vintage","street","refined",
                       "roboto","open_sans","noto_sans","ubuntu","carlito","lato_black","modern_condensed"):
            with self.subTest(choice=choice):
                spec=choose_font(choice)
                self.assertGreater(spec.size,50)
                ass,count=build_word_pop_ass(self.WORDS,font_profile=choice)
                self.assertEqual(count,len(self.WORDS))
                self.assertIn("Style: Word,"+spec.name+",",ass)
                self.assertIn("МАНИКЮР",ass)
                self.assertIn("красивый".upper(),ass)
        with self.assertRaises(ValueError):
            choose_font("unknown")

    def test_phrases_support_new_typefaces(self):
        for choice in ("bebas","platform","bubble","script","modern","old_money","vintage","street","refined",
                       "roboto","open_sans","noto_sans","ubuntu","carlito","lato_black","modern_condensed"):
            text,count=build_signature_ass(
                self.WORDS,font_profile=choice
            )
            self.assertGreater(count,0)
            self.assertIn("Style: Accent,"+choose_font(choice).name+",",text)

    def test_installed_ubuntu_fonts_are_resolved(self):
        for choice in ("bebas","platform","bubble","script","modern","old_money","vintage","street","refined",
                       "roboto","open_sans","noto_sans","ubuntu","carlito","lato_black","modern_condensed"):
            spec=choose_font(choice)
            result=subprocess.run(
                ["fc-match","-f","%{family}",spec.name],
                capture_output=True,text=True,check=True
            )
            self.assertTrue(result.stdout.strip())

    def test_ffmpeg_renders_bubble_and_condensed_russian(self):
        for style in ("bebas","bubble","platform"):
            with self.subTest(style=style):
                with tempfile.TemporaryDirectory(prefix="font_test_") as tmp:
                    root=Path(tmp)
                    subs=root/"captions.ass"
                    out=root/"render.mp4"
                    rendered,count=build_word_pop_ass(
                        self.WORDS, font_profile=style,
                        caption_position="middle",
                    )
                    self.assertEqual(count,len(self.WORDS))
                    subs.write_text(rendered,encoding="utf-8")
                    subprocess.run([
                        "ffmpeg","-hide_banner","-loglevel","error","-y",
                        "-f","lavfi","-i",
                        "color=c=#493b45:s=360x640:r=12:d=1.5",
                        "-vf","scale=720:1280,ass="+str(subs),
                        "-an","-c:v","libx264","-preset","ultrafast",
                        "-crf","32",str(out)
                    ],check=True,capture_output=True,timeout=100)
                    self.assertGreater(out.stat().st_size,3000)


if __name__=="__main__":
    unittest.main()
