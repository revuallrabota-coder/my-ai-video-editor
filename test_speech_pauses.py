"""Tight pauses, spoken-word protection and pitch-preserving ×1.2 timing."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from telegram_editor import get_speech_keep_ranges,Segment,base_video,duration_and_audio
from speech_review import map_words_to_ranges


class SpeechPauseTests(unittest.TestCase):
    def test_strong_removal_does_not_clip_words_and_maps_timestamps(self):
        words=[(.15,.42,"Найди"),(.48,.81,"ошибку"),
               (1.75,2.18,"сегодня"),(2.25,2.52,"здесь")]
        kept=get_speech_keep_ranges(words,2.75,mode="tight")
        self.assertGreaterEqual(len(kept),2)
        trimmed=sum(x.end-x.start for x in kept)
        self.assertLess(trimmed,2.5)
        self.assertGreater(trimmed,1.5)
        mapped=map_words_to_ranges(words,kept,speed=1.2)
        self.assertEqual([w[2] for w in mapped],[x[2] for x in words])
        self.assertAlmostEqual(mapped[0][0],.15/1.2,delta=.04)
        self.assertLess(mapped[-1][1],2.75/1.2)
        for left,right in zip(kept,kept[1:]):
            self.assertLess(left.end,right.start)

    def test_off_and_gentle_cuts_have_different_effect(self):
        words=[(.1,.45,"Первое"),(1.15,1.50,"второе"),(2.30,2.6,"третье")]
        off=get_speech_keep_ranges(words,2.8,"off")
        gentle=get_speech_keep_ranges(words,2.8,"gentle")
        tight=get_speech_keep_ranges(words,2.8,"tight")
        duration=lambda spans:sum(s.end-s.start for s in spans)
        self.assertEqual(duration(off),2.8)
        self.assertGreater(duration(gentle),duration(tight))
        self.assertGreaterEqual(duration(gentle),duration(tight))

    def test_real_ffmpeg_cut_plus_12x_keeps_voice_and_caption_timeline(self):
        with tempfile.TemporaryDirectory(prefix="tight_talk_") as d:
            folder=Path(d)
            source=folder/"with_gaps.mp4"
            out=folder/"faster.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=blue:s=180x320:r=15:d=3",
                "-f","lavfi","-i","sine=frequency=440:duration=1",
                "-f","lavfi","-i","anullsrc=r=44100:cl=mono:d=1",
                "-f","lavfi","-i","sine=frequency=510:duration=1",
                "-filter_complex","[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]",
                "-map","0:v:0","-map","[a]",
                "-c:v","libx264","-preset","ultrafast","-c:a","aac",
                "-shortest",str(source)
            ],capture_output=True,check=True,timeout=90)
            words=[(.20,.85,"Первая"),(2.08,2.80,"Вторая")]
            ranges=get_speech_keep_ranges(words,3.0,"tight")
            base_video(source,out,ranges,True,speed=1.2,quality="balanced",
                       audio_profile="off")
            before,_=duration_and_audio(source)
            after,has_audio=duration_and_audio(out)
            expected=sum(s.end-s.start for s in ranges)/1.2
            self.assertTrue(has_audio)
            self.assertAlmostEqual(after,expected,delta=.13)
            self.assertLess(after,before*.8)


if __name__=="__main__":
    unittest.main()
