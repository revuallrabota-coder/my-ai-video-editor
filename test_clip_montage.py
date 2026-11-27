"""End-to-end multi-source FFmpeg join and private KV download contract."""
from __future__ import annotations

import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from clip_montage import join_clips
from process_uploaded_video import read_chunked_project
from telegram_editor import duration_and_audio, media_info


class VideoProjectTests(unittest.TestCase):
    def test_different_frame_rates_resolutions_and_missing_audio(self):
        with tempfile.TemporaryDirectory(prefix="clip_test_") as t:
            root=Path(t)
            first,second,output=(root/f for f in
                                 ("red.mp4","blue.mp4","combined.mp4"))
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=red:s=240x426:r=15:d=1.0",
                "-f","lavfi","-i","sine=frequency=440:duration=1.0",
                "-c:v","libx264","-preset","ultrafast","-c:a","aac",
                "-shortest",str(first)
            ],check=True,capture_output=True,timeout=50)
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","color=c=blue:s=320x240:r=24:d=1.0",
                "-vf","noise=alls=15:allf=t",
                "-c:v","libx264","-preset","ultrafast","-an",str(second)
            ],check=True,capture_output=True,timeout=50)
            duration,actual_audio=join_clips([first,second],output,"balanced")
            self.assertTrue(actual_audio)
            self.assertAlmostEqual(duration,2.0,delta=0.12)
            self.assertEqual(output.stat().st_size>4000,True)
            streams=media_info(output)["streams"]
            video=next(s for s in streams if s["codec_type"]=="video")
            sound=next(s for s in streams if s["codec_type"]=="audio")
            self.assertEqual((video["width"],video["height"]),(720,1280))
            self.assertEqual(video["r_frame_rate"],"30/1")
            self.assertEqual(sound["codec_name"],"aac")
            # The original clip order survives the normalization/concat.
            def center_rgb(t):
                result=subprocess.run([
                    "ffmpeg","-hide_banner","-loglevel","error",
                    "-ss",str(t),"-i",str(output),
                    "-frames:v","1","-vf","crop=2:2:360:640",
                    "-f","rawvideo","-pix_fmt","rgb24","-"
                ],check=True,capture_output=True,timeout=40)
                return tuple(result.stdout[:3])
            red=center_rgb(.35)
            blue=center_rgb(1.35)
            self.assertGreater(red[0],red[2]+60)
            self.assertGreater(blue[2],blue[0]+60)
            self.assertTrue(duration_and_audio(output)[1])

    def test_too_long_project_rejected_before_edit(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            clips=[root/"one.mp4",root/"two.mp4"]
            for file in clips:
                file.write_bytes(b"X"*5000)
            with patch("clip_montage.duration_and_audio",
                       side_effect=[(310.0,True),(310.0,True)]):
                with self.assertRaisesRegex(ValueError,"продолжительность"):
                    join_clips(clips,root/"out.mp4","balanced")
            self.assertFalse((root/"out.mp4").exists())

    def test_restore_ordered_clips_without_full_500mb_allocation(self):
        first=b"A"*5000
        second=b"B"*6000
        meta={"size":11000,"parts":2,"chunk_size":4_000_000,
              "files":[
                  {"name":"first.mp4","size":5000,"offset":0,"parts":1},
                  {"name":"second.mov","size":6000,"offset":1,"parts":1},
              ]}
        class Response:
            status_code=200
            def __init__(self,payload):self.payload=payload
            def raise_for_status(self):pass
            def json(self):return self.payload
            @property
            def content(self):return self.payload
        class Session:
            def get(self,url,**kwargs):
                if url.endswith("/manifest"):return Response(meta)
                if url.endswith("/chunk/0"):return Response(first)
                if url.endswith("/chunk/1"):return Response(second)
                raise AssertionError("Unexpected chunk "+url)
        with tempfile.TemporaryDirectory() as t:
            with patch("process_uploaded_video.requests.Session",return_value=Session()):
                manifest,paths=read_chunked_project(
                    "https://demo.workers.dev","a"*36,"bot-secret",Path(t)
                )
            self.assertEqual(manifest["parts"],2)
            self.assertEqual([p.read_bytes() for p in paths],[first,second])
            self.assertEqual([p.suffix for p in paths],[".mp4",".mov"])

    def test_reject_tampered_project_offsets(self):
        bad={"size":11000,"parts":2,"chunk_size":4_000_000,
             "files":[{"name":"one.mp4","size":5000,"parts":1,"offset":1},
                      {"name":"two.mp4","size":6000,"parts":1,"offset":0}]}
        class Response:
            status_code=200
            def raise_for_status(self):pass
            def json(self):return bad
        class Session:
            def get(self,url,**kwargs):return Response()
        with tempfile.TemporaryDirectory() as t:
            with patch("process_uploaded_video.requests.Session",return_value=Session()):
                with self.assertRaisesRegex(ValueError,"список"):
                    read_chunked_project(
                        "https://demo.workers.dev","a"*36,"bot-secret",Path(t)
                    )


if __name__=="__main__":
    unittest.main()
