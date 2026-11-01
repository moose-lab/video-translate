"""Exact sample coordinates and versioned, proved DSP-only control compaction."""

import json
import math
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

from .finishing_types import rational
from .float_audio import MAX_FRAMES, Budget, _normalize, finish, invalid, measure

CONTROL_POLICY = "rdp-exact-knot-4ms-v1"
CONTROL_ERROR = Fraction(48000 * 4, 1000)


def control_map(knots, *, check=lambda: None):
    if type(knots) is not tuple or not 2 <= len(knots) <= 3002:
        raise invalid()
    check()
    previous = (Fraction(-1), Fraction(-1))
    for point in knots:
        if (
            type(point) is not tuple
            or len(point) != 2
            or any(type(v) is not Fraction or v.denominator > 1000000 for v in point)
            or not previous[0] < point[0]
            or not previous[1] < point[1]
        ):
            raise invalid()
        if (
            previous[0] >= 0
            and not Fraction(1, 2) <= (point[1] - previous[1]) / (point[0] - previous[0]) <= 4
        ):
            raise invalid()
        previous = point
    if (
        knots[0] != (0, 0)
        or not 1 <= knots[-1][0] <= MAX_FRAMES
        or not (1 <= knots[-1][1] <= MAX_FRAMES)
    ):
        raise invalid()
    # Iterative Ramer-Douglas-Peucker with vertical error in exact output samples.
    # Error between two piecewise linear functions is maximal at an original
    # knot. Checking every original knot is consequently a complete proof.
    keep, stack = {0, len(knots) - 1}, [(0, len(knots) - 1)]
    while stack:
        check()
        a, b = stack.pop()
        x0, y0 = knots[a]
        x1, y1 = knots[b]
        worst, where = Fraction(0), None
        for i in range(a + 1, b):
            if i % 128 == 0:
                check()
            x, y = knots[i]
            error = abs(y - (y0 + (x - x0) * (y1 - y0) / (x1 - x0)))
            if error > worst:
                worst, where = error, i
        if worst > CONTROL_ERROR:
            keep.add(where)
            stack.extend(((a, where), (where, b)))
    indices = sorted(keep)
    actual_bound = Fraction(0)
    rounded_bound = Fraction(0)
    for a, b in zip(indices, indices[1:], strict=False):
        x0, y0 = knots[a]
        x1, y1 = knots[b]
        rx0, ry0, rx1, ry1 = map(round, (x0, y0, x1, y1))
        if not rx0 < rx1 or not ry0 < ry1:
            raise invalid()
        check()
        for x, y in knots[a : b + 1]:
            actual_bound = max(actual_bound, abs(y - (y0 + (x - x0) * (y1 - y0) / (x1 - x0))))
            rounded_bound = max(
                rounded_bound, abs(y - (ry0 + (x - rx0) * Fraction(ry1 - ry0, rx1 - rx0)))
            )
    # Reject rounded-control conflicts and >5ms proof instead of dropping knots.
    if rounded_bound > 240:
        raise invalid()
    keys = [[round(knots[i][0]), round(knots[i][1])] for i in indices[1:-1]]
    return keys, actual_bound, rounded_bound


def warp(audio, destination, *, knots=None, ratio=None, limits, check):
    destination = Path(destination)
    if destination.exists():
        raise invalid()
    with tempfile.TemporaryDirectory(prefix="vt-warp-", dir=destination.parent) as d:
        directory = Path(d)
        budget = Budget(limits, check, directory)
        raw = _normalize(audio, directory / "input.raw", budget)
        if ratio is not None:
            if type(ratio) is not Fraction or not Fraction(1, 2) <= ratio <= 4:
                raise invalid()
            knots = ((Fraction(0), Fraction(0)), (Fraction(raw.frames), raw.frames * ratio))
        keys, error, rounded_error = control_map(knots, check=budget.check)
        expected_input, expected_output = round(knots[-1][0]), round(knots[-1][1])
        budget.preflight(expected_output * 8 + 4096)
        if raw.frames != expected_input:
            raise invalid()
        facts = {
            "policy": CONTROL_POLICY,
            "planned_duration_ms": rational(knots[-1][1] / 48),
            "input_sha256": audio.sha256,
            "input_samples": raw.frames,
            "original_knots": len(knots),
            "interior_controls": len(keys),
            "control_error_samples": rational(error),
            "rounded_control_error_samples": rational(rounded_error),
            "endpoint_rounding_samples": rational(Fraction(expected_output) - knots[-1][1]),
        }
        if all(x == y for x, y in knots):
            return finish(
                raw.path, destination, budget, {**facts, "engine": "identity", "pitch_scale": 1}
            )
        facts.update(
            {
                "native_policy": "r3-standard-process-512-v1",
                "study_block_frames": 4096,
                "process_block_frames": 512,
            }
        )
        budget.preflight(expected_output * 8)
        config, report = directory / "controls.json", directory / "receipt.json"
        config.write_text(
            json.dumps({"input_frames": raw.frames, "output_frames": expected_output, "keys": keys})
        )
        output = directory / "warped.raw"
        budget.run(
            [
                sys.executable,
                str(Path(__file__).with_name("offline_warp_runner.py")),
                str(config),
                str(raw.path),
                str(output),
                str(report),
                str(directory / "phase"),
            ],
            output=output,
        )
        try:
            if report.stat().st_size > 4096:
                raise ValueError()
            result = json.loads(report.read_text())
            if (
                set(result) != {"engine", "pitch_scale", "input_frames", "output_frames", "peak"}
                or type(result["engine"]) is not int
                or result["engine"] != 3
                or type(result["pitch_scale"]) is not int
                or result["pitch_scale"] != 1
                or type(result["input_frames"]) is not int
                or result["input_frames"] != raw.frames
                or type(result["output_frames"]) is not int
                or result["output_frames"] != expected_output
                or type(result["peak"]) not in (int, float)
                or not math.isfinite(result["peak"])
                or result["peak"] < 0
            ):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise invalid() from None
        measured = measure(output, budget)
        if measured.frames != expected_output or abs(measured.peak - result["peak"]) > 1e-6:
            raise invalid()
        return finish(output, destination, budget, {**facts, **result})
