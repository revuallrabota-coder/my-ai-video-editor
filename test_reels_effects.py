"""Small FFmpeg tests for real hook backdrop, original sfx and emoji PNG."""
from __future__ import annotations

import tempfile
import unittest
import wave
import subprocess
from pathlib import Path

from reels_effects import (
    add_hook_to_ass, apply_effects, emoji_image, make_sfx_track,
    pick_cues, validate_effects
)
from telegram_editor import duration_and_audio
from word_captions import build_word_pop_ass


class ReelsEffectsTests(unittest.TestCase):
    WORDS=[(0.1,0.32,"Здесь"),(0.45,0.8,"важная"),
           (1.01,1.36,"ошибка"),(1.7,2.02,"маникюра")]

    def test_sound_cues_and_silent_modes(self) -> None:
        cues=pick_cues(self.WORDS,4)
        self.assertGreaterEqual(len(cues),1)
        self.assertEqual(cues[0][1],"❗")
        validate_effects("soft","on","end")
        with self.assertRaises(ValueError):
            validate_effects("illegal","on","start")

    def test_hook_is_at_end_and_has_backplate(self) -> None:
        ass,_=build_word_pop_ass(self.WORDS)
        complete=add_hook_to_ass(
            ass,"НАЙДИ ОШИБКУ",position="end",duration=10,
            color="#EBC0C8",
        )
        self.assertIn("Style: HookPlate",complete)
        self.assertIn("Style: ReelsHook",complete)
        self.assertIn(r"\p1",complete)
        self.assertIn("0:00:10.00",complete)
        self.assertIn("НАЙДИ ОШИБКУ",complete)
        self.assertEqual(complete.count("Dialogue: 4,"),1)
        both=add_hook_to_ass(ass,"ПОСМОТРИ",position="both",duration=12,
                             color="#EBC0C8")
        self.assertEqual(both.count("Dialogue: 4,"),2)

    def test_generated_sfx_wav_is_short_pop_not_silence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sfx_") as tmp:
            path=Path(tmp)/"accent.wav"
            make_sfx_track(path,[(.4,"❗")],1.7,"soft")
            with wave.open(str(path),"rb") as wav:
                self.assertEqual(wav.getnchannels(),1)
                self.assertEqual(wav.getframerate(),48000)
                self.assertGreater(wav.getnframes(),80000)
                audio=wav.readframes(wav.getnframes())
            self.assertNotEqual(set(audio),{0})

    def test_actual_ffmpeg_audio_mix_and_emoji_overlay(self) -> None:
        # Rendering test on synthetic media: avoids access to personal videos.
        with tempfile.TemporaryDirectory(prefix="render_effects_") as tmp:
            root=Path(tmp)
            source=root/"original.mp4"
            output=root/"result.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=#1e2630:s=720x1280:r=15:d=2.7",
                "-f","lavfi","-i","sine=frequency=440:duration=2.7",
                "-c:v","libx264","-preset","ultrafast",
                "-c:a","aac","-shortest",str(source),
            ],check=True,capture_output=True,timeout=90)
            selected=[
                (0.1,0.35,"Сегодня"),
                (0.8,1.4,"ошибка"),
                (1.42,1.8,"маникюра"),
            ]
            counts=apply_effects(
                source,output,selected,sound="soft",emoji="on",
                caption_position="middle",
            )
            self.assertGreaterEqual(counts["emoji_count"],1)
            self.assertGreaterEqual(counts["sfx_count"],1)
            sec,has_sound=duration_and_audio(output)
            self.assertTrue(has_sound)
            self.assertGreater(sec,2.35)
            self.assertLess(sec,2.85)
            self.assertGreater(output.stat().st_size,10000)


if __name__=="__main__":
    unittest.main()
