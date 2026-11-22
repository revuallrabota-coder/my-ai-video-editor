"""Regression tests: Old Money is a distinct restrained visual + audio preset."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from old_money_fx import CONCEPTS, select_old_money_cues, render_old_money_card

class OldMoneyStyleTests(unittest.TestCase):
    def test_stickers_only_follow_spoken_nouns(self):
        words=[(.2,.4,"кофе"),(5.,5.2,"кофе"),(16.,16.3,"часы"),(26.,26.4,"журнал")]
        cues=select_old_money_cues(words,32,"balanced")
        self.assertEqual([c.symbol for c in cues],["coffee","watch","book"])
        self.assertEqual([c.label for c in cues],["кофе","часы","журнал"])
        self.assertTrue(all(c.time>=4.25 for c in cues))
        self.assertEqual(select_old_money_cues([(7,7.3,"обычная")],30),[])
        with self.assertRaises(ValueError):
            select_old_money_cues(words,32,"invalid")

    def test_separate_vector_props_for_each_motif(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name,_,_ in CONCEPTS:
                target=Path(tmp)/(name+".png")
                render_old_money_card(target,"КНИГА",name)
                with Image.open(target) as image:
                    self.assertEqual(image.size,(480,382))
                    self.assertEqual(image.mode,"RGBA")
                    self.assertGreater(len(image.getcolors(10**7) or []),10)

    def test_minapp_uses_old_money_not_reference_soft_for_inserts(self):
        root=Path(__file__).parent
        html=(root/"index.html").read_text("utf-8")
        renderer=(root/"reels_effects.py").read_text("utf-8")
        self.assertIn("s.captionVariant==='old_money'?'old_money'",html)
        self.assertIn("render_old_money_card",renderer)
        self.assertIn("select_old_money_cues",renderer)
        self.assertIn('insert_style in ("vintage","old_money")',renderer)

if __name__=="__main__":
    unittest.main()
