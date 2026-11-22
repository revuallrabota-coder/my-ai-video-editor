"""Regression coverage for full-screen talking reels and actual selected FX."""
from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from reels_effects import make_sfx_track
from studio_kinetic import select_studio_cues, make_studio_card, make_studio_keyword_asset
from talking_scene_styles import render_scene


def spoken_words(seconds: float = 9.5):
    vocabulary=["Сегодня","посмотрим","одну","интересную","работу",
                "а","затем","разберём","ошибку","подробнее"]
    rows=[]
    for i in range(int(seconds/.32)):
        start=i*.32
        rows.append((start,start+.27,vocabulary[i%len(vocabulary)]))
    return rows


class DynamicReelsTests(unittest.TestCase):
    def test_studio_cues_come_from_speech_and_follow_density(self):
        words=spoken_words(45)
        selected={name:select_studio_cues(words,45,name)
                  for name in ("subtle","balanced","dynamic")}
        self.assertGreaterEqual(len(selected["dynamic"]),3)
        self.assertGreaterEqual(len(selected["dynamic"]),len(selected["balanced"]))
        self.assertGreaterEqual(len(selected["balanced"]),len(selected["subtle"]))
        actual={w.upper() for _,_,w in words}
        for cue in selected["dynamic"]:
            self.assertIn(cue.label,actual)
            self.assertGreater(cue.end,cue.start)
        self.assertEqual(select_studio_cues([],45),[])

    def test_typewriter_and_whoosh_are_audible_not_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            for intensity in ("caption_typewriter","whoosh"):
                path=Path(tmp)/(intensity+".wav")
                make_sfx_track(path,[(.3,None),(1.2,None)],2.0,intensity)
                with wave.open(str(path),"rb") as wav:
                    self.assertEqual(wav.getnchannels(),1)
                    self.assertEqual(wav.getframerate(),48000)
                    samples=wav.readframes(wav.getnframes())
                self.assertGreater(max(samples),0)
                self.assertGreater(len(set(samples)),40)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "FFmpeg needed for real encoder test")
    def test_real_portrait_and_moving_inserts_with_speech(self):
        from reels_effects import apply_effects
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            source=folder/"clean.mp4"
            composed=folder/"full_frame.mp4"
            rendered=folder/"animated.mp4"
            # High-contrast frame and audible speech proxy to test video/audio
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=s=360x640:r=12:d=9.5",
                "-f","lavfi","-i","sine=frequency=225:duration=9.5",
                "-c:v","libx264","-preset","ultrafast","-c:a","aac",
                "-shortest",str(source)
            ],check=True,capture_output=True,timeout=80)
            render_scene(source,composed,"burgundy_brown",quality="balanced")
            words=spoken_words()
            stats=apply_effects(
                composed,rendered,words,
                sound="soft",emoji="off",caption_sound="typewriter",
                insert_style="reference_soft",insert_density="dynamic",
                insert_sound="on",studio_mode=True,
                studio_scene="burgundy_brown",
                insert_source=source,quality="balanced"
            )
            self.assertTrue(rendered.is_file() and rendered.stat().st_size>5000)
            self.assertGreaterEqual(stats["insert_count"],2)
            self.assertGreaterEqual(stats["kinetic_word_count"],1)
            self.assertGreaterEqual(stats["insert_sfx_count"],1)
            self.assertGreaterEqual(stats["caption_sfx_count"],1)
            probe=subprocess.run([
                "ffprobe","-v","quiet",
                "-show_entries","stream=codec_type,width,height",
                "-of","json",str(rendered)
            ],check=True,capture_output=True,text=True,timeout=20)
            import json
            streams=json.loads(probe.stdout)["streams"]
            video=next(s for s in streams if s["codec_type"]=="video")
            self.assertEqual((video["width"],video["height"]),(720,1280))
            self.assertTrue(any(s["codec_type"]=="audio" for s in streams))

    def test_settings_are_forwarded_in_every_studio_mode(self):
        root=Path(__file__).parent
        for file in ("reference_editor.py","telegram_editor.py"):
            body=(root/file).read_text("utf-8")
            self.assertIn("insert_style=insert_style,",body)
            self.assertIn("private_assets=private_assets,",body)
            self.assertIn("studio_scene=talk_scene,",body)
            self.assertIn("insert_source=",body)
        html=(root/"index.html").read_text("utf-8")
        worker=(root/"cloudflare_launcher.js").read_text("utf-8")
        self.assertIn('option value="typewriter"',html)
        self.assertIn('<option value="dynamic">',html)
        self.assertIn('id="checkWorkerConnection"',html)
        self.assertIn('studio-film-overlay',html)
        self.assertIn('id="studioPreviewWord"',html)
        self.assertIn('id="studioInsertVideo"',html)
        self.assertIn('id="videoFilterPreviewStatus"',html)
        self.assertIn("make_studio_keyword_asset",(
            root/"reels_effects.py").read_text("utf-8"))
        self.assertIn('subtitle_sfx:"off soft tick typewriter"',worker)
        self.assertIn('const CONTRACT = 4;',worker)


if __name__=="__main__":
    unittest.main()
