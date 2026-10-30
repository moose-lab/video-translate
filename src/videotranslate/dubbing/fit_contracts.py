"""Strict bounded exact rational fit inputs; no implicit numeric conversion."""

from fractions import Fraction
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import Strict
from .synthesis_contracts import ZeroRevision

POLICY = "shared_fit_v1"


class Rate(Strict):
    numerator: Annotated[int, Field(ge=1, le=4_000_000)]
    denominator: Annotated[int, Field(ge=1, le=1_000_000)]

    @model_validator(mode="after")
    def canonical(self):
        value = self.fraction()
        self.numerator, self.denominator = value.numerator, value.denominator
        return self

    def fraction(self):
        return Fraction(self.numerator, self.denominator)


class FitSettingsBody(Strict):
    mode: Literal["fixed", "smart"] = "fixed"
    max_audio_speed: Rate = Field(default_factory=lambda: Rate(numerator=6, denominator=5))
    max_picture_factor: Rate = Field(default_factory=lambda: Rate(numerator=2, denominator=1))
    max_borrow_ms: Annotated[int, Field(ge=0, le=60_000)] = 0
    max_output_duration_ms: Annotated[int, Field(ge=1, le=57_600_000)] = 57_600_000

    @model_validator(mode="after")
    def range_check(self):
        if (
            not 1 <= self.max_audio_speed.fraction() <= 2
            or not 1 <= self.max_picture_factor.fraction() <= 4
        ):
            raise ValueError("Fit factor out of range")
        return self

    def pure(self):
        from ..media.fit_types import FitSettings

        return FitSettings(
            self.mode,
            self.max_audio_speed.fraction(),
            self.max_picture_factor.fraction(),
            self.max_borrow_ms,
            self.max_output_duration_ms,
        )


class FitSettingsPut(Strict):
    revision: ZeroRevision
    settings: FitSettingsBody


from .contracts import ID, Fingerprint, SourceGuard  # noqa: E402


class FitRow(Strict):
    id: ID
    expected_source_revision_id: ID
    expected_source_text_fingerprint: Fingerprint
    translation_revision: ZeroRevision
    selection_revision: ZeroRevision
    output_id: ID | None
    review_revision: ZeroRevision
    qc_evidence_fingerprint: Fingerprint | None


class FitTrack(Strict):
    tag: Annotated[str, Field(min_length=2, max_length=40)]
    segments: Annotated[list[FitRow], Field(min_length=1, max_length=1000)]


class FitPlanCreate(SourceGuard):
    settings_revision: ZeroRevision
    purpose: Literal["dub", "incomplete_preview", "original_only"]
    tracks: Annotated[list[FitTrack], Field(max_length=16)]

    @model_validator(mode="after")
    def bounded_cells(self):
        if sum(len(t.segments) for t in self.tracks) > 1000:
            raise ValueError("Fit row limit")
        if (self.purpose == "original_only") != (not self.tracks):
            raise ValueError("Fit purpose requires explicit targets or original only")
        if self.purpose != "original_only" and self.transcript_revision is None:
            raise ValueError("Transcript required")
        if any(len({r.id for r in t.segments}) != len(t.segments) for t in self.tracks):
            raise ValueError("Duplicate fit cell")
        return self


class FitOptions(Strict):
    command_id: ID
