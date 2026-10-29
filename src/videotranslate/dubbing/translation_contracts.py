"""Finite command guards; provider dialogue never enters public run options."""

from typing import Annotated

from pydantic import Field

from .contracts import ID, Fingerprint, Revision, SourceGuard, Strict


class TranslationRow(Strict):
    id: ID
    revision: Annotated[int, Field(ge=0, le=2**31 - 1)]
    expected_source_text_fingerprint: Fingerprint
    locked: bool
    approved: bool


class TranslateCommand(SourceGuard):
    track_revision: Revision
    segments: Annotated[list[TranslationRow], Field(min_length=1, max_length=1000)]
    force_replace: bool = False


class PhaseOptions(Strict):
    phase_id: ID


class SuggestionApply(SourceGuard):
    phase_id: ID
    segments: Annotated[list[TranslationRow], Field(min_length=1, max_length=200)]
