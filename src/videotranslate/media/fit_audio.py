"""Derived local media only; natural output/QC identity is never mutated."""

from fractions import Fraction
from pathlib import Path
from typing import Callable

from .audio import AudioFile
from .finishing_types import RenderLimits
from .fit_plan import validate_plan
from .fit_types import FitPlan
from .float_audio import invalid
from .offline_warp import warp


def fit_voice(
    natural: AudioFile,
    destination: Path,
    *,
    speed: Fraction,
    limits: RenderLimits,
    check: Callable[[], None],
) -> AudioFile:
    if type(speed) is not Fraction or not 1 <= speed <= 2 or speed.denominator > 1000000:
        raise invalid()
    return warp(natural, destination, ratio=1 / speed, limits=limits, check=check)


def retime_audio(
    audio: AudioFile,
    plan: FitPlan,
    destination: Path,
    *,
    limits: RenderLimits,
    check: Callable[[], None],
) -> AudioFile:
    validate_plan(plan)
    if not plan.feasible:
        raise invalid()
    knots = tuple((Fraction(p.source_start_ms * 48), p.output_start_ms * 48) for p in plan.pieces)
    knots += ((Fraction(plan.source_duration_ms * 48), plan.output_duration_ms * 48),)
    return warp(audio, destination, knots=knots, limits=limits, check=check)
