"""Bounded, block-streamed PCM envelope; sample frames are the only time grid."""

import hashlib
import math
import sys
import time
import wave
from array import array
from pathlib import Path

from ..execution.contracts import FailureCode, StageFailure

POLICY = "pcm-envelope-v1"
MAX_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024


def inspect_wave_pcm(source, max_duration=14400):
    """Measured per-channel sample count, without rounding duration to milliseconds."""
    if (
        source.getsampwidth() != 2
        or source.getcomptype() != "NONE"
        or not 1 <= source.getnchannels() <= 8
        or not 8000 <= source.getframerate() <= 192000
        or not 0 < source.getnframes() <= max_duration * source.getframerate()
    ):
        raise StageFailure(FailureCode.INVALID_MEDIA)
    return source.getnframes(), source.getframerate(), source.getnchannels()


def envelope(
    path,
    *,
    expected_sha256,
    bins=600,
    max_bytes=MAX_BYTES,
    timeout=60,
    max_duration=14400,
    check=lambda: None,
):
    if type(bins) is not int or not 1 <= bins <= 2000:
        raise ValueError("Invalid waveform bin count")
    deadline = time.monotonic() + timeout

    def active():
        check()
        if time.monotonic() > deadline:
            raise StageFailure(FailureCode.MEDIA_LIMIT)

    path = Path(path)
    active()
    if not 0 < path.stat().st_size <= max_bytes:
        raise StageFailure(FailureCode.MEDIA_LIMIT)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            active()
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise StageFailure(FailureCode.INVALID_MEDIA)
    try:
        with wave.open(str(path)) as source:
            frames, rate, channels = inspect_wave_pcm(source, max_duration)
            count = min(bins, frames)
            rows = []
            # Each bin covers [floor(i*N/B), floor((i+1)*N/B)); no tail is dropped.
            for i in range(count):
                start, end = i * frames // count, (i + 1) * frames // count
                remaining, lo, hi, squares = end - start, 32767, -32768, 0
                while remaining:
                    active()
                    amount = min(4096, remaining)
                    data = source.readframes(amount)
                    if len(data) != amount * channels * 2:
                        raise StageFailure(FailureCode.INVALID_MEDIA)
                    values = array("h", data)
                    if sys.byteorder != "little":
                        values.byteswap()
                    lo, hi = min(lo, min(values)), max(hi, max(values))
                    squares += sum(value * value for value in values)
                    remaining -= amount
                rows.append(
                    dict(
                        start_sample=start,
                        end_sample=end,
                        min=lo / 32768,
                        max=hi / 32768,
                        rms=math.sqrt(squares / ((end - start) * channels)) / 32768,
                    )
                )
            if source.readframes(1):
                raise StageFailure(FailureCode.INVALID_MEDIA)
    except (wave.Error, EOFError, OSError):
        raise StageFailure(FailureCode.INVALID_MEDIA) from None
    return dict(
        policy=POLICY,
        input_sha256=expected_sha256,
        sample_rate=rate,
        channels=channels,
        sample_count=frames,
        duration_ms=frames * 1000 / rate,
        bin_count=count,
        bins=rows,
    )
