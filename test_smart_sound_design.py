"""UI sound modes and semantically mapped, aesthetic-specific sound layers."""
from __future__ import annotations
import tempfile
import unittest
import wave
from pathlib import Path
from guide18_fx import GuideCue, sound_family, sound_track

class SmartSoundDesignTests(unittest.TestCase):
    def test_semantic_visuals_have_matching_distinct_audio(self):
        expected={
            "pov_carousel_spin":"pages",
            "image_cluster_reel":"photo",
            "split_reel":"compare",
            "match_cut":"emphasis",
            "glass_explainer_reel":"glass",
            "apple_ui_toggles":"steps",
            "liquid_glass_graph":"graph",
            "notification_stack":"notify",
        }
        for effect,family in expected.items():
            self.assertEqual(sound_family(effect),family)
        self.assertEqual(len(set(expected.values())),8)

    def test_rendered_semantic_cues_sound_different(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/"semantic_sfx.wav"
            cues=[
                GuideCue("pov_carousel_spin",.45,1.2,"МНОГО",compact=True),
                GuideCue("split_reel",1.6,2.6,"СРАВНИМ",compact=True),
                GuideCue("match_cut",3.1,3.8,"ГЛАВНОЕ",compact=True),
            ]
            sound_track(output,cues,5.0,style="burgundy")
            with wave.open(str(output),"rb") as reader:
                self.assertEqual(reader.getnchannels(),1)
                self.assertEqual(reader.getframerate(),48000)
                all_frames=reader.readframes(reader.getnframes())
            self.assertEqual(len(all_frames),5*48000*2)
            fragments=[
                all_frames[int(t*48000)*2:int((t+.12)*48000)*2]
                for t in (.45,1.6,3.1)
            ]
            self.assertEqual(len(set(fragments)),3)
            self.assertTrue(all(any(value!=0 for value in clip) for clip in fragments))

    def test_same_visual_has_different_style_timbre(self):
        with tempfile.TemporaryDirectory() as folder:
            cues=[GuideCue("glass_explainer_reel",.5,1.2,"ПОЧЕМУ")]
            files=[]
            for style in ("pink_tender","old_money","burgundy","vintage"):
                target=Path(folder)/f"{style}.wav"
                sound_track(target,cues,2,style=style)
                files.append(target.read_bytes())
            self.assertEqual(len(set(files)),4)

    def test_miniapp_has_single_primary_audio_choice(self):
        root=Path(__file__).parent
        page=(root/"index.html").read_text(encoding="utf-8")
        renderer=(root/"reels_effects.py").read_text(encoding="utf-8")
        self.assertIn('<select id="soundDesign">',page)
        self.assertIn('<option value="auto" selected>',page)
        self.assertIn('<details id="soundDesignDetails" hidden>',page)
        self.assertIn("if(mode==='auto')return {keywords:'off',captions:'soft',inserts:true};",page)
        self.assertIn('Референс: разные деликатные звуки появления фраз',page)
        self.assertIn("if(mode==='off')return {keywords:'off',captions:'off',inserts:false};",page)
        self.assertIn("guide_audio(audio,soundtrack_events,duration,style=insert_style)",renderer)
        # Changing the visual preset must not turn on typewriter audio
        self.assertNotIn("byId('subtitleSfx').value='typewriter';",page)
        self.assertNotIn("byId('assetSfx').checked=true;",page)

if __name__=="__main__":
    unittest.main()
