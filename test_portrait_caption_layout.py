"""CI checks for new talking-head subtitle layouts (no AI model needed)."""
import re
import unittest
from pathlib import Path

from portrait_caption_layer import check_layout
from reference_cascade_captions import build_reference_cascade_ass

WORDS = [
    (0.10, 0.36, "Посмотри"),
    (0.36, 0.64, "на"),
    (0.64, 1.10, "ошибку"),
    (1.10, 1.46, "сейчас"),
]


class TalkingHeadLayouts(unittest.TestCase):
    def test_layout_validation(self):
        for layout in ("standard", "behind", "beside"):
            self.assertEqual(check_layout(layout), layout)
        with self.assertRaises(ValueError):
            check_layout("unknown")

    def test_left_and_right_preserve_animation(self):
        layouts = {}
        for side in ("center", "left", "right"):
            script, count = build_reference_cascade_ass(
                WORDS,
                caption_variant="reference_soft",
                animation_style="float",
                background_style="always",
                subject_side=side,
            )
            self.assertGreater(count, 0)
            self.assertIn(r"\move(", script)
            self.assertIn(r"\fad(", script)
            self.assertIn("CascadeHalo", script)
            # Compare the same first animated word for all three positions.
            match = re.search(r"Dialogue: 2,[^\n]*?\\move\((\d+),", script)
            self.assertIsNotNone(match)
            layouts[side] = int(match.group(1))
        self.assertLess(layouts["left"], layouts["center"])
        self.assertLess(layouts["center"], layouts["right"])

    def test_user_control_is_forwarded_to_worker_and_montage(self):
        html = Path("index.html").read_text("utf-8")
        worker = Path("cloudflare_launcher.js").read_text("utf-8")
        processor = Path("process_uploaded_video.py").read_text("utf-8")
        self.assertIn('id="subjectLayout"', html)
        self.assertIn("subject_layout:s.subjectLayout", html)
        self.assertIn('subject_layout: subjectLayout', worker)
        self.assertIn('config.get("subject_layout","standard")', processor)


if __name__ == "__main__":
    unittest.main()
