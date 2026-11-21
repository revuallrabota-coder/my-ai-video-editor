"""Presets must be whitelisted FFmpeg expressions, with no user strings."""
from __future__ import annotations
import unittest

from font_presets import choose_font
from reference_dynamic_captions import build_reference_dynamic_ass
from video_filters import FILTERS, video_filter_chain
from reels_effects import pick_caption_cues, make_sfx_track


class ReelsLooksTests(unittest.TestCase):
    WORDS=[
        (0.10,0.32,"Новый"),(0.38,0.70,"маникюр"),
        (0.72,0.97,"красивый"),(1.04,1.30,"сегодня"),
        (1.45,1.8,"здесь"),(2.15,2.58,"ошибка"),
    ]

    def test_new_named_filters_and_font_pairs(self):
        self.assertEqual(video_filter_chain("none"), "")
        for look in ("old_money","vintage","street","elegant"):
            with self.subTest(look=look):
                self.assertIn(look,FILTERS)
                self.assertIn("eq=",video_filter_chain(look))
        for name in ("old_money","vintage","street","refined"):
            self.assertTrue(choose_font(name).name)
        with self.assertRaises(ValueError):
            video_filter_chain("eq=contrast=100000:evil=1")

    def test_subtitle_color_style_separate_fonts_and_backdrops(self):
        presets={
            "old_money":("old_money","refined"),
            "vintage":("vintage","script"),
            "street":("street","clean"),
            "elegant":("refined","elegant"),
        }
        for style,(big,small) in presets.items():
            with self.subTest(style=style):
                ass,n=build_reference_dynamic_ass(
                    self.WORDS,color="auto",font_profile=big,
                    small_font_profile=small,caption_variant=style,
                    background_style="always",animation_style="slide",
                )
                self.assertGreater(n,0)
                self.assertIn("Style: Phrase,"+choose_font(small).name,ass)
                self.assertIn(r"\fn"+choose_font(big).name,ass)
                self.assertIn("Dialogue: 2,",ass)
                self.assertNotIn("Dialogue: 0,",ass)
                self.assertIn(r"\move(",ass)
        ass,n=build_reference_dynamic_ass(
            self.WORDS,background_style="off",animation_style="pop"
        )
        self.assertGreater(n,0)
        self.assertNotIn("Dialogue: 0,",ass)
        self.assertIn(r"\move(",ass)

    def test_caption_sfx_are_sparse_not_every_word(self):
        words=[(i*.24,i*.24+.17,"обучение") for i in range(25)]
        cues=pick_caption_cues(words,8,style="soft")
        self.assertGreater(len(cues),0)
        self.assertLess(len(cues),len(words)//3)
        self.assertTrue(all(b[0]-a[0]>=0.99 for a,b in zip(cues,cues[1:])))
        self.assertTrue(all(c[1] is None for c in cues))
