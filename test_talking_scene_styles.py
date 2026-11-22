"""Regression checks for four independently selectable talking-head compositions."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from talking_scene_styles import (
    _arch_mask, _background, append_scene_ornaments,
    render_scene, validate_talk_scene,
)
from reference_cascade_captions import build_reference_cascade_ass


class FourTalkingReelsLooks(unittest.TestCase):
    def test_presets_are_distinct(self):
        self.assertEqual(validate_talk_scene("contour"),"contour")
        self.assertEqual(validate_talk_scene("cream"),"cream")
        self.assertEqual(validate_talk_scene("pistachio"),"pistachio")
        self.assertEqual(validate_talk_scene("burgundy_brown"),"burgundy_brown")
        self.assertEqual(validate_talk_scene("off"),"off")
        with self.assertRaises(ValueError):
            validate_talk_scene("reels_line_logo")
        a=_background("contour",(360,640))
        b=_background("cream",(360,640))
        p=_background("pistachio",(360,640))
        v=_background("burgundy_brown",(360,640))
        # Each selection must create a visibly distinct scene, not merely
        # relabel the same cream background.
        backgrounds=[im.getpixel((180,128)) for im in (a,b,p,v)]
        self.assertEqual(len(set(backgrounds)),4)
        self.assertGreater(p.getpixel((180,128))[1],p.getpixel((180,128))[0])
        self.assertGreater(v.getpixel((180,128))[0],v.getpixel((180,128))[1])
        mask=_arch_mask((360,390))
        self.assertEqual(mask.getpixel((180,370)),255)
        self.assertEqual(mask.getpixel((0,0)),0)

    def test_studio_captions_preserve_soft_word_animations(self):
        words=[
            (0.1,.4,"Смотри"),(.4,.7,"какая"),(.7,1.15,"ошибка"),
            (1.2,1.5,"видео"),(1.5,1.85,"всё"),(1.85,2.3,"показывает"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            for style in ("contour","cream","pistachio","burgundy_brown"):
                script,count=build_reference_cascade_ass(
                    words,color="auto",caption_position="studio",
                    font_profile="bold",small_font_profile="modern",
                    caption_variant={
                        "contour":"contour_talk","cream":"cream_talk",
                        "pistachio":"pistachio_talk",
                        "burgundy_brown":"burgundy_brown_talk"
                    }[style],
                    background_style="off",animation_style="float",
                )
                self.assertGreater(count,2)
                self.assertIn("\\move(",script)
                self.assertIn("\\fad(",script)
                ass=Path(temp)/(style+".ass")
                ass.write_text(script,"utf-8")
                badges=append_scene_ornaments(ass,words,style)
                enhanced=ass.read_text("utf-8")
                # Generic speech shorter than 4 seconds must NOT generate
                # arbitrary cards, even in a graphics-forward preset.
                self.assertEqual(badges,0)
                self.assertNotIn("Style: TalkBadge",enhanced)
                self.assertIn("Dialogue: 2",enhanced)

    def test_stickers_only_when_approved_speech_explicitly_justifies_them(self):
        words=[
            (.0,.6,"давайте"),(.7,1.2,"посмотрим"),
            (2.8,3.2,"найди"),(3.3,3.9,"ошибку"),
            (4.0,4.6,"в"),(4.7,5.3,"маникюре"),
            (6.0,7.1,"объясняю"),(7.2,8.0,"почему"),
            (8.1,9.0,"так"),(9.1,10.0,"случилось")
        ]
        from reference_cascade_captions import build_reference_cascade_ass
        for style in ("contour","cream","pistachio","burgundy_brown"):
            ass_text,_=build_reference_cascade_ass(
                words,caption_position="studio",
                caption_variant={
                    "contour":"contour_talk","cream":"cream_talk",
                    "pistachio":"pistachio_talk",
                    "burgundy_brown":"burgundy_brown_talk"
                }[style]
            )
            with tempfile.TemporaryDirectory() as tmp:
                ass=Path(tmp)/"subtitles.ass"
                ass.write_text(ass_text,"utf-8")
                badges=append_scene_ornaments(ass,words,style)
                self.assertLessEqual(badges,1)
                self.assertNotIn("МАСТЕР",ass.read_text("utf-8"))
                if badges:
                    self.assertIn("ОШИБКУ",ass.read_text("utf-8"))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "FFmpeg is not installed")
    def test_real_ffmpeg_output_keeps_voice_and_full_portrait(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            original=root/"original.mp4"
            cmd=["ffmpeg","-v","error","-y",
                 "-f","lavfi","-i","testsrc2=size=360x640:rate=12:duration=1",
                 "-f","lavfi","-i","sine=frequency=340:duration=1",
                 "-c:v","libx264","-preset","ultrafast","-c:a","aac",
                 "-shortest",str(original)]
            subprocess.run(cmd,check=True,capture_output=True,timeout=25)
            for style in ("contour","cream","pistachio","burgundy_brown"):
                dest=root/(style+".mp4")
                render_scene(original,dest,style,quality="balanced")
                self.assertTrue(dest.is_file() and dest.stat().st_size>1000)
                probe=subprocess.run([
                    "ffprobe","-v","quiet","-show_entries",
                    "stream=codec_type,width,height","-of","json",str(dest)
                ],check=True,capture_output=True,text=True,timeout=15)
                streams=json.loads(probe.stdout)["streams"]
                self.assertTrue(any(s["codec_type"]=="audio" for s in streams))
                v=next(s for s in streams if s["codec_type"]=="video")
                self.assertEqual((v["width"],v["height"]),(720,1280))

    def test_upper_heading_contrasts_with_studio_background(self):
        from top_video_title import append_top_title
        from signature_captions import ass_color
        words=[(.2,.5,"Это"),(.6,.9,"пример")]
        for profile,ink in (
            ("pistachio_talk","#294C35"),
            ("burgundy_brown_talk","#F5DCD0"),
        ):
            ass,_=build_reference_cascade_ass(
                words,caption_position="studio",caption_variant=profile)
            titled=append_top_title(
                ass,"Проверка текста","always",3.0,
                color=ink,studio_scene=True,
            )
            self.assertIn("Style: CustomTopTitle",titled)
            self.assertIn(ass_color(ink),titled)
        default=append_top_title(
            ass,"Проверка текста","always",3.0,color="#294C35"
        )
        self.assertIn("&H00FFFFFF",default)

    def test_full_settings_chain_has_talking_scene(self):
        repo=Path(__file__).parent
        html=(repo/"index.html").read_text("utf-8")
        worker=(repo/"cloudflare_launcher.js").read_text("utf-8")
        process=(repo/"process_uploaded_video.py").read_text("utf-8")
        self.assertIn('option value="contour_talk"',html)
        self.assertIn('option value="cream_talk"',html)
        self.assertIn('option value="pistachio_talk"',html)
        self.assertIn('option value="burgundy_brown_talk"',html)
        self.assertIn('option value="pistachio"',html)
        self.assertIn('option value="burgundy_brown"',html)
        self.assertIn('"pistachio","burgundy_brown"',worker)
        self.assertIn("supported_talk_scenes:CHOICES.talk_scene.split(\" \")",worker)
        self.assertIn("workerHealth.supported_talk_scenes",html)
        self.assertIn("color:'#F5DCD0'",html)
        self.assertIn("color:'#294C35'",html)
        self.assertIn("8 готовых стилей",html)
        self.assertIn("pistachio_talk:",html)
        self.assertIn("burgundy_brown_talk:",html)
        self.assertIn("scene==='pistachio'",html)
        self.assertIn("scene==='burgundy_brown'",html)
        self.assertIn("studio_scene=(caption_position==\"studio\")",
                      (repo/"telegram_editor.py").read_text("utf-8"))
        caption_palettes=(repo/"reference_dynamic_captions.py").read_text("utf-8")
        self.assertIn('"pistachio_talk":',caption_palettes)
        self.assertIn('"burgundy_brown_talk":',caption_palettes)
        self.assertIn("talk_scene:s.talkScene",html)
        self.assertIn('talk_scene:option("talk_scene",s.talk_scene,"off")',worker)
        self.assertIn('config.get("talk_scene","off")',process)
        self.assertIn("style_contract_version:CONTRACT",worker)
        self.assertIn("accepted_talk_scene:settings.talk_scene",worker)
        self.assertIn("workerHealth.style_contract_version!==3",html)
        self.assertIn("start.accepted_talk_scene!==settings.talk_scene",html)
        renderer=(repo/"reference_editor.py").read_text("utf-8")
        standard=(repo/"telegram_editor.py").read_text("utf-8")
        self.assertIn('insert_style=insert_style',renderer)
        self.assertIn('insert_style=insert_style',standard)
        self.assertIn('private_assets=private_assets',renderer)
        self.assertIn('private_assets=private_assets',standard)
        self.assertIn('studio_scene=talk_scene',renderer)
        self.assertIn('studio_scene=talk_scene',standard)
        self.assertIn('if insert_style != "off":',renderer)
        effects=(repo/"reels_effects.py").read_text("utf-8")
        self.assertIn("studio_cues=(select_studio_cues",effects)
        self.assertIn("moving_source=insert_source or source",effects)
        self.assertIn("live=f\"[liveclip{i}]\"",effects)
        self.assertIn("shortest=0:eof_action=pass:repeatlast=0",effects)


if __name__=="__main__":
    unittest.main()
