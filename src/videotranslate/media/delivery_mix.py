"""48 kHz stereo float sum; overlap is additive with explicit uniform protection."""

import hashlib
import json
import math
import tempfile
from array import array
from fractions import Fraction
from pathlib import Path

from .float_audio import (
    CHANNELS,
    FRAME_BYTES,
    Budget,
    _normalize,
    blocks,
    finish,
    invalid,
    measure,
    write_block,
)


def mix(background, voices, destination, *, background_gain, voice_gain, limits, check):
    if any(
        type(g) not in {float, int}
        or isinstance(g, bool)
        or not math.isfinite(g)
        or not 0 <= g <= 4
        for g in (background_gain, voice_gain)
    ):
        raise invalid()
    with tempfile.TemporaryDirectory(prefix="vt-mix-", dir=Path(destination).parent) as directory:
        root = Path(directory)
        budget = Budget(limits, check, root)
        bed = _normalize(background, root / "bed.raw", budget)
        budget.preflight(bed.byte_size)
        summed = root / "sum.raw"
        with summed.open("xb") as out:
            for values in blocks(bed.path, budget.check):
                write_block(out, array("f", (x * background_gain for x in values)))
        placements = []
        for i, (voice, onset, end) in enumerate(voices):
            if type(onset) is not Fraction or type(end) is not Fraction or not 0 <= onset < end:
                raise invalid()
            start = round(onset * 48)
            expected_end = round(end * 48)
            raw = _normalize(voice, root / f"voice-{i}.raw", budget)
            # NaturalOutput stores nearest integer ms: ±0.5 ms = 24 frames at 48k.
            # Speeds are >=1, so fitting cannot amplify that uncertainty. Allow two
            # additional frames for duration/onset nearest-sample rounding. This
            # finite quantization allowance never extends the common bed capacity.
            if start + raw.frames > bed.frames or start + raw.frames > expected_end + 26:
                raise invalid()
            with summed.open("r+b") as output:
                position = start
                for values in blocks(raw.path, budget.check):
                    output.seek(position * FRAME_BYTES)
                    current = array("f")
                    current.frombytes(output.read(len(values) * 4))
                    if len(current) != len(values):
                        raise invalid()
                    combined = array(
                        "f", (a + b * voice_gain for a, b in zip(current, values, strict=True))
                    )
                    output.seek(position * FRAME_BYTES)
                    write_block(output, combined)
                    position += len(values) // CHANNELS
            placements.append(
                dict(
                    onset_sample=start,
                    actual_samples=raw.frames,
                    declared_end_sample=expected_end,
                    declared_end_overrun_samples=max(0, start + raw.frames - expected_end),
                    tail_policy="preserve_actual_no_fill_no_trim",
                )
            )
            raw.path.unlink()
        unprotected = measure(summed, budget)
        gain = min(1.0, 0.98 / unprotected.peak) if unprotected.peak else 1.0
        protected = root / "protected.raw"
        budget.preflight(unprotected.byte_size)
        with protected.open("xb") as out:
            for values in blocks(summed, budget.check):
                write_block(out, array("f", (x * gain for x in values)))
        final = measure(protected, budget)
        if final.peak > 0.980001:
            raise invalid()
        return finish(
            protected,
            destination,
            budget,
            dict(
                policy="float_additive_uniform_ceiling_v1",
                background_gain=background_gain,
                voice_gain=voice_gain,
                unprotected_peak=unprotected.peak,
                applied_uniform_gain=gain,
                protected_peak=final.peak,
                voice_count=len(placements),
                placement_rounding_tolerance_samples=26,
                max_declared_end_overrun_samples=max(
                    (p["declared_end_overrun_samples"] for p in placements), default=0
                ),
                placement_rounding_policy="natural_nearest_ms_24_frames_plus_two_roundings_v1",
                placements_sha256=hashlib.sha256(
                    json.dumps(placements, sort_keys=True).encode()
                ).hexdigest(),
                ceiling=0.98,
            ),
        )
