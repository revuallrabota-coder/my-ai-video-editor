"""Regression for all 18 PDF-inspired original scene adapters."""
from __future__ import annotations
import math
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from PIL import Image,ImageChops,ImageDraw

from guide18_fx import (
    EFFECTS,FULL_FX,SUBJECT_FX,GuideCue,_draw,plan,render,sound_track,
)

WORDS=[
    (.12,.45,"Сначала"),(.5,.85,"разберём"),(1.0,1.3,"ошибку"),
    (4.1,4.4,"Потом"),(4.5,4.9,"покажем"),(5.0,5.4,"салон"),
    (9.2,9.6,"Сравним"),(9.8,10.2,"работу"),
    (14.5,14.9,"Смотри"),(15.0,15.4,"важное"),
    (19.3,19.8,"Результат"),(20.0,20.5,"потрясающий"),
]
class GuideFxTests(unittest.TestCase):
    def test_complete_catalog_no_missing_or_duplicate_effects(self):
        self.assertEqual(len(EFFECTS),18)
        self.assertEqual(len(set(EFFECTS)),18)
        self.assertEqual(len(FULL_FX.intersection(EFFECTS)),10)
        self.assertTrue(SUBJECT_FX.issubset(EFFECTS.keys()))
        with self.assertRaises(ValueError):
            plan(WORDS,25,"nonexistent")

    def test_all_18_have_real_distinct_frame_procedures(self):
        frame=Image.new("RGB",(360,640),(100,94,88))
        other=Image.new("RGB",(360,640),(162,110,97))
        frames=[frame,other]*5
        mask=Image.new("L",(360,640),0)
        ImageDraw.Draw(mask).ellipse((95,100,265,610),fill=235)
        for effect in EFFECTS:
            with self.subTest(effect=effect):
                a=_draw(effect,.12,"МАНИКЮР",frame,frames,1,mask,WORDS,0,"cream")
                b=_draw(effect,.82,"МАНИКЮР",other,frames,4,mask,WORDS,0,"cream")
                self.assertEqual(a.size,(360,640))
                self.assertEqual(a.mode,"RGBA")
                difference=ImageChops.difference(a,b)
                self.assertTrue(
                    difference.convert("RGB").getbbox() or
                    ImageChops.difference(a.getchannel("A"),b.getchannel("A")).getbbox(),
                    "Motion must visibly change instead of freezing a screenshot")

    def test_auto_scenes_are_semantic_and_never_overlap(self):
        cues=plan(WORDS,25,"auto","dynamic")
        self.assertGreaterEqual(len(cues),2)
        self.assertTrue(all(c.effect in EFFECTS for c in cues))
        self.assertTrue(all(c.start>=0 and c.end<=25 for c in cues))
        for left,right in zip(cues,cues[1:]):
            self.assertGreaterEqual(right.start-left.end,1.0)
        self.assertEqual(cues,plan(WORDS,25,"auto","dynamic"))
        self.assertEqual(plan([],25,"auto"),[]) # no invented spoken words

    def test_automatic_mode_keeps_unrelated_words_and_the_intro_clean(self):
        unrelated=[
            (.08,.32,"Сначала"),(.4,.77,"поговорим"),
            (1.9,2.15,"сегодня"),(4.9,5.3,"маникюр"),
            (7.9,8.2,"клиент"),(11.,11.4,"покрытие"),
        ]
        self.assertEqual(plan(unrelated,13,"auto","dynamic"),[])
        relevant=unrelated+[(13.2,13.6,"ошибку"),(18.2,18.6,"результат")]
        cues=plan(relevant,22,"auto","dynamic")
        self.assertTrue(cues)
        self.assertTrue(all(c.compact for c in cues))
        self.assertTrue(all(c.start>=4 for c in cues))
        self.assertTrue(all(c.label in {"ОШИБКУ","РЕЗУЛЬТАТ"} for c in cues))

    def test_manual_mode_uses_only_one_chosen_effect(self):
        for effect in EFFECTS:
            cues=plan(WORDS,25,effect,"balanced")
            self.assertTrue(cues)
            self.assertTrue(all(c.effect==effect for c in cues))
            self.assertTrue(all(c.end-c.start<=3.001 for c in cues))

    def test_sfx_varies_without_overwriting_voice(self):
        with tempfile.TemporaryDirectory() as t:
            file=Path(t)/"guide.wav"
            cues=[GuideCue("match_cut",.1,2.1,"ОШИБКА"),
                  GuideCue("notification_stack",2.5,4.2,"ВНИМАНИЕ"),
                  GuideCue("apple_ui_toggles",4.9,6.5,"ПРОВЕРКА")]
            sound_track(file,cues,7.0)
            with wave.open(str(file),"rb") as f:
                self.assertEqual(f.getframerate(),48000)
                self.assertEqual(f.getnchannels(),1)
                data=f.readframes(f.getnframes())
            self.assertGreater(sum(x!=0 for x in data),1000)
            chunks=[data[int(t*48000)*2:int((t+.16)*48000)*2]
                    for t in (.1,2.5,4.9)]
            self.assertEqual(len(set(chunks)),3)

    @unittest.skipUnless(shutil.which("ffmpeg"),"FFmpeg required")
    def test_video_frames_are_temporally_dynamic(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)
            source=folder/"input.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=size=360x640:rate=15:duration=3",
                "-c:v","libx264","-preset","ultrafast",str(source)
            ],check=True,capture_output=True,timeout=50)
            cue=GuideCue("phone_3d_float",.1,2.95,"ТЕЛЕФОН")
            pattern,count=render(source,folder,cue,0,WORDS,"cream")
            self.assertGreaterEqual(count,30)
            from PIL import Image
            a=Image.open(pattern.replace("%03d","000")).convert("RGBA")
            b=Image.open(pattern.replace("%03d",str(count//2).zfill(3))).convert("RGBA")
            self.assertIsNotNone(ImageChops.difference(a,b).convert("RGB").getbbox())

if __name__=="__main__":
    unittest.main()
