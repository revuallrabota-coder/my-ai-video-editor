"""Reference-derived dynamic captions, cinematic pan and Full HD smoke tests."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from reference_dynamic_captions import build_reference_dynamic_ass
from reference_editor import add_virtual_camera, side_pan_expressions
from telegram_editor import Segment, base_video, media_info


class ReferenceMotionTests(unittest.TestCase):
    WORDS = [
        (.1,.35,"Сейчас"),(.37,.72,"расскажу"),(.75,1.18,"ситуацию"),
        (2.1,2.37,"Мне"),(2.4,2.9,"поставили"),(2.93,3.24,"условия"),
        (4.4,4.73,"Поэтому"),(4.78,5.09,"решила"),(5.1,5.58,"уйти"),
        (6.5,6.9,"Новые"),(6.94,7.3,"правила"),(7.34,7.8,"работы"),
    ]

    def test_dynamic_text_changes_size_and_has_some_plates(self) -> None:
        text, count=build_reference_dynamic_ass(
            self.WORDS, color="auto", font_profile="bold"
        )
        self.assertGreater(count,0)
        self.assertLess(count, len(self.WORDS)*3)
        # One text event per phrase; any oval shadow has its own synced layer.
        self.assertIn("Сейчас",text)
        self.assertIn("расскажу",text)
        self.assertIn("Style: Phrase,",text)
        self.assertIn("Style: PhrasePlate,",text)
        self.assertEqual(text.count("Dialogue: 2,")+text.count("Dialogue: 1,"),count)
        self.assertNotIn("Dialogue: 0,",text)
        self.assertIn(r"\move(",text)
        self.assertIn(r"\fad(",text)
        # Максимальный кегль ограничен безопасной зоной 9:16, 107 больше не допустим.
        self.assertNotIn(r"\fs107",text)
        self.assertIn("Dialogue: 2,",text)
        self.assertIn("&H003E44F0&",text)  # red #F0443E in ASS BGR
        self.assertNotIn("Cheat Code",text)

    def test_pan_is_eased_and_not_stuck_in_loop(self) -> None:
        zoom, x=side_pan_expressions(self.WORDS,9.0)
        self.assertIn("on-",x)
        self.assertIn("iw-iw/zoom",x)
        self.assertIn("0.280",x)
        self.assertNotIn("mod(",x)
        self.assertIn("1.16",zoom)

    def test_render_camera_and_text_in_same_pass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cinematic_test_") as tmp:
            folder=Path(tmp)
            src=folder/"input.mp4"
            subs=folder/"caption.ass"
            out=folder/"output.mp4"
            ff=[
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=size=240x426:rate=30:duration=2.2",
                "-f","lavfi","-i","sine=frequency=440:duration=2.2",
                "-c:v","libx264","-preset","ultrafast",
                "-c:a","aac","-shortest",str(src),
            ]
            subprocess.run(ff,check=True,capture_output=True,timeout=90)
            text,_=build_reference_dynamic_ass(
                [(0.1,0.45,"Мой"),(.5,.9,"новый"),(.95,1.4,"маникюр")]
            )
            subs.write_text(text,encoding="utf-8")
            add_virtual_camera(
                src,out,cadence=3,camera_style="cinematic_pan",
                words=[(0.1,.45,"Мой"),(.5,.9,"новый"),(.95,1.4,"маникюр")],
                quality="balanced",subtitles_ass=subs,
            )
            streams=media_info(out)["streams"]
            video=next(x for x in streams if x.get("codec_type")=="video")
            self.assertEqual((video["width"],video["height"]),(720,1280))
            self.assertTrue(any(x.get("codec_type")=="audio" for x in streams))
            self.assertGreater(out.stat().st_size,10000)

    def test_fullhd_export_resolution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quality_test_") as tmp:
            folder=Path(tmp)
            src=folder/"input.mp4"
            out=folder/"fullhd.mp4"
            subprocess.run([
                "ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=size=144x256:rate=30:duration=0.7",
                "-f","lavfi","-i","sine=frequency=220:duration=0.7",
                "-c:v","libx264","-preset","ultrafast","-c:a","aac",
                "-shortest",str(src)
            ],check=True,capture_output=True,timeout=90)
            base_video(
                src,out,[Segment(0,.65)],True,
                audio_profile="off",quality="high",
            )
            streams=media_info(out)["streams"]
            stream=next(x for x in streams if x.get("codec_type")=="video")
            self.assertEqual((stream["width"],stream["height"]),(1080,1920))


if __name__=="__main__":
    unittest.main()
