"""Smart montage contract: one effect per meaning, no roulette."""
from __future__ import annotations
import unittest
from pathlib import Path
from PIL import Image, ImageChops
from guide18_fx import SMART_EFFECTS, _compact_frame, plan

class SmartSemanticMontageTests(unittest.TestCase):
    def test_many_options_outranks_show_photos_in_same_phrase(self):
        speech=[(1,1.3,"Привет"),(5.0,5.3,"Покажу"),
                (5.6,5.9,"много"),(6.1,6.4,"вариантов")]
        cues=plan(speech,24,"auto")
        self.assertEqual(len(cues),1)
        self.assertEqual(cues[0].effect,"pov_carousel_spin")
        self.assertEqual(cues[0].label,"МНОГО")
        self.assertFalse(cues[0].compact)
        self.assertFalse(cues[0].required)  # Automatic but cinematic cutaway.

    def test_selected_favorites_are_required_not_keyword_lottery(self):
        speech=[(5.1,5.4,"много"),(15.5,15.9,"главное"),
                (25.,25.4,"сравним"),(35.,35.4,"объясню")]
        cues=plan(speech,45,"multi:pov_carousel_spin,match_cut","dynamic")
        self.assertEqual([c.effect for c in cues],
                         ["pov_carousel_spin","match_cut"])
        self.assertTrue(all(c.required for c in cues))
        self.assertFalse(cues[0].compact)  # Manual carousel must be fullscreen.
        # No trigger words, but the user CHECKED both boxes.
        mandatory=plan([(5,5.4,"клиент")],14,
                       "multi:pov_carousel_spin,match_cut")
        self.assertEqual([c.effect for c in mandatory],
                         ["pov_carousel_spin","match_cut"])
        self.assertTrue(all(c.start>=4 for c in mandatory))
        self.assertTrue(all(y.start>x.end for x,y in zip(mandatory,mandatory[1:])))
        with self.assertRaises(ValueError):
            plan(speech,45,"multi:match_cut,match_cut")
        with self.assertRaises(ValueError):
            plan(speech,45,"multi:__import__('os')")
        with self.assertRaises(ValueError):
            plan(speech,45, "multi:")

    def test_importance_comparison_and_steps_have_distinct_effects(self):
        important=plan([(5,5.3,"Главное")],19,"auto")
        self.assertEqual(important[0].effect,"match_cut")
        pair=plan([(5,5.2,"До"),(5.8,6.2,"и"),
                   (6.5,6.8,"после")],19,"auto")
        self.assertEqual(pair[0].effect,"split_reel")
        self.assertEqual(plan([(5,5.2,"До"),(5.3,5.5,"пяти"),
                               (5.6,5.9,"секунд")],19,
                              "auto"),[])
        self.assertEqual([c.effect for c in plan(
            [(5,5.2,"До"),(5.3,5.5,"пяти"),(5.6,5.9,"секунд")],
            19,"multi:split_reel")],["split_reel"])
        steps=plan([(5,5.3,"Сначала"),(7,7.3,"затем")],20,"auto")
        self.assertEqual(steps[0].effect,"apple_ui_toggles")
        self.assertEqual(plan([(5,5.4,"Сначала"),(6,6.4,"поговорим")],
                              15,"auto"),[])

    def test_first_four_seconds_and_spacing(self):
        speech=[(0,.4,"Главное"),(4.4,4.6,"важное"),
                (7,7.3,"много"),(16.,16.4,"вариантов"),
                (26,26.4,"результат")]
        cues=plan(speech,33,"auto","dynamic")
        self.assertTrue(all(c.start>=4 and c.end<=33 for c in cues))
        self.assertTrue(all(y.start-x.end>=1. for x,y in zip(cues,cues[1:])))
        self.assertEqual(cues,plan(speech,33,"auto","dynamic"))

    def test_compact_effect_frames_look_distinct_and_protect_speaker(self):
        mask=Image.new("L",(720,1280),0)
        clips=[Image.new("RGB",(360,640),(color,80,120))
               for color in (30,110,215)]
        a=_compact_frame("МНОГО",.35,mask,(36,245),"middle",
                         effect="pov_carousel_spin",clips=clips,
                         palette="burgundy")
        b=_compact_frame("ВАЖНО",.35,mask,(36,245),"middle",
                         effect="match_cut",clips=clips,
                         palette="burgundy")
        self.assertIsNotNone(
            ImageChops.difference(a,b).convert('RGB').getbbox())
        self.assertEqual(a.size,(720,1280))
        self.assertEqual(a.getpixel((0,0))[3],0)

    def test_frontend_worker_and_render_validation_match(self):
        root=Path(__file__).parent
        ui=(root/"index.html").read_text("utf-8")
        worker=(root/"cloudflare_launcher.js").read_text("utf-8")
        ipad=(root/"cloudflare_launcher_ipad.txt").read_text("utf-8")
        renderer=(root/"reels_effects.py").read_text("utf-8")
        delivery=(root/"process_uploaded_video.py").read_text("utf-8")
        self.assertNotIn('12 эффектов + 6 стилей',ui)
        self.assertNotIn('<select id="guideEffect">',ui)
        self.assertIn('id="smartFxMode"',ui)
        self.assertIn('name="preferredGuideFx"',ui)
        for effect in SMART_EFFECTS:
            self.assertIn(f'value="{effect}"',ui)
        self.assertIn("'multi:'+selected.join(',')",ui)
        self.assertIn("var manualFx=s.guideEffect.startsWith('multi:')",ui)
        self.assertIn("required: bool = False", (root/"guide18_fx.py").read_text("utf-8"))
        self.assertNotIn("byId('reelsPreset').value='custom';",ui)
        self.assertIn("const CONTRACT = 7;",worker)
        self.assertEqual(worker,ipad)
        self.assertIn("validateGuideEffect(s.guide_effect)",worker)
        self.assertIn("retro=[cue for cue in retro if unoccupied",renderer)
        self.assertIn('not selected_guide.startswith("multi:")',delivery)

if __name__=="__main__":
    unittest.main()
