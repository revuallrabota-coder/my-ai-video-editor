"""Reference-style editorial audio must audibly follow caption appearances.

All generated test material is synthetic. No audio is extracted or copied
from the third-party Reels reference.
"""
from __future__ import annotations

import array
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from editorial_caption_sfx import EVENT_LENGTH, render_caption_sounds
from reels_effects import apply_effects, pick_caption_cues, make_sfx_track
from telegram_editor import media_info


class EditorialCaptionAudioTests(unittest.TestCase):
    WORDS=[
        (.6,.85,"Покажу"),(.88,1.10,"пример"),
        (2.0,2.24,"Вот"),(2.3,2.62,"стиль"),
        (3.45,3.7,"Важное"),(3.75,4.03,"слово"),
        (4.9,5.1,"Это"),(5.15,5.49,"красиво"),
        (6.35,6.6,"Теперь"),(6.65,6.91,"следующее"),
    ]

    def test_sounds_follow_phrases_and_not_each_word(self):
        cues=pick_caption_cues(self.WORDS,8,style="soft")
        self.assertEqual(len(cues),5)
        self.assertLess(len(cues),len(self.WORDS))
        self.assertEqual([round(t,2) for t,_ in cues],
                         [.6,2.0,3.45,4.9,6.35])
        self.assertEqual([kind for _,kind in cues],
                         ["air","paper","pop","silk","air"])
        self.assertTrue(all(
            b[0]-a[0]>=.93 for a,b in zip(cues,cues[1:])
        ))

    def test_generated_wav_is_quiet_distinct_and_timed(self):
        cues=[(.5,"air"),(1.5,"paper"),(2.5,"pop"),(3.5,"silk")]
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"original_editorial_sfx.wav"
            render_caption_sounds(target,cues,5.0)
            with wave.open(str(target),"rb") as f:
                self.assertEqual(f.getnchannels(),1)
                self.assertEqual(f.getframerate(),48000)
                samples=array.array("h")
                samples.frombytes(f.readframes(f.getnframes()))
            self.assertEqual(len(samples),5*48000)
            self.assertTrue(all(x==0 for x in samples[:int(.49*48000)]))
            different=[]
            for moment,kind in cues:
                i=int(moment*48000)
                clip=samples[i:i+int(.09*48000)]
                self.assertGreater(max(abs(x) for x in clip),250,
                                   f"{kind} must be noticeable on phone speakers")
                different.append(tuple(clip[::30]))
            self.assertEqual(len(set(different)),4)
            self.assertLess(max(abs(x) for x in samples),32760)

    def test_old_soft_caption_mode_now_renders_editorial_sound(self):
        with tempfile.TemporaryDirectory() as folder:
            destination=Path(folder)/"subtitle_audio.wav"
            cues=pick_caption_cues(self.WORDS,8,style="soft")
            make_sfx_track(destination,cues,8,"caption_soft")
            with wave.open(str(destination),"rb") as f:
                samples=array.array("h")
                samples.frombytes(f.readframes(f.getnframes()))
            self.assertTrue(any(samples[round(.6*48000):round(.8*48000)]))
            self.assertFalse(any(samples[round(1.2*48000):round(1.4*48000)]))

    def test_real_mp4_keeps_voice_and_adds_caption_sound(self):
        with tempfile.TemporaryDirectory(prefix="editorial_audio_") as folder:
            directory=Path(folder)
            original=directory/"spoken.mp4"
            output=directory/"mixed.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=size=320x568:rate=15:duration=4.5",
                "-f","lavfi","-i","sine=frequency=440:duration=4.5",
                "-c:v","libx264","-preset","ultrafast","-threads","2",
                "-c:a","aac","-shortest",str(original)
            ],check=True,capture_output=True,timeout=60)
            stats=apply_effects(
                original,output,self.WORDS[:6],
                sound="off",emoji="off",insert_style="off",guide_effect="off",
                caption_sound="soft",quality="balanced",
            )
            self.assertEqual(stats["caption_sfx_count"],3)
            self.assertTrue(output.exists())
            media=media_info(output)
            self.assertTrue(any(x["codec_type"]=="audio" for x in media["streams"]))
            self.assertTrue(any(x["codec_type"]=="video" for x in media["streams"]))
            self.assertGreater(output.stat().st_size,10000)


if __name__=="__main__":
    unittest.main()
