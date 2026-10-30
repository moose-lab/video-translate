"""Immutable, bounded values for pure shared timing policy."""

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

MAX_SOURCE_MS = 14_400_000
MAX_OUTPUT_MS = 57_600_000
MAX_LINES = 1000
FACTOR_PRECISION = 1_000_000


class FitInputError(ValueError):
    """Only bounded public codes, never caller values, cross this boundary."""

    def __init__(self, code: str):
        if type(code) is not str or code not in {
            "INVALID_FIT_INPUT",
            "INVALID_FIT_TIME",
            "INVALID_FIT_PLAN",
            "FIT_PLAN_MISMATCH",
        }:
            code = "INVALID_FIT_INPUT"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FitSettings:
    mode: Literal["fixed", "smart"] = "fixed"
    max_audio_speed: Fraction = Fraction(6, 5)
    max_picture_factor: Fraction = Fraction(2)
    max_borrow_ms: int = 0
    max_output_duration_ms: int = MAX_OUTPUT_MS


@dataclass(frozen=True)
class FitLine:
    track_key: str
    segment_key: str
    role_key: str | None
    start_ms: int
    end_ms: int
    natural_duration_ms: int


@dataclass(frozen=True)
class MapPiece:
    source_start_ms: int
    source_end_ms: int
    output_start_ms: Fraction
    output_end_ms: Fraction


@dataclass(frozen=True)
class LinePlacement:
    track_key: str
    segment_key: str
    available_source_end_ms: int
    borrowed_ms: int
    output_start_ms: Fraction
    source_caption_end_ms: Fraction
    required_audio_speed: Fraction
    audio_speed: Fraction | None
    voice_end_ms: Fraction | None


@dataclass(frozen=True)
class FitIssue:
    code: Literal["LINE_FIT_LIMIT", "OUTPUT_DURATION_LIMIT"]
    track_key: str | None = None
    segment_key: str | None = None


@dataclass(frozen=True)
class FitPlan:
    source_duration_ms: int
    settings: FitSettings
    lines: tuple[FitLine, ...]
    pieces: tuple[MapPiece, ...]
    placements: tuple[LinePlacement, ...]
    issues: tuple[FitIssue, ...]

    @property
    def feasible(self) -> bool:
        return not self.issues

    @property
    def output_duration_ms(self) -> Fraction:
        return self.pieces[-1].output_end_ms
