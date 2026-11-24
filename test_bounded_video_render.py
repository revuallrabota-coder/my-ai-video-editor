"""Runner-OOM regression: pause cuts never fan out source frames.

The November 24 render downloaded all parts, recognized 46 words, and was
terminated after FFmpeg exceeded 7 GB RSS on the first encode pass.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telegram_editor import Segment, base_video


def _probe(path: Path) -> dict:
    return json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height,duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout)


class BoundedRenderTests(unittest.TestCase):
    def test_many_speech_cuts_use_one_bounded_filtergraph(self):
        cuts=[Segment(i*.2,i*.2+.09) for i in range(40)]
        captured=[]
        with patch("telegram_editor.execute",side_effect=lambda args: captured.append(args)):
            base_video(Path("/tmp/source.mov"),Path("/tmp/result.mp4"),cuts,True,
                       quality="high",speed=1.2,audio_profile="balanced")
        self.assertEqual(len(captured),1)
        command=captured[0]
        graph=command[command.index("-filter_complex")+1]
        self.assertEqual(graph.count("select='"),2)
        self.assertIn("aselect='",graph)
        self.assertNotIn("concat=",graph)
        self.assertNotIn("trim=start",graph)
        self.assertIn("setpts=N/(30*TB)",graph)
        self.assertIn("asetpts=N/SR/TB",graph)
        self.assertIn("-filter_complex_threads",command)
        self.assertEqual(command[command.index("-filter_complex_threads")+1],"1")
        self.assertEqual(command[command.index("-threads")+1],"2")
        self.assertIn("scale=1080:1920",graph)
        self.assertEqual(graph.count("gte(t,"),80)

    def test_real_fullhd_video_audio_remain_synchronized(self):
        with tempfile.TemporaryDirectory(prefix="bounded_render_") as tmp:
            folder=Path(tmp)
            original=folder/"source.mp4"
            output=folder/"edited.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-filter_threads","1",
                "-f","lavfi","-i","testsrc2=size=320x568:rate=30:duration=4.8",
                "-f","lavfi","-i","sine=frequency=430:sample_rate=48000:duration=4.8",
                "-c:v","libx264","-preset","ultrafast","-threads","2",
                "-c:a","aac","-shortest",str(original)
            ],capture_output=True,check=True,timeout=45)
            cuts=[Segment(.20,.85),Segment(2.0,2.62),Segment(3.9,4.43)]
            base_video(original,output,cuts,True,quality="high",
                       speed=1.2,audio_profile="off")
            metadata=_probe(output)
            streams=metadata["streams"]
            video=next(s for s in streams if s["codec_type"]=="video")
            audio=next(s for s in streams if s["codec_type"]=="audio")
            expected=sum(c.end-c.start for c in cuts)/1.2
            self.assertEqual((video["width"],video["height"]),(1080,1920))
            self.assertAlmostEqual(float(video["duration"]),expected,delta=.10)
            self.assertAlmostEqual(float(audio["duration"]),expected,delta=.10)
            self.assertLess(abs(float(video["duration"])-float(audio["duration"])),.12)

    def test_no_audio_still_uses_single_stream(self):
        cuts=[Segment(0,.7),Segment(1.2,1.7)]
        commands=[]
        with patch("telegram_editor.execute",side_effect=lambda args: commands.append(args)):
            base_video(Path("/tmp/silent.mov"),Path("/tmp/edited.mp4"),cuts,False,
                       quality="balanced")
        cmd=commands[0]
        self.assertIn("-an",cmd)
        graph=cmd[cmd.index("-filter_complex")+1]
        self.assertNotIn("aselect=",graph)
        self.assertIn("select='",graph)


if __name__=="__main__":
    unittest.main()
