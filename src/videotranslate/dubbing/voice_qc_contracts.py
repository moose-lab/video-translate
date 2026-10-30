"""Strict proof-bearing QC and human listening commands."""

from typing import Annotated, Literal

from pydantic import Field

from .contracts import ID, Fingerprint, SourceGuard, Strict
from .synthesis_contracts import ZeroRevision


class QCRow(Strict):
    id: ID
    translation_revision: ZeroRevision
    expected_source_text_fingerprint: Fingerprint
    selection_revision: ZeroRevision
    output_id: ID


class VoiceQC(SourceGuard):
    segments: Annotated[list[QCRow], Field(min_length=1, max_length=1000)]


class AudioReviewPut(SourceGuard):
    revision: ZeroRevision
    translation_revision: ZeroRevision
    expected_source_text_fingerprint: Fingerprint
    output_id: ID
    audio_selection_revision: ZeroRevision
    qc_evidence_fingerprint: Fingerprint
    decision: Literal["accepted", "rejected"]
    note: Annotated[str, Field(max_length=2000)] = ""
