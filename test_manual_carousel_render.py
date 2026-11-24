"""End-to-end FFmpeg smoke test for manually selected carousel + audible SFX.

The visual must exist even when the transcript has no 'options/list' keywords.
Never upload private customer video to GitHub for a regression test.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageChops
from guide18_fx import plan
from reels_effects import apply_effects
from telegram_editor import media_info


def still(video: Path, seconds: float, dest: Path) -> Image.Image:
    subprocess.run([
        "ffmpeg","-hide_banner","-loglevel","error","-y",
        "-ss",str(seconds),"-i",str(video),"-frames:v","1",str(dest)
    ],capture_output=True,check=True,timeout=50)
    with Image.open(dest) as f:
        return f.convert("RGB")


class ManualCarouselVideoTests(unittest.TestCase):
    def test_carousel_renders_video_and_a_synchronized_audio_insert(self):
        words=[(1.0,1.4,"Здравствуйте"),(4.5,4.85,"сегодня"),
               (5.0,5.4,"говорим"),(5.7,6.0,"клиентам")]
        chosen=plan(words,7.8,"multi:pov_carousel_spin")
        self.assertEqual(len(chosen),1)
        self.assertTrue(chosen[0].required)
        self.assertFalse(chosen[0].compact,"The user chose cinematic fullscreen, not a widget")
        with tempfile.TemporaryDirectory(prefix="actual_carousel_") as tmp:
            root=Path(tmp)
            original=root/"source.mp4"
            edited=root/"edited.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i",
                "testsrc2=size=360x640:rate=15:duration=7.8",
                "-f","lavfi","-i","sine=frequency=440:duration=7.8",
                "-c:v","libx264","-preset","ultrafast","-threads","2",
                "-c:a","aac","-shortest",str(original)
            ],capture_output=True,check=True,timeout=80)
            # Cinematic scene must never need person segmentation or tiny
            # corner-caption protection. It replaces the frame entirely.
            with patch("guide18_fx._mask_frames",
                       side_effect=RuntimeError("segmenter not available")):
                stats=apply_effects(
                    original,edited,words,
                    insert_style="reference_soft",
                    guide_effect="multi:pov_carousel_spin",
                    insert_sound="on",sound="off",caption_sound="off",
                    emoji="off",quality="balanced",
                )
            self.assertGreaterEqual(stats["guide_effect_count"],1)
            self.assertIn("pov_carousel_spin",stats["guide_effects_rendered"])
            self.assertGreaterEqual(stats["insert_sfx_count"],1)
            self.assertTrue(edited.exists())
            streams=media_info(edited)["streams"]
            self.assertTrue(any(s["codec_type"]=="audio" for s in streams))
            self.assertTrue(any(s["codec_type"]=="video" for s in streams))
            a=still(original,5.2,root/"before.png")
            b=still(edited,5.2,root/"after.png")
            self.assertEqual(a.size,b.size)
            # The entire 9:16 composition must change, not just a tiny
            # floating 320x150 rectangle in the top-left corner.
            diff=ImageChops.difference(a,b).convert("L")
            histogram=diff.histogram()
            changed=sum(histogram[38:])
            self.assertGreater(changed, a.width*a.height*.53,
                "Carousel must replace the conversation with a cinematic scene")
            # Middle-right and lower corners must be visibly treated as well.
            bottom_right=(220,350,355,560)
            bottom=ImageChops.difference(
                a.crop(bottom_right),b.crop(bottom_right)).convert("L")
            self.assertGreater(sum(bottom.histogram()[38:]),4300,
                "Old tiny corner widget must never pass the visual regression")


if __name__=="__main__":
    unittest.main()
