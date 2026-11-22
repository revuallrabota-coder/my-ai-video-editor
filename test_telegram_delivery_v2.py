"""Telegram chat must receive a playable MP4 even if the master is >48MB."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telegram_delivery import (
    telegram_copy,send_video_to_telegram,TELEGRAM_SAFE_BYTES,
)
from telegram_editor import duration_and_audio


class TelegramDeliveryTests(unittest.TestCase):
    def test_two_pass_produces_smaller_playable_copy_and_keeps_voice(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"master.mp4"
            copy=Path(td)/"telegram.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=s=320x568:r=15:d=4.8",
                "-f","lavfi","-i","sine=frequency=400:duration=4.8",
                "-c:v","libx264","-preset","ultrafast","-crf","12",
                "-c:a","aac","-b:a","192k","-shortest",str(source)
            ],check=True,capture_output=True,timeout=65)
            self.assertGreater(source.stat().st_size,400_000)
            fitted=telegram_copy(
                source,copy,max_bytes=350_000,target_bytes=290_000
            )
            self.assertEqual(fitted,copy)
            self.assertLess(copy.stat().st_size,350_001)
            self.assertGreater(source.stat().st_size,copy.stat().st_size)
            seconds,audio=duration_and_audio(copy)
            self.assertTrue(audio)
            self.assertAlmostEqual(seconds,4.8,delta=.2)

    def test_no_recompression_of_telegram_ready_file(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"small.mp4"
            src.write_bytes(b"X"*4096)
            self.assertEqual(telegram_copy(src,Path(td)/"unused.mp4"),src)

    def test_send_video_first_then_fallback_document(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"small.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=size=360x640:rate=15:duration=2",
                "-f","lavfi","-i","sine=frequency=440:duration=2",
                "-c:v","libx264","-preset","ultrafast",
                "-c:a","aac","-shortest",str(src)
            ],capture_output=True,check=True,timeout=55)
            class Response:
                def __init__(self,ok):
                    self.ok=ok
                    self.status_code=200
                def json(self):return {"ok":self.ok}
            with patch("telegram_delivery.requests.post",
                       side_effect=[Response(False),Response(True)]) as post:
                send_video_to_telegram("TOKEN",314159,src,"Готовый Reels")
            self.assertEqual(post.call_count,2)
            self.assertTrue(post.call_args_list[0].args[0].endswith("/sendVideo"))
            self.assertTrue(post.call_args_list[1].args[0].endswith("/sendDocument"))


if __name__=="__main__":
    unittest.main()
