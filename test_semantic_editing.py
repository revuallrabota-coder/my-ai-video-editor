"""Meaning-aware effects and private user-owned pack integration tests."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from zipfile import ZipFile

from semantic_editing import choose_semantic_cues,plan_for_editorial_scenes
from private_effect_assets import prepare_private_effect_assets
from reels_effects import apply_effects
from telegram_editor import duration_and_audio


class SemanticMontageTests(unittest.TestCase):
    def test_generic_topic_does_not_trigger_cute_but_unrelated_sticker(self):
        words=[(2.8,3.1,"маникюр"),(3.4,3.8,"клиентка"),
               (4.1,4.7,"пришла"),(5.2,5.7,"сегодня")]
        self.assertEqual(choose_semantic_cues(words,8),[])
        self.assertEqual(plan_for_editorial_scenes(words,8),[])

    def test_find_error_chooses_inspection_not_arbitrary_sticker(self):
        words=[(2.7,3.0,"Найди"),(3.1,3.5,"ошибку"),
               (3.65,3.95,"в"),(4.0,4.55,"маникюре")]
        cues=choose_semantic_cues(words,8)
        self.assertEqual(len(cues),1)
        self.assertEqual(cues[0].kind,"inspect")
        self.assertAlmostEqual(cues[0].start,2.7,delta=.2)

    def test_comparison_selects_collage_instead_of_automatic_tv(self):
        words=[(4.7,5.0,"сравним"),(5.2,5.4,"два"),
               (5.7,6.2,"варианта")]
        result=choose_semantic_cues(words,8)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].kind,"compare")
        scenes=plan_for_editorial_scenes(words,8)
        self.assertEqual(len(scenes),1)

    def test_no_false_alarm_for_negated_error(self):
        words=[(2.8,3.0,"здесь"),(3.1,3.4,"нет"),
               (3.5,3.8,"ошибки"),(4.0,4.4,"покрытия")]
        self.assertEqual(choose_semantic_cues(words,8),[])

    def test_semantic_edits_are_sparse_and_reproducible(self):
        words=[]
        for i,token in enumerate([
            "посмотри","ошибку","покрытия","сравним","варианта",
            "результат","ошибка","неправильно","сейчас","покажу",
            "следующий","кадр","попробуем","ошибку","финальную",
            "результат","проверим","покрытие","быстро","минуты"
        ]):
            words.append((3.0+i*.8,3.35+i*.8,token))
        a=choose_semantic_cues(words,25,"dynamic")
        b=choose_semantic_cues(words,25,"dynamic")
        self.assertEqual(a,b)
        self.assertLessEqual(len(a),8)
        self.assertTrue(all(y.start-x.start>=6.7 for x,y in zip(a,a[1:])))

    def test_archive_pack_is_safe_and_only_media_used(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            pack=root/"assets.zip"
            # A tiny mock of the user's pack, not a redistributed template.
            with ZipFile(pack,"w") as z:
                z.writestr("Free Animated Icon Sets/Pre-Rendered Footage/X.mov",
                           bytes(range(256))*24)
                z.writestr("../../PB - Free Camera Shake Presets/35mm_HeavyMovement.ffx",
                           b"NOT_A_FFMPEG_VIDEO")
                z.writestr("PB - 21 Motion Graphics For Premiere/1.mogrt",
                           b"NOT_AN_FFMPEG_VIDEO")
                z.writestr("Trailer_Construction_Lite_Version/0026_slam 4.wav",
                           bytes(range(256))*30)
            assets=prepare_private_effect_assets([pack],root/"out")
            self.assertEqual(assets.selected_files,2)
            self.assertEqual(assets.ignored_adobe_presets,2)
            self.assertEqual(assets.icons["error"].stat().st_size,6144)
            self.assertEqual(assets.sounds["error"].stat().st_size,7680)
            self.assertEqual(len(list((root/"out").glob("*.ffx"))),0)

    def test_ffmpeg_overlays_opted_in_mov_without_damaging_voice(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=root/"speech.mp4"
            icon=root/"X.mov"
            done=root/"edited.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=s=240x426:r=12:d=5.8",
                "-f","lavfi","-i","sine=frequency=340:duration=5.8",
                "-c:v","libx264","-preset","ultrafast",
                "-c:a","aac","-shortest",str(source)
            ],check=True,capture_output=True,timeout=90)
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=black@0.0:s=96x96:r=12:d=1.8",
                "-vf","format=argb,drawbox=x=18:y=18:w=60:h=60:color=red@1:t=fill",
                "-c:v","qtrle",str(icon)
            ],check=True,capture_output=True,timeout=60)
            sound=root/"sample.wav"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","sine=frequency=180:duration=1",
                "-c:a","pcm_s16le",str(sound)
            ],check=True,capture_output=True,timeout=30)
            from private_effect_assets import PrivateAssets
            assets=PrivateAssets(icons={"error":icon},
                                 sounds={"error":sound})
            # A strong explicit error cue, well after the opening title.
            words=[(2.7,3.1,"вот"),(3.15,3.6,"ошибка"),
                   (3.7,4.15,"покрытия")]
            result=apply_effects(
                source,done,words,emoji="off",sound="off",
                caption_sound="off",insert_style="reference_soft",
                insert_density="subtle",insert_sound="on",
                quality="balanced",private_assets=assets
            )
            self.assertEqual(result["private_asset_count"],1)
            self.assertEqual(result["semantic_cue_count"],1)
            self.assertEqual(result["insert_sfx_count"],1)
            self.assertEqual(result["insert_count"],1)
            seconds,audio=duration_and_audio(done)
            self.assertTrue(audio)
            self.assertTrue(5.4<seconds<6.1)
            self.assertGreater(done.stat().st_size,10000)


if __name__=="__main__":
    unittest.main()
