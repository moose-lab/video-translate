"""Strict finite bounded manual editing inputs. No model-generation claims."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..languages.catalog import resolve

ID = Annotated[str, Field(min_length=1, max_length=36)]
Revision = Annotated[int, Field(ge=1, le=2**31 - 1)]
Millis = Annotated[int, Field(ge=0, le=2**31 - 1)]
Text = Annotated[str, Field(min_length=1, max_length=10000)]
Fingerprint = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def valid_strings(cls, value):
        pending = [(value, 0)]
        visited = 0
        while pending:
            item, depth = pending.pop()
            visited += 1
            if visited > 20000 or depth > 20:
                raise ValueError("Editing structure limit")
            if isinstance(item, str):
                try:
                    item.encode("utf-8")
                except UnicodeError:
                    raise ValueError("Invalid Unicode") from None
                if any(ord(char) < 32 and char not in "\n\t\r" for char in item):
                    raise ValueError("Invalid control character")
            elif isinstance(item, dict):
                if len(item) > 2000:
                    raise ValueError("Editing structure limit")
                pending.extend((child, depth + 1) for pair in item.items() for child in pair)
            elif isinstance(item, (list, tuple)):
                if len(item) > 2000:
                    raise ValueError("Editing structure limit")
                pending.extend((child, depth + 1) for child in item)
        return value


class SelectionPut(Strict):
    revision: Revision
    source_asset_id: ID
    audio_ordinal: Annotated[int, Field(ge=0, le=100)]
    start_ms: Millis = 0
    end_ms: Millis | None = None


class SourceGuard(Strict):
    selection_revision: Revision
    transcript_revision: ID | None


class SegmentFields(Strict):
    text: Text
    start_ms: Millis
    end_ms: Millis
    speaker_id: ID | None = None

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Text required")
        return value


class SegmentCreate(SourceGuard, SegmentFields):
    pass


class SegmentPatch(SourceGuard):
    revision: Revision
    text: Text | None = None
    start_ms: Millis | None = None
    end_ms: Millis | None = None
    speaker_id: ID | None = None

    @model_validator(mode="after")
    def changed_fields(self):
        for key in ("text", "start_ms", "end_ms"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError("Null edit")
        if self.text is not None and not self.text.strip():
            raise ValueError("Text required")
        return self


class SplitPart(SegmentFields):
    speaker_id: ID | None


class SegmentSplit(SourceGuard):
    revision: Revision
    parts: Annotated[list[SplitPart], Field(min_length=2, max_length=20)]


class RowRevision(Strict):
    id: ID
    revision: Revision


class SegmentMerge(SourceGuard, SegmentFields):
    speaker_id: ID | None
    segments: Annotated[list[RowRevision], Field(min_length=2, max_length=20)]


class SpeakerCreate(Strict):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(max_length=1000)] = ""

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Name required")
        return value


class SpeakerPatch(Strict):
    revision: Revision
    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    description: Annotated[str, Field(max_length=1000)] | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def nonnull(self):
        if any(getattr(self, x) is None for x in self.model_fields_set):
            raise ValueError("Null edit")
        if self.name is not None and not self.name.strip():
            raise ValueError("Name required")
        return self


class SpeakerMerge(SourceGuard):
    source_id: ID
    source_revision: Revision
    target_id: ID
    target_revision: Revision


class ContextFields(Strict):
    summary: Annotated[str, Field(max_length=20000)] = ""
    glossary: Annotated[dict[str, str], Field(max_length=200)] = Field(default_factory=dict)

    @field_validator("glossary", mode="before")
    @classmethod
    def glossary_types(cls, value):
        # Reject entry types at the fixed field location, before Pydantic can put
        # a private dictionary term in an entry-level validation location.
        if not isinstance(value, dict) or any(
            not isinstance(key, str) or not isinstance(term, str) for key, term in value.items()
        ):
            raise ValueError("Glossary must contain text entries")
        return value

    @field_validator("glossary")
    @classmethod
    def bounded_terms(cls, value):
        if any(
            "\x00" in k
            or "\x00" in v
            or not k.strip()
            or not v.strip()
            or len(k) > 200
            or len(v) > 500
            for k, v in value.items()
        ):
            raise ValueError("Invalid glossary")
        if sum(len(k) + len(v) for k, v in value.items()) > 20000:
            raise ValueError("Glossary limit")
        return value


class TrackCreate(ContextFields):
    tag: Annotated[str, Field(min_length=2, max_length=40)]
    mode: Literal["Fast", "Cinematic", "Autofit"] = "Fast"

    @field_validator("tag")
    @classmethod
    def target(cls, value):
        tag = resolve(value)["tag"]
        if tag == "auto":
            raise ValueError("Explicit target required")
        return tag


class TrackPatch(ContextFields):
    revision: Revision
    mode: Literal["Fast", "Cinematic", "Autofit"] | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def nonnull(self):
        if any(getattr(self, x) is None for x in self.model_fields_set):
            raise ValueError("Null edit")
        return self


class TranslationPatch(SourceGuard):
    revision: Annotated[int, Field(ge=0, le=2**31 - 1)]
    expected_source_text_fingerprint: Fingerprint
    text: Text
    locked: bool | None = None
    approved: bool = False

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Text required")
        return value


class ApprovalRow(RowRevision):
    expected_source_text_fingerprint: Fingerprint


class Approve(SourceGuard):
    segments: Annotated[list[ApprovalRow], Field(min_length=1, max_length=200)]


class CueMapping(Strict):
    cue_id: Annotated[str, Field(min_length=1, max_length=64)]
    segment_id: ID | None = None
    revision: Annotated[int, Field(ge=0, le=2**31 - 1)] = 0
    speaker_id: ID | None = None
    use_voice_label: bool = False


class ImportPreview(SourceGuard):
    format: Literal["srt", "vtt", "numbered"]
    content: Annotated[str, Field(min_length=1, max_length=262144)]


class ImportApply(ImportPreview):
    digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    mapping: Annotated[list[CueMapping], Field(min_length=1, max_length=1000)]
    mode: Literal["new_transcript", "replace_current"] = "new_transcript"
    force_locked: bool = False
