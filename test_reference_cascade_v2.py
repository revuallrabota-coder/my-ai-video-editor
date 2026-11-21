"""Regression of additive pink/white captions against the supplied reference."""
from __future__ import annotations
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from reference_cascade_captions import build_reference_cascade_ass,oval_path
from telegram_editor import write_ass,duration_and_audio


class ReferenceCascadeV2Tests(unittest.TestCase):
    WORDS=[
        (.15,.34,"ты"),(.35,.66,"вырезаешь"),(.67,.89,"каждую"),
        (.91,1.22,"паузу"),(1.65,1.97,"добавляешь"),
        (2.03,2.28,"субтитры"),
    ]

    def test_accumulation_instead_of_word_replacement(self):
        ass,count=build_reference_cascade_ass(
            self.WORDS,background_style="always",
            font_profile="old_money",small_font_profile="refined",
            caption_variant="reference_soft"
        )
        big=[x for x in ass.splitlines() if x.startswith("Dialogue: 2,")
             and "CascadeBig" in x]
        little=[x for x in ass.splitlines() if x.startswith("Dialogue: 2,")
                and "CascadeSmall" in x]
        self.assertGreaterEqual(len(big),1)
        self.assertGreaterEqual(len(little),2)
        self.assertGreater(count,4)
        self.assertTrue(any("ВЫРЕЗАЕШЬ" in x for x in big))
        # Earlier context should still be visible when a following word
        # joins the same phrase (their events overlap in time).
        def interval(line):
            first=line.split(",")
            def parse(t):
                h,m,s=t.split(":")
                return int(h)*3600+int(m)*60+float(s)
            return parse(first[1]),parse(first[2])
        preceding=next(x for x in little if "ты" in x)
        emphasis=next(x for x in big if "ВЫРЕЗАЕШЬ" in x)
        a,b=interval(preceding)
        c,d=interval(emphasis)
        self.assertLess(c,b)
        self.assertLess(a,d)

    def test_oval_has_positive_path_and_matches_glyph_move(self):
        ass,_=build_reference_cascade_ass(
            self.WORDS,background_style="always"
        )
        self.assertTrue(oval_path(250,70).startswith("m "))
        shadows=[x for x in ass.splitlines() if x.startswith("Dialogue: 1,")]
        self.assertGreater(len(shadows),2)
        self.assertTrue(all(r"\an7\move(" in x for x in shadows))
        self.assertTrue(all(r"\p1" in x and r"\blur5.3" in x for x in shadows))
        self.assertFalse(any("BorderStyle=3" in x for x in shadows))
        texts=[x for x in ass.splitlines() if x.startswith("Dialogue: 2,")]
        for shadow in shadows:
            # The backing has the same start/end as precisely one text word.
            span=shadow.split(",",3)[1:3]
            self.assertTrue(any(x.split(",",3)[1:3]==span for x in texts))

    def test_real_telegram_pipeline_uses_reference_cascade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            src=root/"short.mp4"
            ass_path=root/"captions.ass"
            out=root/"frame.png"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=#42312c:s=360x640:r=12:d=3",
                "-f","lavfi","-i","sine=frequency=440:duration=3",
                "-c:v","libx264","-preset","ultrafast",
                "-c:a","aac","-shortest",str(src)
            ],check=True,capture_output=True,timeout=50)
            events=write_ass(
                src,ass_path,"#E8A4B5",style="reference_dynamic",
                words_override=self.WORDS,
                font_profile="old_money",
                small_font_profile="refined",
                background_style="always",
                top_title="Разбор маникюра",
                top_title_mode="always"
            )
            text=ass_path.read_text("utf8")
            self.assertGreater(events,4)
            self.assertIn("Style: CascadeBig",text)
            self.assertIn("Style: CascadeSmall",text)
            self.assertIn("CustomTopTitle",text)
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=#42312c:s=720x1280:r=12:d=3",
                "-vf",f"ass={ass_path}","-ss","1.0","-frames:v","1",str(out)
            ],check=True,capture_output=True,timeout=70)
            self.assertGreater(out.stat().st_size,3000)


if __name__=="__main__":
    unittest.main()
