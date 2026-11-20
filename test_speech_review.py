"""Unit tests for the human transcript-review and speech-driven zoom schedule."""
from __future__ import annotations

import unittest

from speech_review import align_corrected_words, apply_word_fixes, map_words_to_ranges, plain_transcript
from reference_editor import speech_zoom_windows, smooth_zoom_expression
from telegram_editor import Segment


class TranscriptReviewTests(unittest.TestCase):
    def test_explicitly_corrected_words_are_never_replaced(self) -> None:
        draft=[
            (0.12,0.39,"Привет"),
            (0.40,0.85,"молако"),
            (0.86,1.25,"сегодня"),
        ]
        corrected="Привет молоко сегодня"
        result=align_corrected_words(draft,corrected,duration=1.4)
        self.assertEqual(" ".join(w[2] for w in result),corrected)
        self.assertEqual(result[1][0], draft[1][0])

    def test_added_words_and_empty_speech(self) -> None:
        original=[(0.1,0.45,"Добрый"),(0.5,1.0,"день")]
        for source in (original, []):
            result=align_corrected_words(source,"Добрый солнечный день",duration=1.5)
            self.assertEqual(plain_transcript(result),"Добрый солнечный день")
            self.assertTrue(all(a < b for a,b,_ in result))

    def test_targeted_fixes_keep_original_timing(self) -> None:
        original = [(0.1,0.3,"гелак"),(0.31,0.68,"получается"),(0.7,1.1,"плохой")]
        corrected = apply_word_fixes(original,"гелак=гель-лак; плохой=неровный")
        self.assertEqual(plain_transcript(corrected),"гель-лак получается неровный")
        self.assertEqual(corrected[0][0:2], original[0][0:2])
        with self.assertRaises(ValueError):
            apply_word_fixes(original, "несуществующее=правильно")

    def test_cut_and_speed_timestamp_mapping(self) -> None:
        source=[
            (0.1,0.3,"первое"),
            (2.1,2.4,"второе"),
            (3.1,3.4,"третье"),
        ]
        kept=[Segment(0.0,0.5),Segment(2.0,3.5)]
        result=map_words_to_ranges(source,kept,speed=1.25)
        self.assertEqual([x[2] for x in result],["первое","второе","третье"])
        self.assertAlmostEqual(result[1][0],0.48,places=2)

    def test_zoom_is_keyed_to_phrases_not_every_second(self) -> None:
        words=[]
        for i in range(45):
            t=0.1+i*0.35
            words.append((t,t+0.27,f"слово{i}"))
        windows=speech_zoom_windows(words,duration=18)
        self.assertTrue(windows)
        self.assertLess(len(windows),7)
        self.assertTrue(all(b>a for a,b in windows))
        self.assertIn("on",smooth_zoom_expression(windows,0.16))


if __name__=="__main__":
    unittest.main()
