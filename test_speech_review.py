"""Unit tests for the human transcript-review and speech-driven zoom schedule."""
from __future__ import annotations

import unittest

from speech_review import align_corrected_words, apply_word_fixes, map_words_to_ranges, plain_transcript, shift_word_timestamps, plan_speech_repeats
from reference_editor import speech_zoom_windows, smooth_zoom_expression, editorial_zoom_expression
from telegram_editor import Segment, exclude_speech_repeats


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

    def test_editorial_zoom_keeps_the_close_up_until_next_phrase(self) -> None:
        words = [
            (0.1,0.4,"Первая"),(0.45,0.8,"фраза"),
            (3.7,4.1,"Вторая"),(4.15,4.5,"фраза"),
            (7.3,7.7,"Третья"),(7.73,8.15,"фраза"),
        ]
        expr = editorial_zoom_expression(words, duration=10.0, amplitude=0.17)
        self.assertIn("on", expr)
        self.assertNotIn("mod(", expr)
        self.assertIn("0.170", expr)
        self.assertTrue(expr.startswith("1+"))
        self.assertGreaterEqual(expr.count("0.170"), 2)

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



class SubtitleTimingTests(unittest.TestCase):
    def test_positive_delay_moves_titles_not_audio(self):
        words=[(0.10,0.35,"Слово"),(0.38,0.60,"другое"),(1.1,1.5,"фраза")]
        shifted=shift_word_timestamps(words,0.30,2.0)
        self.assertEqual([x[2] for x in shifted],[x[2] for x in words])
        self.assertAlmostEqual(shifted[0][0],0.40)
        self.assertAlmostEqual(shifted[1][0],0.68)
        self.assertAlmostEqual(shifted[2][0],1.40)

    def test_clamps_at_video_end_and_rejects_bad_offset(self):
        shifted=shift_word_timestamps([(0.7,0.95,"конец")],0.30,1.1)
        self.assertAlmostEqual(shifted[0][1],1.1)
        with self.assertRaises(ValueError):
            shift_word_timestamps([(0.7,0.95,"конец")],9.0,1.1)


class RetakeTests(unittest.TestCase):
    @staticmethod
    def words(text):
        return [(i*.6+.1,i*.6+.38,w) for i,w in enumerate(text.split())]

    def test_three_attempts_keep_latest_and_preserve_unique_words(self):
        raw=self.words("Сначала я покажу ошибку я покажу ошибку Я покажу ошибку дальше")
        kept,cuts=plan_speech_repeats(raw)
        self.assertEqual(plain_transcript(kept),"Сначала Я покажу ошибку дальше")
        self.assertEqual(kept[1],raw[7])
        self.assertEqual(len(cuts),2)
        ranges=exclude_speech_repeats([Segment(0,7)],cuts)
        for a,b,_ in kept:
            self.assertTrue(any(s.start<=a and s.end>=b for s in ranges))
        self.assertEqual(plain_transcript(map_words_to_ranges(raw,ranges,1.2)),
                         plain_transcript(kept))

    def test_restart_with_filler_and_continuation(self):
        raw=self.words("я покажу как э я покажу как правильно наносить гель")
        kept,cuts=plan_speech_repeats(raw)
        self.assertEqual(plain_transcript(kept),"я покажу как правильно наносить гель")
        self.assertEqual(len(cuts),1)
        self.assertEqual(kept[0],raw[4])

    def test_single_word_and_intentional_emphasis(self):
        raw=self.words("покрытие покрытие очень очень ровное")
        kept,cuts=plan_speech_repeats(raw)
        self.assertEqual(plain_transcript(kept),"покрытие очень очень ровное")
        self.assertEqual(kept[0],raw[1])
        self.assertEqual(len(cuts),1)

    def test_different_meaning_or_distant_repeat_is_preserved(self):
        for text in ("я покажу ошибку потом я покажу результат",
                     "первый шаг важен затем подпиливаем край первый шаг важен"):
            raw=self.words(text)
            self.assertEqual(plan_speech_repeats(raw),(raw,[]))
        raw=[(.1,.3,"покажу"),(.4,.7,"ошибку"),(12,12.3,"покажу"),(12.4,12.7,"ошибку")]
        self.assertEqual(plan_speech_repeats(raw),(raw,[]))

    def test_unsafe_overlapping_timestamps_are_not_cut(self):
        raw=[(.1,.5,"покрытие"),(.4,.7,"покрытие")]
        self.assertEqual(plan_speech_repeats(raw),(raw,[]))


    def test_real_revuall_three_rephrased_openings(self):
        text=("Девочки, мне кажется, я нашла буквально золото для мастеров, потому что это просто невероятно. "
              "Девочки, я, кажется, нашла просто золото для мастера Минкю. "
              "Это реальность, это не реклама, это просто рекомендация как от мастера, "
              "которая вот только начинала когда-то работать, и которому это действительно "
              "когда-то могло бы очень сильно помочь. потому что в какой-то момент я считала, "
              "что у меня просто плохие работы нет "
              "девочки, я кажется, нашла золото для мастеров маникюра особенно тем, "
              "кто только начинает работать я потом это покажу вблизи, "
              "потому что это просто невероятно какая у него консистенция, "
              "господи Я кайфую от этих гейлаков. Я скупила их все, потому что это невероятно. "
              "Это просто сто из десяти. Он буквально сам ложится под кучу. "
              "Вот момент особенно. Нет, нет, нет. Проверим.")
        raw=[(i*.30+.05,i*.30+.24,w) for i,w in enumerate(text.split())]
        kept,cuts=plan_speech_repeats(raw)
        clean=plain_transcript(kept)
        self.assertTrue(clean.startswith("девочки, я кажется, нашла золото для мастеров маникюра"))
        self.assertEqual(clean.lower().count("девочки"),1)
        self.assertNotIn("Это реальность",clean)
        self.assertNotIn("Нет, нет, нет.",clean)
        self.assertIn("Проверим.",clean)
        self.assertIn("Я скупила их все",clean)
        ranges=exclude_speech_repeats([Segment(0,raw[-1][1]+.1)],cuts)
        self.assertEqual(plain_transcript(map_words_to_ranges(raw,ranges,1.2)),clean)

    def test_unrelated_explanation_and_negation_remain(self):
        raw=self.words("Первый шаг важен. Теперь подпиливаем край. Первый шаг важен для результата.")
        self.assertEqual(plan_speech_repeats(raw),(raw,[]))
        raw=self.words("Это не реклама. Нет, это не реклама, а моя рекомендация.")
        kept,cuts=plan_speech_repeats(raw)
        self.assertIn("не реклама",plain_transcript(kept))
        raw=self.words("э покрытие эм должно быть ровным мм и тонким")
        kept,cuts=plan_speech_repeats(raw)
        self.assertEqual(plain_transcript(kept),"покрытие должно быть ровным и тонким")
        self.assertEqual(len(cuts),3)


if __name__=="__main__":
    unittest.main()
