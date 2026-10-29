"""Narrow private normalized result contracts, separate from public run facts."""

from typing import Annotated

from pydantic import Field, model_validator

from .contracts import ID, Strict, Text


class RecognizedSegment(Strict):
    start: Annotated[float | int, Field(ge=0, allow_inf_nan=False)]
    end: Annotated[float | int, Field(gt=0, allow_inf_nan=False)]
    text: Text
    speaker: Annotated[str | None, Field(min_length=1, max_length=100)] = None

    @model_validator(mode="after")
    def valid_segment(self):
        if self.end <= self.start or not self.text.strip():
            raise ValueError("Invalid recognized segment")
        return self


class NormalizedTranscript(Strict):
    selection_id: ID
    segments: Annotated[list[RecognizedSegment], Field(min_length=1, max_length=1000)]
    detected_language: Annotated[str | None, Field(max_length=40)] = None
