"""Original short audio accents synchronized to animated subtitle phrases.

The reference uses distinct kinetic typography; this is an original
procedural approximation of its *sound-design grammar*, not audio copied
from the user's reference. Keep the original spoken audio intact.
"""
from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path
from typing import Sequence

EVENT_LENGTH = {
    "air": 0.30,     # soft ascending airy swish on a sliding large headline
    "paper": 0.16,   # delicate brush/flick for small paper labels
    "pop": 0.125,    # rounded non-metallic pop on a emphasized word
    "silk": 0.245,   # soft two-step texture for elegant flowing lettering
}
EVENT_GAIN = {"air": 0.15, "paper": 0.12, "pop": 0.14, "silk": 0.11}


def render_caption_sounds(
    target: Path,
    cues: Sequence[tuple[float, str | None]],
    duration: float,
    rate: int = 48000,
) -> None:
    """Make a *single*, quiet, time-aligned WAV with varied original accents.

    A sample is synthesized only at the start of a displayed subtitle phrase,
    never for every word. We accumulate into one mono track (mixed downstream
    under the voice) and use smooth envelopes without clipping.
    """
    if not 8000 <= rate <= 96000:
        raise ValueError("Invalid audio sample rate")
    total = max(1, round(max(0.0, duration) * rate))
    output = array("h", [0]) * total
    for event_index, (moment, kind) in enumerate(sorted(cues)):
        family = kind if kind in EVENT_LENGTH else "pop"
        at = round(max(0.0, float(moment)) * rate)
        if at >= total:
            continue
        length = min(total-at, int(EVENT_LENGTH[family] * rate))
        if length <= 0:
            continue
        smooth_noise = 0.0
        for i in range(length):
            t = i / rate
            p = i / max(1, length-1)
            # Reproducible noise without relying on random seeds or libraries.
            seed = (i * 1664525 + 1013904223 + event_index * 30489) & 0xFFFFFFFF
            white_noise = 2.0 * ((seed >> 8) / 16777216.0) - 1.0
            smooth_noise = smooth_noise * 0.77 + white_noise * 0.23
            if family == "air":
                envelope = math.sin(math.pi*p) ** 1.7
                sweep = math.sin(2*math.pi*(430 + 600*p)*t)
                sample = .73*smooth_noise + .27*sweep
            elif family == "paper":
                # Two low-volume tactile paper brushes.
                second = max(0.0, t-0.068)
                envelope = (
                    (1-math.exp(-t*340))*math.exp(-t*34)
                    + .46*(1-math.exp(-second*260))*math.exp(-second*72)
                )
                sample = .80*smooth_noise+.20*math.sin(2*math.pi*690*t)
            elif family == "silk":
                envelope = math.sin(math.pi*p) ** 1.9
                sweep = math.sin(2*math.pi*(740 - 195*p)*t)
                sample = .57*sweep + .43*smooth_noise
            else:
                # A soft rounded bounce, not a loud notification bell.
                envelope = (1-math.exp(-t*210))*math.exp(-t*34)
                sample = (
                    .70*math.sin(2*math.pi*(570 - 210*p)*t)
                    + .19*math.sin(2*math.pi*840*t)
                    + .11*smooth_noise
                )
            value = round(32767 * EVENT_GAIN[family] * envelope * sample)
            current = output[at+i] + value
            output[at+i] = max(-32760, min(32760, current))
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(output.tobytes())
