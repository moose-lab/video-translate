"""Blockwise target-specific source union replacement with complementary fades."""

import tempfile
from array import array
from pathlib import Path
from typing import Callable

from .audio import AudioFile
from .finishing_types import RenderLimits, rational
from .fit_types import MAX_LINES, MAX_SOURCE_MS
from .float_audio import Budget, _normalize, blocks, finish, invalid, write_block


def _union(source_duration_ms, intervals, fade):
    if (
        type(source_duration_ms) is not int
        or not 1 <= source_duration_ms <= MAX_SOURCE_MS
        or type(intervals) is not tuple
        or len(intervals) > MAX_LINES
        or type(fade) is not int
        or not 0 <= fade <= 100
    ):
        raise invalid()
    for pair in intervals:
        if (
            type(pair) is not tuple
            or len(pair) != 2
            or any(type(v) is not int for v in pair)
            or not 0 <= pair[0] < pair[1] <= source_duration_ms
        ):
            raise invalid()
    merged = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    if any(2 * fade > b - a for a, b in merged):
        raise invalid()
    return merged


def build_background(
    working: AudioFile,
    instrumental: AudioFile,
    destination: Path,
    *,
    source_duration_ms: int,
    dialogue_intervals: tuple[tuple[int, int], ...],
    crossfade_ms: int,
    limits: RenderLimits,
    check: Callable[[], None],
) -> AudioFile:
    merged = _union(source_duration_ms, dialogue_intervals, crossfade_ms)
    destination = Path(destination)
    if destination.exists():
        raise invalid()
    expected = source_duration_ms * 48
    with tempfile.TemporaryDirectory(prefix="vt-bed-", dir=destination.parent) as d:
        directory = Path(d)
        budget = Budget(limits, check, directory)
        budget.preflight(expected * 8 + 4096)
        original = _normalize(working, directory / "working.raw", budget)
        bed = _normalize(instrumental, directory / "instrumental.raw", budget)
        if original.frames != expected or bed.frames != expected:
            raise invalid()
        intervals = [(a * 48, b * 48) for a, b in merged]
        fade, current, position = crossfade_ms * 48, 0, 0
        output = directory / "background.raw"
        budget.preflight(expected * 8)
        with output.open("xb") as out:
            for work, music in zip(
                blocks(original.path, budget.check), blocks(bed.path, budget.check), strict=True
            ):
                mixed = array("f")
                for i in range(len(work) // 2):
                    while current < len(intervals) and position >= intervals[current][1]:
                        current += 1
                    weight = 0.0
                    if current < len(intervals):
                        a, b = intervals[current]
                        if a <= position < b:
                            weight = (
                                1.0
                                if not fade
                                else min(1, (position - a) / fade, (b - position) / fade)
                            )
                    mixed.extend(
                        work[i * 2 + c] * (1 - weight) + music[i * 2 + c] * weight for c in (0, 1)
                    )
                    position += 1
                budget.check()
                write_block(out, mixed)
        return finish(
            output,
            destination,
            budget,
            {
                "policy": "source-union-linear-inside-v1",
                "dialogue_union_ms": merged,
                "crossfade_ms": crossfade_ms,
                "planned_duration_ms": rational(source_duration_ms),
                "working_sha256": working.sha256,
                "instrumental_sha256": instrumental.sha256,
                "working_only": not merged,
            },
        )
