"""Speech-aware hard cuts followed by 1.2x atempo preserve original words."""
from __future__ import annotations
import subprocess
import tempfile
import unittest
from pathlib import Path

from telegram_editor import Segment,base_video,duration_and_audio,get_speech_keep_ranges
from speech_review import map_words_to_ranges


class SpeechCutTests(unittest.TestCase):
    WORDS=[
        (.30,.56,"Сегодня"),(.61,.94,"маникюр"),
        (2.23,2.60,"покажу"),(2.65,2.93,"ошибку"),
        (4.42,4.75,"исправляем"),(4.79,5.08,"её"),
    ]
    def test_tight_removes_interword_pauses_without_cutting_speech(self):
        kept=get_speech_keep_ranges(self.WORDS,5.6,"tight")
        self.assertGreater(len(kept),1)
        self.assertLess(sum(s.end-s.start for s in kept),4.5)
        for a,b,_ in self.WORDS:
            self.assertTrue(any(s.start<=a and s.end>=b for s in kept))
        self.assertEqual(len(get_speech_keep_ranges(self.WORDS,5.6,"off")),1)
        self.assertGreaterEqual(
            sum(s.end-s.start for s in get_speech_keep_ranges(self.WORDS,5.6,"gentle")),
            sum(s.end-s.start for s in kept)
        )

    def test_12x_speed_matches_corrected_word_timestamps(self):
        kept=get_speech_keep_ranges(self.WORDS,5.6,"tight")
        words=map_words_to_ranges(self.WORDS,kept,1.2)
        self.assertEqual(len(words),len(self.WORDS))
        self.assertTrue(all(words[i][0]<=words[i+1][0]
                            for i in range(len(words)-1)))
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"source.mp4"
            output=Path(td)/"edited.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=size=256x456:rate=12:duration=5.6",
                "-f","lavfi","-i","sine=frequency=430:duration=5.6",
                "-c:v","libx264","-preset","ultrafast",
                "-c:a","aac","-shortest",str(source)
            ],check=True,capture_output=True,timeout=60)
            base_video(
                source,output,kept,True,speed=1.2,
                audio_profile="off",quality="balanced"
            )
            seconds,audio=duration_and_audio(output)
            expected=sum(s.end-s.start for s in kept)/1.2
            self.assertAlmostEqual(seconds,expected,delta=.16)
            self.assertTrue(audio)


if __name__=="__main__":
    unittest.main()
