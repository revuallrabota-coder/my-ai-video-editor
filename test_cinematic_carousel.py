"""Visual quality regression: real fullscreen 9:16 carousel, never 3 thumbnail clones."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops
from cinematic_carousel import draw_carousel
from guide18_fx import _distinct_carousel_frames


class CinematicCarouselTests(unittest.TestCase):
    def test_pictures_actually_slide_fullscreen_instead_of_repeating_a_widget(self):
        pictures=[Image.new("RGB",(420,760),color)
                  for color in ((208,56,63),(45,166,79),(43,89,209))]
        scenes=[draw_carousel(progress,pictures,"burgundy")
                for progress in (.12,.50,.88)]
        self.assertTrue(all(x.size==(360,640) for x in scenes))
        for scene in scenes:
            # The ENTIRE scene hides the previous footage, not just the
            # middle: even borders, drop shadows, labels and progress markers.
            self.assertEqual(scene.getchannel("A").getextrema(),(255,255))
        centers=[frame.convert("RGB").getpixel((180,320)) for frame in scenes]
        self.assertEqual(len(set(centers)),3,"Center slide must change by index")
        for i,expected in enumerate(((208,56,63),(45,166,79),(43,89,209))):
            self.assertLess(sum(abs(a-b) for a,b in zip(centers[i],expected)),38)
        # Alpha is equally opaque for both renders, so RGB difference is
        # the meaningful measure (RGBA getbbox can ignore RGB when A==0).
        diff=ImageChops.difference(scenes[0],scenes[-1]).convert("RGB")
        self.assertIsNotNone(diff.getbbox())
        # The scene fades in/out gracefully without hard cuts.
        self.assertEqual(draw_carousel(0,pictures).getpixel((180,320))[3],0)
        self.assertEqual(draw_carousel(1,pictures).getpixel((180,320))[3],0)

    def test_background_changes_with_aesthetic_but_nail_colors_do_not(self):
        photos=[Image.new("RGB",(420,760),(92,15,39)) for _ in range(3)]
        burgundy=draw_carousel(.5,photos,"burgundy")
        pink=draw_carousel(.5,photos,"pink_tender")
        # Sample outside the full-height slides: side slides intentionally
        # occupy x=15 around y=170, so that is a PHOTO pixel, not backdrop.
        self.assertNotEqual(burgundy.getpixel((15,75)),pink.getpixel((15,75)))
        self.assertEqual(burgundy.getpixel((180,320))[:3],(92,15,39))
        self.assertEqual(pink.getpixel((180,320))[:3],(92,15,39))

    def test_seeks_across_entire_recording_not_only_current_two_seconds(self):
        with tempfile.TemporaryDirectory(prefix="carousel_frames_") as tmp:
            root=Path(tmp);source=root/"three_scenes.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=red:s=360x640:r=15:d=3",
                "-f","lavfi","-i","color=c=green:s=360x640:r=15:d=3",
                "-f","lavfi","-i","color=c=blue:s=360x640:r=15:d=3",
                "-filter_complex","[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                "-map","[v]","-c:v","libx264","-preset","ultrafast",
                "-threads","2",str(source),
            ],check=True,capture_output=True,timeout=75)
            fallback=[Image.new("RGB",(360,640),(20,20,20))]*3
            photos=_distinct_carousel_frames(source,fallback)
            self.assertEqual(len(photos),3)
            values=[p.resize((1,1)).getpixel((0,0)) for p in photos]
            # Three different real sections of the video, not 3 copies.
            self.assertEqual(len(set(values)),3)


if __name__=="__main__":
    unittest.main()
