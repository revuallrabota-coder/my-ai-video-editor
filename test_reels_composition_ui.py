"""The sole composition is the original fullscreen speaker, independent of preset."""
import unittest
from pathlib import Path

class CompositionPickerRemovedTests(unittest.TestCase):
    def test_no_redundant_composition_dropdown(self):
        html=(Path(__file__).parent/"index.html").read_text(encoding="utf-8")
        self.assertNotIn('<select id="talkScene">', html)
        self.assertNotIn('for="talkScene"', html)
        self.assertIn('<input type="hidden" id="talkScene" value="off">', html)

    def test_all_reels_styles_keep_fullscreen_and_auto_inserts(self):
        html=(Path(__file__).parent/"index.html").read_text(encoding="utf-8")
        self.assertIn("talkScene:'off'", html)
        self.assertIn("byId('talkScene').value='off'", html)
        for preset in ("pink_tender","old_money","vintage_cinema","burgundy_brown_talk"):
            self.assertIn('value="'+preset+'"', html)
        self.assertIn("s.reelsPreset==='burgundy_brown_talk'?'burgundy'", html)
        self.assertIn("s.reelsPreset==='pink_tender'?'pink_tender'", html)

if __name__ == "__main__":
    unittest.main()
