"""End-to-end oval subtitle shadows and manually entered upper Reels titles."""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops
from reference_dynamic_captions import build_reference_dynamic_ass,_oval_phrase_shadow,phrase_groups
from top_video_title import append_top_title, title_lines
from telegram_editor import write_ass


class OvalAndTitleTests(unittest.TestCase):
    WORDS = [(0.25,0.48,"Это"),(0.50,0.79,"ошибка"),
             (0.81,1.14,"маникюра"),(1.38,1.75,"Посмотри"),
             (1.79,2.08,"сюда"),(2.13,2.37,"вот")]

    def test_true_capsule_not_square_ass_border_style(self):
        blob=_oval_phrase_shadow(350,80)
        self.assertIn(" b ",blob)
        self.assertTrue(blob.startswith("m "))
        ass,n=build_reference_dynamic_ass(
            self.WORDS,background_style="always",
            font_profile="old_money",small_font_profile="refined")
        self.assertIn("Style: OvalShadow,",ass)
        styles=[row for row in ass.splitlines() if row.startswith("Style: PhrasePlate,")]
        self.assertEqual(len(styles),1)
        # BorderStyle is field index 15 after "Style: ".
        self.assertEqual(styles[0].split(",")[15],"1")
        self.assertNotIn(",0,0,3,",styles[0])
        groups=phrase_groups(self.WORDS)
        self.assertEqual(n,len(groups)*2)
        shadows=[line for line in ass.splitlines() if line.startswith("Dialogue: 1,")]
        captions=[line for line in ass.splitlines() if line.startswith("Dialogue: 2,")]
        self.assertEqual(len(shadows),len(captions))
        for a,b in zip(shadows,captions):
            # Visibility, fade and movement must remain locked frame by frame.
            self.assertEqual(a.split(",",3)[1:3],b.split(",",3)[1:3])
            ma=re.search(r"\\move\([^)]+\)",a)
            mb=re.search(r"\\move\([^)]+\)",b)
            self.assertIsNotNone(ma)
            self.assertEqual(ma.group(),mb.group())
            fa=re.search(r"\\fad\([^)]+\)",a)
            fb=re.search(r"\\fad\([^)]+\)",b)
            self.assertEqual(fa.group(),fb.group())
            self.assertIn(r"\p1",a)
            self.assertNotIn(r"\p1",b)

    def test_oval_is_also_used_for_long_wrapped_phrase(self):
        words=[(0.2,0.54,"Профессиональный"),
               (0.57,0.81,"маникюр"),(.87,1.2,"очень"),
               (1.22,1.61,"сложный")]
        ass,_=build_reference_dynamic_ass(
            words,background_style="always",
            font_profile="old_money",small_font_profile="refined")
        self.assertIn(r"\N",ass)
        self.assertIn("OvalShadow,,",ass)
        self.assertIn(r"\blur6",ass)

    def test_custom_title_can_stay_throughout_or_only_intro(self):
        ass,_=build_reference_dynamic_ass(self.WORDS,
                background_style="off",intro_animated=False)
        title="Разбор кошмарного маникюра"
        entire=append_top_title(ass,title,"always",15)
        opening=append_top_title(ass,title,"intro",15)
        self.assertIn("РАЗБОР",entire)
        self.assertIn("CustomTopTitle,,",entire)
        self.assertIn("0:00:15.00",entire)
        self.assertNotIn("0:00:15.00",opening)
        self.assertIn("0:00:03.80",opening)
        self.assertEqual(append_top_title(ass,title,"off",15),ass)
        self.assertEqual(append_top_title(ass,"","always",15),ass)
        for unsafe in ("До {100} процентов",r"Привет \N"):
            cleaned,_=title_lines(unsafe)
            self.assertNotIn("{",cleaned)
            self.assertNotIn("}",cleaned)

    def test_real_ffmpeg_top_text_and_oval_render_in_correct_positions(self):
        with tempfile.TemporaryDirectory(prefix="oval_title_") as temp:
            folder=Path(temp)
            source=folder/"original.mp4"
            ass_path=folder/"captions.ass"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=#20212a:s=360x640:r=12:d=5.1",
                "-f","lavfi","-i","sine=frequency=380:duration=5.1",
                "-c:v","libx264","-preset","ultrafast",
                "-c:a","aac","-shortest",str(source)
            ],check=True,capture_output=True,timeout=60)
            count=write_ass(
                source,ass_path,"#E8A4B5",style="reference_dynamic",
                words_override=self.WORDS,
                background_style="always",
                top_title="РАЗБОР КОШМАРНОГО МАНИКЮРА",
                top_title_mode="always",
            )
            content=ass_path.read_text(encoding="utf-8")
            self.assertGreater(count,0)
            self.assertIn("CustomTopTitle",content)
            self.assertNotIn("Style: HeroBig",content)
            self.assertIn("Style: OvalShadow",content)
            frame=folder/"frame.png"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=#20212a:s=720x1280:r=12:d=5.1",
                "-vf",f"ass={ass_path}","-ss","4.0",
                "-frames:v","1",str(frame)
            ],check=True,capture_output=True,timeout=90)
            with Image.open(frame) as image:
                rgb=image.convert("RGB")
                # The upper title remains at second four, when subtitles end.
                inside=rgb.crop((70,76,650,205))
                background=Image.new("RGB",inside.size,"#20212a")
                self.assertIsNotNone(ImageChops.difference(inside,background).getbbox())


if __name__=="__main__":
    unittest.main()
