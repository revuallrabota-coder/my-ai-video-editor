"""Conservative matching of uploaded transparent PNGs to actual spoken words."""
from pathlib import Path
import unittest
from semantic_object_overlays import choose_object_cues, inventory

class SpokenObjectsTests(unittest.TestCase):
    def setUp(self):
        self.photos=[
            Path("/private/photo_sticker_gift_burgundy.png"),
            Path("/private/photo_sticker_gift_stripes.png"),
            Path("/private/photo_sticker_mug_christmas.png"),
            Path("/private/photo_sticker_tea_oolong.png"),
            Path("/private/photo_sticker_snow_snowflake.png"),
            Path("/private/photo_sticker_date_feb_badge.png"),
            Path("/private/photo_overlay_fade_top.png"),
            Path("/private/photo_sticker_record_coffee_vinyl.png"),
        ]

    def test_inventory_never_uses_overlays_as_random_objects(self):
        found=inventory(self.photos)
        self.assertEqual(set(found),{"gift","mug","tea","snow","date_feb","record"})
        self.assertEqual(len(found["gift"]),2)

    def test_matching_requires_actual_concept_not_generic_video(self):
        words=[(.5,.75,"Сегодня"),(1.1,1.5,"маникюр"),
               (5.,5.4,"получится"),(8.,8.3,"красиво")]
        self.assertEqual(choose_object_cues(words,15,self.photos,"dynamic"),[])

    def test_exact_spoken_objects_are_included_and_not_overlapping(self):
        words=[(1.,1.35,"подарок"),(2.,2.3,"другу"),
               (7.,7.3,"чашку"),(12.,12.3,"феврале"),
               (17.,17.3,"чай"),(22.,22.3,"подарок")]
        cues=choose_object_cues(words,28,self.photos,"balanced")
        self.assertEqual([c.concept for c in cues],
                         ["gift","mug","date_feb","tea","gift"])
        for left,right in zip(cues,cues[1:]):
            self.assertLess(left.end+.25,right.start)
        self.assertNotEqual(cues[0].path,cues[-1].path)

    def test_negation_does_not_insert_gift(self):
        words=[(2.,2.2,"это"),(2.4,2.5,"не"),
               (2.7,3.2,"подарок")]
        self.assertEqual(choose_object_cues(words,8,self.photos,"dynamic"),[])

    def test_unsupported_concept_never_fabricated(self):
        words=[(2.,2.4,"кисточка"),(9.,9.3,"паста"),
               (14.,14.3,"салон")]
        self.assertEqual(choose_object_cues(words,18,self.photos,"dynamic"),[])

if __name__=="__main__":
    unittest.main()
