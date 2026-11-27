"""Do not trim 10-minute speech projects to the old 125-second cap."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from clip_montage import MAX_SECONDS,join_clips


class TenMinuteTimelineTests(unittest.TestCase):
    def test_project_accepts_six_hundred_seconds_without_reencoding_single_clip(self):
        self.assertEqual(MAX_SECONDS,600.0)
        with tempfile.TemporaryDirectory(prefix="ten_min_") as folder:
            path=Path(folder)
            source=path/"source.mp4"
            output=path/"final.mp4"
            source.write_bytes(b"x"*4096)
            with patch("clip_montage.duration_and_audio",return_value=(600.0,True)):
                duration,audio=join_clips([source],output,quality="high")
            self.assertEqual(duration,600.0)
            self.assertTrue(audio)
            self.assertEqual(output.read_bytes(),source.read_bytes())

    def test_more_than_ten_minutes_fails_before_any_expensive_encoding(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"source.mp4";source.write_bytes(b"x"*4096)
            with patch("clip_montage.duration_and_audio",return_value=(600.3,True)):
                with self.assertRaisesRegex(ValueError,"десяти минут"):
                    join_clips([source],Path(folder)/"out.mp4",quality="high")

    def test_multiple_clips_count_toward_a_single_ten_minute_timeline(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            clips=[]
            for n in range(2):
                path=root/f"clip{n}.mp4";path.write_bytes(b"x"*4096)
                clips.append(path)
            with patch("clip_montage.duration_and_audio",return_value=(310.,True)):
                with self.assertRaisesRegex(ValueError,"десяти минут"):
                    join_clips(clips,root/"out.mp4",quality="balanced")


if __name__=="__main__":
    unittest.main()
