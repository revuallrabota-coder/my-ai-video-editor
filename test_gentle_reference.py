"""Phrase-level, low-shadow, emoji-attached Reels typography regression tests."""
from __future__ import annotations
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image,ImageChops
from reference_dynamic_captions import (
    build_reference_dynamic_ass,phrase_groups,phrase_geometry,phrase_emoji_anchors,
)
from reels_effects import pick_caption_cues


class GentleReferenceTests(unittest.TestCase):
    WORDS=[
        (.10,.30,"Я"),(.33,.53,"так"),(.56,.89,"параллельна"),
        (1.0,1.27,"работаю"),(1.30,1.56,"с"),(1.58,1.98,"клиентами"),
        (2.5,2.84,"Результат"),(2.90,3.22,"красивый"),
        (3.28,3.60,"сегодня"),
    ]

    def test_complete_phrase_in_one_fade_not_word_pop(self):
        ass,count=build_reference_dynamic_ass(
            self.WORDS,font_profile="old_money",
            small_font_profile="refined",caption_variant="old_money",
            background_style="always",animation_style="float",
        )
        self.assertGreaterEqual(count,2)
        self.assertLess(count,len(self.WORDS)+2)
        lines=[row for row in ass.splitlines() if row.startswith("Dialogue:")]
        self.assertEqual(len(lines),count)
        self.assertNotIn("Dialogue: 0,",ass)
        self.assertIn("Style: PhrasePlate,",ass)
        for line in lines:
            self.assertIn(r"\fad(",line)
            self.assertIn(r"\move(",line)
            self.assertIn(r"\clip(72,175,648,1105)",line)
            self.assertTrue("PhrasePlate,," in line or "OvalShadow,," in line)
        # Never silently drop a spoken word, even with long phrases.
        shown=re.sub(r"\{[^}]*\}","", "\n".join(lines))
        shown=shown.replace(r"\N"," ").lower()
        for _,_,word in self.WORDS:
            self.assertIn(word.lower(),shown)
        self.assertIn(r"\fnLiberation Serif",ass)
        self.assertIn(r"\p1",ass)
        self.assertIn("Style: OvalShadow,",ass)
        self.assertEqual(ass.count("Dialogue: 1,"),len(phrase_groups(self.WORDS)))

    def test_grouping_does_not_leave_a_single_word_flicker(self):
        words=[
            (i*.27,i*.27+.19,word)
            for i,word in enumerate(["сейчас","я","очень","красиво","делаю","маникюр"])
        ]
        groups=phrase_groups(words)
        self.assertEqual([len(g) for g in groups],[4,2])

    def test_emoji_geometry_follows_real_phrase_bounds(self):
        spans=phrase_geometry(self.WORDS,"middle","refined","old_money")
        self.assertGreater(len(spans),0)
        centers=set()
        for start,end,width,cx,cy in spans:
            self.assertLess(start,end)
            self.assertLessEqual(width,455)
            self.assertTrue(290 <= cx <= 430)
            self.assertTrue(560 <= cy <= 830)
            centers.add((cx,cy))
        self.assertGreater(len(centers),1)
        anchors=phrase_emoji_anchors(self.WORDS,"middle","refined","old_money")
        self.assertEqual(len(anchors),len(spans))
        self.assertTrue(all(70 <= x0 <= 600 and 70 <= x1 <= 600
                            for _,_,x0,_,x1,_ in anchors))
        cues=pick_caption_cues(self.WORDS,4.5)
        self.assertLess(len(cues),len(self.WORDS)//2+1)

    def test_hero_title_stars_and_continuous_motion(self):
        ass,count=build_reference_dynamic_ass(
            self.WORDS, caption_variant="reference_soft",
            font_profile="old_money",small_font_profile="refined",
            intro_animated=True, intro_title="Бот который монтирует")
        self.assertIn("Style: HeroBig,",ass)
        self.assertIn("Style: HeroStar,",ass)
        self.assertIn("МОНТИРУЕТ",ass)
        self.assertGreaterEqual(ass.count("HeroStar,,"),3)
        self.assertIn(r"\p1",ass)
        self.assertGreater(count,len(phrase_groups(self.WORDS)))
        lines=[row for row in ass.splitlines() if "Phrase,," in row or "PhrasePlate,," in row]
        motions=[re.search(r"\\move\((\d+),(\d+),(\d+),(\d+),0,(\d+)\)", row) for row in lines]
        self.assertTrue(all(m is not None for m in motions))
        self.assertTrue(any(m.group(1)!=m.group(3) for m in motions))

    def test_true_ffmpeg_plate_stays_with_floating_phrase(self):
        # Two ASS layers with EXACT shared timing/position render one moving oval.
        with tempfile.TemporaryDirectory(prefix="gentle_caption_") as td:
            root=Path(td)
            ass_file=root/"subtitle.ass"
            ass,n=build_reference_dynamic_ass(
                [(0.06,.36,"Я"),(.38,.70,"работаю"),(.72,1.2,"мастером")],
                background_style="always",font_profile="old_money",
                small_font_profile="refined",
            )
            ass_file.write_text(ass,encoding="utf-8")
            for timepoint,kind in ((.26,"in"),(.80,"hold")):
                image=root/(kind+".png")
                subprocess.run([
                    "ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-f","lavfi","-i","color=c=black:s=720x1280:r=20:d=1.6",
                    "-vf",f"ass={ass_file}","-ss",str(timepoint),
                    "-frames:v","1",str(image),
                ],capture_output=True,check=True,timeout=60)
                with Image.open(image) as frame:
                    img=frame.convert("RGB")
                    diff=ImageChops.difference(
                        img,Image.new("RGB",img.size,"black")
                    )
                    bbox=diff.getbbox()
                self.assertIsNotNone(bbox)
                left,top,right,bottom=bbox
                self.assertGreaterEqual(left,70)
                self.assertLessEqual(right,650)
                self.assertGreater(top,200)
                self.assertLess(bottom,1080)


if __name__=="__main__":
    unittest.main()
