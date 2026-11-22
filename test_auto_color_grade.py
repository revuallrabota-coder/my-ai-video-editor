"""Ensure Reels filters are not an additional misleading user decision."""
from pathlib import Path
import re
import unittest
from video_filters import FILTERS,video_filter_chain

ROOT=Path(__file__).parent

class ColorGradePresetTests(unittest.TestCase):
    def test_only_style_controls_grade(self):
        html=(ROOT/"index.html").read_text("utf-8")
        self.assertNotIn('<label class="field" for="filter">',html)
        self.assertIn('<select id="filter" hidden style="display:none"',html)
        self.assertIn("byId('filter').value=autoGrade[this.value]||'none';",html)
        block=html.split("var autoGrade={",1)[1].split("};",1)[0]
        for preset,grade in {
            "reference_soft":"none",
            "pink_tender":"pink_tender",
            "old_money":"old_money",
            "vintage_cinema":"vintage",
            "editorial":"clean",
            "contour_talk":"none",
            "burgundy_brown_talk":"burgundy",
            "custom":"none",
        }.items():
            self.assertIn(f"{preset}:'{grade}'",block)
            self.assertIn(grade,FILTERS)

    def test_pipeline_receives_filter_after_worker_conversion(self):
        html=(ROOT/"index.html").read_text("utf-8")
        worker=(ROOT/"cloudflare_launcher.js").read_text("utf-8")
        process=(ROOT/"process_uploaded_video.py").read_text("utf-8")
        render=(ROOT/"telegram_editor.py").read_text("utf-8")
        self.assertIn("filter_style:byId('filter').value",html)
        self.assertIn('video_filter:option("video_filter",s.filter_style ?? s.video_filter,"none")',worker)
        self.assertIn('filter_style=str(config.get("video_filter","none"))',process)
        self.assertIn('extra_filters = video_filter_chain(filter_style)',render)
        self.assertIn('video_filters += "," + extra_filters',render)

    def test_subtle_styles_are_distinct_and_normal_is_unmodified(self):
        self.assertEqual(video_filter_chain("none"),"")
        for grade in ("old_money","pink_tender","burgundy","vintage","clean"):
            self.assertTrue(video_filter_chain(grade))
        self.assertEqual(len({video_filter_chain(key) for key in
            ("none","old_money","pink_tender","burgundy","vintage")}),5)
        with self.assertRaises(ValueError):
            video_filter_chain("unknown")
        
if __name__=="__main__":
    unittest.main()
