"""Small deterministic CPU-only media fixtures and block measurements."""

import hashlib
import math
import struct
from array import array
from fractions import Fraction

from videotranslate.media.audio import validate_audio
from videotranslate.media.fit_plan import build_plan
from videotranslate.media.fit_types import FitLine, FitSettings

RATE = 48000


def float_wav(path, frames, channels=2, sample=lambda i, c: 0.0):
    size = frames * channels * 4
    with path.open("wb") as f:
        f.write(
            struct.pack(
                "<4sI4s4sIHHIIHH4sI",
                b"RIFF",
                size + 36,
                b"WAVE",
                b"fmt ",
                16,
                3,
                channels,
                RATE,
                RATE * channels * 4,
                channels * 4,
                32,
                b"data",
                size,
            )
        )
        for start in range(0, frames, 4096):
            a = array(
                "f",
                (
                    sample(i, c)
                    for i in range(start, min(frames, start + 4096))
                    for c in range(channels)
                ),
            )
            f.write(a.tobytes())
    return validate_audio(path)


def marked(path, seconds=4, channels=2, amplitude=1.4):
    marks = [
        (0.01, 0.15, 400),
        (0.85, 0.99, 600),
        (1.85, 1.99, 800),
        (2.85, 2.99, 1000),
        (seconds - 0.15, seconds - 0.01, 1200),
    ]

    def sample(i, c):
        t = i / RATE
        for a, b, hz in marks:
            if a <= t < b:
                return amplitude * math.sin(2 * math.pi * (hz + c * 100) * t)
        return 0.0

    return float_wav(path, round(seconds * RATE), channels, sample), marks


def golden_plan():
    return build_plan(
        4000,
        [FitLine("zh", "a", "r", 0, 2000, 3000), FitLine("zh", "b", "s", 1000, 3000, 4000)],
        FitSettings(mode="smart", max_audio_speed=Fraction(1)),
    )


def sha(path):
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
