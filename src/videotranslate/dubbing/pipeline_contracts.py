"""Finite product workflow commands; never arbitrary graph or provider payloads."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import ID, Fingerprint, Revision, Strict
from .fit_contracts import Rate


class DeliveryOptions(Strict):
    frame_rate: Rate = Field(default_factory=lambda: Rate(numerator=25, denominator=1))
    background_gain: Annotated[float, Field(ge=0, le=4, allow_inf_nan=False)] = 1.0
    voice_gain: Annotated[float, Field(ge=0, le=4, allow_inf_nan=False)] = 1.0
    include_original_comparison: bool = True
    default_audio_track: Annotated[str | None, Field(max_length=40)] = None
    captions: Literal["sidecar", "none"] = "sidecar"


class Scope(Strict):
    target_track_ids: Annotated[list[ID], Field(min_length=1, max_length=16)]
    delivery_track_ids: Annotated[list[ID], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def scope_valid(self):
        if (
            len(set(self.target_track_ids)) != len(self.target_track_ids)
            or len(set(self.delivery_track_ids)) != len(self.delivery_track_ids)
            or not set(self.delivery_track_ids) <= set(self.target_track_ids)
        ):
            raise ValueError("Unique finish targets must belong to the workflow scope")
        return self


class PipelineStart(Scope):
    expected_editor_fingerprint: Fingerprint
    source_mode: Literal["automatic", "use_current", "manual_import"] = "use_current"
    auto_advance: bool = False
    purpose: Literal["dub", "incomplete_preview"] = "dub"
    delivery_options: DeliveryOptions = Field(default_factory=DeliveryOptions)


class PipelineCAS(Strict):
    revision: Revision


class PipelineContinue(PipelineCAS):
    kind: Literal["source", "translation", "reconcile"]
    guard: Fingerprint
    track_id: ID | None = None


class PipelinePolicyPut(PipelineCAS):
    auto_advance: bool


class PipelineScopePut(Scope):
    revision: Revision


class ControlOptions(Strict):
    workflow_id: ID
    generation: Revision
    wake_revision: Revision
