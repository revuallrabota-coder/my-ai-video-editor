"""Actual FFmpeg smoke test: selecting a filter changes the exported pixels."""
from __future__ import annotations

import shutil
import subprocess
import unittest

from video_filters import FILTERS,video_filter_chain


class VisibleFiltersTests(unittest.TestCase):
    def test_preset_names_and_mappings(self):
        self.assertIn("none",FILTERS)
        self.assertEqual(video_filter_chain("none"),"")
        self.assertGreaterEqual(len(FILTERS),10)
        with self.assertRaises(ValueError):
            video_filter_chain("nonexistent")

    @unittest.skipUnless(shutil.which("ffmpeg"),"FFmpeg required")
    def test_every_selected_filter_changes_real_video_pixels(self):
        def frame(chain: str) -> bytes:
            args=[
                "ffmpeg","-v","error","-f","lavfi","-i",
                "testsrc2=size=180x320:rate=1:duration=1",
                "-frames:v","1",
            ]
            if chain:
                args.extend(["-vf",chain])
            args.extend(["-f","rawvideo","-pix_fmt","rgb24","-"])
            p=subprocess.run(args,capture_output=True,check=True,timeout=35)
            self.assertEqual(len(p.stdout),180*320*3)
            return p.stdout

        reference=frame("")
        for name,chain in FILTERS.items():
            if name=="none":
                continue
            with self.subTest(filter=name):
                actual=frame(chain)
                self.assertNotEqual(actual,reference)


if __name__=="__main__":
    unittest.main()
