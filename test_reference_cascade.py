"""Reference-derived incremental Reels typography without floating backplates."""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image,ImageChops
from reference_cascade_captions import build_reference_cascade_ass
from reference_dynamic_captions import phrase_groups


class CascadeSubtitleTests(unittest.TestCase):
    WORDS=[
        (.05,.24,"Только"),(.28,.46,"не"),
        (.55,.98,"Говорите"),(1.08,1.31,"что"),
        (1.87,2.08,"До"),(2.12,2.34,"сих"),
        (2.38,2.63,"пор"),(2.72,3.21,"вручную"),
        (3.66,4.12,"Монтируете"),(4.18,4.52,"рилсы"),
    ]

    def test_words_accumulate_within_one_phrase_no_flash_reset(self):
        ass,count=build_reference_cascade_ass(self.WORDS,background_style="always")
        self.assertIn("Style: CascadeBig,",ass)
        self.assertIn("Style: CascadeSmall,",ass)
        self.assertIn("Style: CascadeHalo,",ass)
        text_rows=[line for line in ass.splitlines() if line.startswith("Dialogue: 2,")]
        halo_rows=[line for line in ass.splitlines() if line.startswith("Dialogue: 1,")]
        self.assertEqual(len(text_rows),len(self.WORDS))
        self.assertEqual(len(halo_rows),len(self.WORDS))
        self.assertEqual(count,len(text_rows)+len(halo_rows))
        self.assertEqual(len(phrase_groups(self.WORDS)),3)
        self.assertIn("ГОВОРИТЕ",ass)
        self.assertIn("ВРУЧНУЮ",ass)
        # The first small word stays on screen until the full phrase ends,
        # while big keyword joins later. This is not word-by-word replacement.
        only=text_rows[0].split(",")
        main=next(line for line in text_rows if "ГОВОРИТЕ" in line)
        self.assertEqual(only[2],main.split(",")[2])  # shared phrase end
        self.assertLess(float(only[1].split(":")[-1]),
                        float(main.split(",")[1].split(":")[-1]))
        # Every soft oval shares the exact timing and animated position of
        # its own printed word, so it cannot hover away from the letters.
        for shadow,word in zip(halo_rows,text_rows):
            self.assertEqual(shadow.split(",")[1:3],word.split(",")[1:3])
            move=lambda item:tuple(int(k) for k in
                re.search(r"\\move\(([^)]+)\)",item).group(1).split(","))
            ax,ay,bx,by,_,_=move(shadow)
            cx,cy,dx,dy,_,_=move(word)
            # The shadow has TOP-LEFT ASS anchoring and the glyph CENTER:
            # compare motion delta and measured capsule center, not x/y.
            self.assertLessEqual(abs((bx-ax)-(dx-cx)),1)
            self.assertLessEqual(abs((by-ay)-(dy-cy)),1)
            shape=re.search(r"}m \d+ 0 l \d+ 0 b \d+ 0 (\d+)",shadow)
            self.assertIsNotNone(shape)
            width=int(shape.group(1))
            radius=int(re.search(r"}m (\d+) 0",shadow).group(1))
            self.assertLessEqual(abs(ax+width/2-cx),2)
            self.assertLessEqual(abs(ay+radius-cy),2)
            self.assertIn(r"\p1",shadow)
            self.assertNotIn(r"\p1",word)
            self.assertIn(r"\blur5.3",shadow)
            self.assertIn(r"\1a&HAD&",shadow)
        self.assertNotIn("BorderStyle=3",ass)

    def test_alternating_left_right_and_mixed_sizes_remain_safe(self):
        ass,_=build_reference_cascade_ass(
            self.WORDS,background_style="occasional",
            font_profile="old_money",small_font_profile="refined")
        text=[x for x in ass.splitlines() if x.startswith("Dialogue: 2,")]
        xpos=[]
        for line in text:
            match=re.search(r"\\move\((\d+),(\d+),(\d+),(\d+),0,(\d+)\)",line)
            self.assertIsNotNone(match)
            x0,y0,x1,y1,ms=(int(z) for z in match.groups())
            xpos.append(x1)
            self.assertTrue(85<=x1<=635)
            self.assertTrue(430<=y1<=950)
            self.assertTrue(ms>=100)
        self.assertGreater(len(set(xpos)),3)
        sizes={int(s) for s in re.findall(r"\\fs(\d+)",ass)}
        self.assertGreater(max(sizes),min(sizes)+10)
        self.assertIn("CascadeBig",ass)
        self.assertIn("CascadeSmall",ass)

    def test_real_ffmpeg_incremental_words_arrive_without_separate_shadow(self):
        with tempfile.TemporaryDirectory(prefix="cascade_subtitle_") as tmp:
            root=Path(tmp)
            ass=root/"caption.ass"
            text,_=build_reference_cascade_ass(
                self.WORDS,background_style="always",
                caption_variant="reference_soft"
            )
            ass.write_text(text,encoding="utf-8")
            crops=[]
            for when in (0.39,0.80):
                image=root/f"{when:.2f}.png"
                subprocess.run([
                    "ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-f","lavfi","-i","color=c=#25202b:s=720x1280:r=15:d=1.5",
                    "-vf",f"ass={ass}",
                    "-ss",str(when),"-frames:v","1",str(image)
                ],check=True,capture_output=True,timeout=60)
                with Image.open(image) as im:
                    crops.append(im.convert("RGB").copy())
            # Keyword appears at ~.55; pixel image must differ after it joins.
            self.assertIsNotNone(ImageChops.difference(crops[0],crops[1]).getbbox())
            for im in crops:
                outside=(im.crop((0,0,71,1280)),
                         im.crop((649,0,720,1280)))
                # Avoid hardcoding uncompressed RGB: FFmpeg conversion from
                # yuv420p shifts the nominal hex channels by 1-3 units.
                background=Image.new("RGB",(71,1280),im.getpixel((0,0)))
                for border in outside:
                    delta=ImageChops.difference(border,background)
                    self.assertTrue(all(ch.getextrema()[1]<=3
                                        for ch in delta.split()))


if __name__=="__main__":
    unittest.main()
