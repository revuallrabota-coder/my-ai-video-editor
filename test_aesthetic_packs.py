"""Regression tests for independent aesthetic packs and real-media fallback."""
from __future__ import annotations
import os
import tempfile
import unittest
import wave
from pathlib import Path
from PIL import Image
from aesthetic_fx import (select_mood_cues,render_mood_card,
                          make_mood_sound_track,resolve_mood_asset)

class AestheticPacksTest(unittest.TestCase):
    def test_pink_and_burgundy_semantics_and_no_random_stickers(self):
        words=[(0.1,.3,"бант"),(5.,5.2,"жемчуг"),
               (14.,14.3,"розы"),(24.,24.4,"сердце")]
        pink=select_mood_cues(words,30,"pink_tender","balanced")
        self.assertEqual([c.symbol for c in pink],["pearl","flower","heart"])
        self.assertEqual(select_mood_cues([(6,6.3,"кадры")],22,
                                         "pink_tender"),[])
        burgundy=select_mood_cues([(5,5.3,"вишня"),(15,15.2,"сургуч")],
                                 25,"burgundy","balanced")
        self.assertEqual([c.symbol for c in burgundy],["cherry","seal"])
        with self.assertRaises(ValueError):
            select_mood_cues(words,32,"unknown","balanced")

    def test_cards_and_separate_audio_are_real_and_not_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for style,theme in (("pink_tender","pearl"),("burgundy","seal")):
                card=p/(style+".png")
                render_mood_card(card,"образ",theme,style)
                with Image.open(card) as im:
                    self.assertEqual(im.size,(480,382))
                    self.assertEqual(im.mode,"RGBA")
                    self.assertGreater(len(im.getcolors(1000000) or []),15)
            cues=select_mood_cues([(5.,5.3,"бант")],15,"pink_tender")
            sound1=p/"pink.wav";sound2=p/"wine.wav"
            make_mood_sound_track(sound1,cues,9,"pink_tender")
            make_mood_sound_track(sound2,cues,9,"burgundy")
            with wave.open(str(sound1),"rb") as f:
                self.assertEqual(f.getframerate(),24000)
                self.assertEqual(f.getnchannels(),1)
            self.assertNotEqual(sound1.read_bytes(),sound2.read_bytes())

    def test_licensed_clips_are_local_private_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous=os.environ.get("PRIVATE_STYLE_ASSETS_DIR")
            try:
                os.environ["PRIVATE_STYLE_ASSETS_DIR"]=tmp
                target=Path(tmp)/"pink_tender"/"flower.mp4"
                target.parent.mkdir()
                target.write_bytes(b"x"*128)
                self.assertEqual(resolve_mood_asset("pink_tender","flower","mp4"),target)
                self.assertIsNone(resolve_mood_asset("burgundy","flower","mp4"))
                self.assertIsNone(resolve_mood_asset("pink_tender","../flower","mp4"))
            finally:
                if previous is None:os.environ.pop("PRIVATE_STYLE_ASSETS_DIR",None)
                else:os.environ["PRIVATE_STYLE_ASSETS_DIR"]=previous

    def test_frontend_worker_and_renderer_use_same_style_contract(self):
        root=Path(__file__).parent
        html=(root/"index.html").read_text("utf-8")
        worker=(root/"cloudflare_launcher.js").read_text("utf-8")
        ipad=(root/"cloudflare_launcher_ipad.txt").read_text("utf-8")
        effects=(root/"reels_effects.py").read_text("utf-8")
        self.assertIn('value="pink_tender"',html)
        self.assertIn("s.reelsPreset==='burgundy_brown_talk'?'burgundy'",html)
        self.assertIn("s.reelsPreset==='pink_tender'?'pink_tender'",html)
        self.assertIn("const CONTRACT = 5;",worker)
        self.assertEqual(worker,ipad)
        self.assertIn('accepted_insert_style:settings.insert_style',worker)
        self.assertIn("select_mood_cues",effects)
        self.assertIn("resolve_mood_asset",effects)
        self.assertIn("make_mood_sound_track",effects)

if __name__=="__main__":
    unittest.main()
