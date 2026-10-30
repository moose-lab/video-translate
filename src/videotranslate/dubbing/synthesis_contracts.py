"""Strict bounded synthesis commands. Selection does not approve listening or QC."""

from typing import Annotated

from pydantic import Field

from .contracts import ID, Fingerprint, SourceGuard, Strict

ZeroRevision = Annotated[int, Field(ge=0, le=2**31 - 1)]


class Controls(Strict):
    ns: Annotated[int, Field(ge=4, le=64)] = 32
    gs: Annotated[float, Field(ge=0, le=4, allow_inf_nan=False)] = 2.0
    dn: bool = True
    sp: Annotated[float, Field(ge=0.5, le=1.5, allow_inf_nan=False)] = 1.0
    du: Annotated[float, Field(ge=0.01, le=10000, allow_inf_nan=False)] | None = None
    pp: bool = True
    po: bool = True


class SynthesisRow(Strict):
    id: ID
    translation_revision: ZeroRevision
    expected_source_text_fingerprint: Fingerprint
    selection_revision: ZeroRevision
    review_translation_revision: ZeroRevision | None = None
    review_reference_version_id: ID | None = None


class Synthesize(SourceGuard):
    segments: Annotated[list[SynthesisRow], Field(min_length=1, max_length=1000)]
    replace_selected: bool = False
    regenerate: bool = False


class VoiceSettingsPut(SourceGuard):
    revision: ZeroRevision
    controls: Controls | None


class AudioSelectionPut(SourceGuard):
    revision: ZeroRevision
    output_id: ID
    translation_revision: ZeroRevision
    expected_source_text_fingerprint: Fingerprint


class LineOptions(Strict):
    line_id: ID
