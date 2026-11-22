"""Real vintage cinema tests: spoken timing, pixel scenes, sound and iPad preset."""
from __future__ import annotations
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from PIL import Image
from vintage_cinema import VintageCue, select_vintage_cues,render_vintage_scene,make_vintage_sound_track
from video_filters import video_filter_chain

class VintageCinemaTests(unittest.TestCase):
    def test_speech_is_the_only_source_for_text_and_no_intro_overlay(self):
        words=[
            (0.1,.3,"монтаж"), (2.,2.2,"кино"), (5.7,6.1,"ошибку"),
            (6.12,6.3,"на"), (6.35,6.7,"ногте"), (6.8,7.2,"покажу"),
            (20.,20.3,"время"), (20.4,20.7,"покрытия"),
        ]
        cues=select_vintage_cues(words,31.,"dynamic")
        self.assertGreaterEqual(len(cues),2)
        self.assertTrue(all(c.start>=5.0 and c.end<31 for c in cues))
        transcript=" ".join(x[2] for x in words).lower()
        for cue in cues:
            self.assertIn(cue.phrase.lower(),transcript)
            self.assertGreater(cue.end-cue.start,1.4)
        self.assertEqual(select_vintage_cues([],40),[])
        self.assertEqual(select_vintage_cues([(2,2.2,"проектор")],10),[])

    def test_audio_is_real_original_wav_with_quiet_nonzero_projector_clicks(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"projector.wav"
            cue=VintageCue(5.5,7.4,"покажи ошибку","inspection",0)
            make_vintage_sound_track(path,[cue],9.)
            with wave.open(str(path),"rb") as a:
                self.assertEqual(a.getnchannels(),1)
                self.assertEqual(a.getframerate(),24000)
                raw=a.readframes(a.getnframes())
            self.assertGreater(len(set(raw)),60)
            self.assertGreater(len(raw),200000)
            self.assertLess(max(raw),256)

    def test_animated_scene_is_full_frame_and_fades_with_cinematic_texture(self):
        with tempfile.TemporaryDirectory() as tmp:
            cue=VintageCue(6.,7.6,"ошибку на ногте","inspection",0)
            pattern,count=render_vintage_scene(Path(tmp),cue,0)
            self.assertGreaterEqual(count,15)
            first=Image.open(pattern % 0).convert("RGBA")
            middle=Image.open(pattern % (count//2)).convert("RGBA")
            self.assertEqual(middle.size,(720,1280))
            self.assertEqual(first.getpixel((360,600))[3],0)
            self.assertEqual(middle.getpixel((360,600))[3],255)
            self.assertNotEqual(middle.getpixel((100,300)),middle.getpixel((360,600)))

    def test_vintage_cannot_be_skipped_when_other_sounds_are_disabled(self):
        renderer=(Path(__file__).parent/"reels_effects.py").read_text("utf-8")
        self.assertIn("and not retro and not vintage_cues and not motion_cues",renderer)
        self.assertIn('cues=([] if insert_style=="vintage" else',renderer)

    def test_all_archive_themes_have_original_drawn_props(self):
        from vintage_cinema import _scene_image, THEMES
        for theme,_ in THEMES:
            frame=_scene_image(VintageCue(6.,8.,"настоящая фраза",theme,0),4,0)
            self.assertEqual(frame.size,(720,1280))
            self.assertNotEqual(frame.getpixel((360,375)),frame.getpixel((30,375)))

    def test_ui_and_renderer_use_the_same_vintage_contract(self):
        root=Path(__file__).parent
        html=(root/"index.html").read_text("utf-8")
        worker=(root/"cloudflare_launcher.js").read_text("utf-8")
        renderer=(root/"reels_effects.py").read_text("utf-8")
        for expected in ['value="vintage_cinema"', "insert_style:s.motionInserts?(s.captionVariant==='vintage'?'vintage':'reference_soft')"]:
            self.assertIn(expected,html)
        self.assertIn('insert_style:"off reference_soft retro old_money vintage',worker)
        self.assertIn("render_vintage_scene",renderer)
        self.assertIn("make_vintage_sound_track",renderer)
        vintage=video_filter_chain("vintage")
        for expected in ("noise=","vignette=","colorbalance="):
            self.assertIn(expected,vintage)

if __name__=="__main__":
    unittest.main()
