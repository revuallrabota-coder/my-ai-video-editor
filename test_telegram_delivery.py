"""Ensure completed Reels is sent as a playable MP4 under 50MB Bot API limit."""
from __future__ import annotations
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from telegram_delivery import telegram_copy,send_video_to_telegram
from telegram_editor import duration_and_audio,media_info


class TelegramDeliveryTests(unittest.TestCase):
    def test_large_final_mp4_is_transcoded_below_safe_limit(self):
        with tempfile.TemporaryDirectory(prefix="tg_video_") as temp:
            root=Path(temp)
            original=root/"fullhd.mp4"
            deliver=root/"telegram.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=s=360x640:r=15:d=8",
                "-f","lavfi","-i","sine=frequency=430:duration=8",
                "-c:v","libx264","-preset","ultrafast","-crf","10",
                "-c:a","aac","-b:a","160k","-shortest",
                str(original)
            ],capture_output=True,check=True,timeout=70)
            self.assertGreater(original.stat().st_size,400000)
            rendered=telegram_copy(
                original,deliver,max_bytes=400000,target_bytes=280000
            )
            self.assertEqual(rendered,deliver)
            self.assertLessEqual(deliver.stat().st_size,400000)
            self.assertGreater(deliver.stat().st_size,30000)
            seconds,audio=duration_and_audio(deliver)
            self.assertTrue(audio)
            self.assertAlmostEqual(seconds,8.0,delta=.15)
            self.assertEqual(
                next(s["codec_name"] for s in media_info(deliver)["streams"]
                     if s["codec_type"]=="video"),"h264")
            # Encoding never modifies the untouched high-quality master.
            self.assertGreater(original.stat().st_size,deliver.stat().st_size)

    def test_small_original_does_not_get_reencoded(self):
        with tempfile.TemporaryDirectory() as t:
            f=Path(t)/"tiny.mp4"
            f.write_bytes(b"X"*5000)
            self.assertEqual(telegram_copy(f,Path(t)/"output.mp4"),f)
            self.assertFalse((Path(t)/"output.mp4").exists())

    def test_sendvideo_is_primary_method_with_document_fallback(self):
        with tempfile.TemporaryDirectory() as t:
            file=Path(t)/"reels.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=size=360x640:rate=15:duration=2",
                "-f","lavfi","-i","sine=frequency=440:duration=2",
                "-c:v","libx264","-preset","ultrafast",
                "-c:a","aac","-shortest",str(file),
            ],capture_output=True,check=True,timeout=50)
            class Reply:
                def __init__(self,ok):
                    self.ok=ok
                    self._ok=ok
                def json(self):
                    return {"ok":self._ok,
                            "description":"Upload rejected" if not self._ok else ""}
            with patch("telegram_delivery.requests.post",
                       side_effect=[Reply(False),Reply(True)]) as mocked:
                send_video_to_telegram("TOKEN",1234,file,"Готовый ролик")
            self.assertTrue(mocked.call_args_list[0].args[0].endswith("/sendVideo"))
            sent=mocked.call_args_list[0].kwargs
            self.assertEqual(sent["data"]["width"],"360")
            self.assertEqual(sent["data"]["height"],"640")
            self.assertEqual(sent["data"]["duration"],"2")
            self.assertEqual(sent["data"]["supports_streaming"],"true")
            # A portrait thumbnail is generated for iOS clients that might
            # otherwise make the chat player a square.
            self.assertIn("thumbnail",sent["files"])
            self.assertTrue(mocked.call_args_list[1].args[0].endswith("/sendDocument"))

    def test_oversized_document_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as t:
            file=Path(t)/"huge.mp4"
            with file.open("wb") as stream:
                stream.truncate(48_000_001)
            with patch("telegram_delivery.requests.post") as mocked:
                with self.assertRaises(ValueError):
                    send_video_to_telegram("TOKEN",1234,file,"caption")
                mocked.assert_not_called()


if __name__=="__main__":
    unittest.main()
