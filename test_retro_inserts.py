"""Проверки винтажных вставок и синхронных звуков, в том числе FFmpeg."""
from __future__ import annotations
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from PIL import Image
from reels_effects import apply_effects
from retro_inserts import (
    choose_retro_cues, make_retro_card, make_retro_sound_track,
)
from telegram_editor import duration_and_audio


class RetroInsertsTests(unittest.TestCase):
    WORDS = [
        (0.20,0.43,"Сегодня"), (0.62,1.01,"маникюр"),
        (1.30,1.61,"снимаю"), (2.15,2.55,"видео"),
        (3.40,3.80,"результат"), (4.70,5.03,"интересный"),
    ]

    def test_keyword_match_and_pacing(self):
        cues = choose_retro_cues(self.WORDS, 8, density="dynamic")
        self.assertGreaterEqual(len(cues), 1)
        self.assertEqual(cues[0].label, "МАНИКЮР")
        self.assertEqual(cues[0].symbol, "💅")
        for a,b in zip(cues,cues[1:]):
            self.assertGreaterEqual(b.time-a.time,3.5)
        self.assertEqual(
            choose_retro_cues([(0.1,0.4,"привет")],4),
            []
        )
        with self.assertRaises(ValueError):
            choose_retro_cues(self.WORDS,8,density="loud")

    def test_original_card_has_alpha_and_is_not_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"retro.png"
            make_retro_card(path,"МАНИКЮР","💅")
            with Image.open(path) as im:
                self.assertEqual(im.size,(480,382))
                self.assertEqual(im.mode,"RGBA")
                self.assertEqual(im.getpixel((0,0))[3],0)
                self.assertGreater(im.getpixel((200,180))[3],0)

    def test_every_caption_style_generates_distinct_cutaway(self):
        from retro_inserts import CARD_STYLES
        expected=("old_money","vintage","elegant","street","editorial",
                  "minimal","neon","pop","luxe","retro")
        self.assertTrue(all(style in CARD_STYLES for style in expected))
        with tempfile.TemporaryDirectory() as td:
            appearances=[]
            for style in expected:
                output=Path(td)/(style+".png")
                make_retro_card(output,"РЕЗУЛЬТАТ","🏆",style=style)
                with Image.open(output) as im:
                    self.assertEqual(im.size,(480,382))
                    self.assertEqual(im.mode,"RGBA")
                    appearances.append(im.getpixel((40,80)))
            self.assertGreaterEqual(len(set(appearances)),6)

    def test_new_reference_cutaway_is_original_half_frame_graphic(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"reference_motion.png"
            make_retro_card(output,"МОНТАЖ","🎬",style="reference_soft")
            with Image.open(output) as im:
                self.assertEqual(im.size,(480,382))
                self.assertEqual(im.getpixel((0,0))[3],0)
                self.assertGreater(im.getpixel((240,180))[3],0)

    def test_thematic_sound_not_silent(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"sound.wav"
            cues=choose_retro_cues(self.WORDS,8)
            make_retro_sound_track(path,cues,8)
            with wave.open(str(path),"rb") as track:
                self.assertEqual(track.getnchannels(),1)
                self.assertEqual(track.getframerate(),48000)
                self.assertGreater(track.getnframes(),300000)
                content=track.readframes(track.getnframes())
                self.assertNotEqual(set(content),{0})

    def test_real_ffmpeg_cutaway_and_sfx_keep_original_voice(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            source=folder/"source.mp4"
            output=folder/"output.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=#1c342e:s=480x854:r=15:d=2.7",
                "-f","lavfi","-i","sine=frequency=220:duration=2.7",
                "-c:v","libx264","-preset","ultrafast",
                "-c:a","aac","-shortest",str(source)
            ],check=True,timeout=90,capture_output=True)
            stats=apply_effects(
                source,output,[(0.55,1.25,"маникюр"),(1.35,1.7,"сегодня")],
                sound="off",emoji="off",caption_sound="off",
                insert_style="retro",insert_density="dynamic",insert_sound="on",
                quality="balanced",
            )
            self.assertEqual(stats["insert_count"],1)
            self.assertEqual(stats["insert_sfx_count"],1)
            duration,audio=duration_and_audio(output)
            self.assertTrue(audio)
            self.assertTrue(2.3<duration<2.9)
            self.assertGreater(output.stat().st_size,10000)


if __name__=="__main__":
    unittest.main()
