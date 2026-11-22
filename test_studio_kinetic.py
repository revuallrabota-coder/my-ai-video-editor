"""Regression: animated video inserts and audible caption/transition SFX.

This uses a synthetic source video and does not require Telegram credentials.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from studio_kinetic import select_studio_cues
from reels_effects import make_sfx_track, apply_effects


WORDS=[
    (.12,.31,"Начинаем"),(.37,.65,"обсуждение"),(.7,1.0,"сегодня"),
    (2.72,3.02,"Посмотри"),(3.09,3.35,"какой"),(3.41,3.80,"маникюр"),
    (5.25,5.55,"Сейчас"),(5.62,5.91,"покажу"),(5.97,6.30,"почему"),
    (7.05,7.32,"Будет"),(7.39,7.70,"красиво"),
]


class StudioKineticTests(unittest.TestCase):
    def test_cues_follow_speech_and_keep_real_words(self):
        for frequency in ("subtle","balanced","dynamic"):
            cues=select_studio_cues(WORDS,9.5,frequency)
            self.assertTrue(cues,frequency)
            self.assertTrue(all(c.start>=2.4 and c.end<=9.5 for c in cues))
            spoken={"".join(x for x in text.upper() if x.isalpha())
                    for _,_,text in WORDS}
            self.assertTrue(all("".join(x for x in cue.label if x.isalpha()) in spoken
                                for cue in cues))
        self.assertEqual(select_studio_cues(WORDS,9.5,"subtle"),
                         select_studio_cues(WORDS,9.5,"subtle"))

    def test_typewriter_and_whoosh_generate_different_non_silent_audio(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            out=[]
            for style in ("caption_typewriter","whoosh"):
                file=root/(style+".wav")
                make_sfx_track(file,[(.5,None),(2.6,None)],3.5,style)
                with wave.open(str(file),"rb") as track:
                    self.assertEqual(track.getframerate(),48000)
                    samples=track.readframes(track.getnframes())
                self.assertTrue(any(samples),style)
                out.append(samples)
            self.assertNotEqual(out[0],out[1])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "FFmpeg required for integration render")
    def test_real_portrait_output_with_moving_insert_and_sfx(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            video=root/"input.mp4"
            output=root/"output.mp4"
            subprocess.run([
                "ffmpeg","-v","error","-y",
                "-f","lavfi","-i","testsrc2=size=360x640:rate=30:duration=9.5",
                "-f","lavfi","-i","sine=frequency=370:duration=9.5",
                "-c:v","libx264","-preset","ultrafast",
                "-c:a","aac","-shortest",str(video)
            ],capture_output=True,check=True,timeout=60)
            stats=apply_effects(
                video,output,WORDS,
                sound="soft",emoji="off",
                caption_position="top",quality="balanced",
                caption_sound="typewriter",
                insert_style="reference_soft",
                insert_density="balanced",insert_sound="on",
                studio_mode=True,studio_scene="burgundy_brown",
                insert_source=video,
            )
            self.assertTrue(output.is_file() and output.stat().st_size>1000)
            self.assertGreater(stats.get("insert_count",0),0)
            self.assertGreater(stats.get("caption_sfx_count",0),0)
            self.assertGreater(stats.get("insert_sfx_count",0),0)
            probe=subprocess.run([
                "ffprobe","-v","error","-show_entries",
                "stream=codec_type,width,height","-of","csv=p=0",str(output)
            ],capture_output=True,text=True,check=True,timeout=15).stdout
            self.assertIn("video,360,640",probe)
            self.assertIn("audio",probe)


if __name__=="__main__":
    unittest.main()
