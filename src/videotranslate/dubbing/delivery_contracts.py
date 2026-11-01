"""Explicit, strict bounded delivery choices; paths and asset identities are server derived."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import ID, Strict
from .fit_contracts import Rate


class DeliveryCreate(Strict):
    fit_plan_id: ID
    expected_fit_run_id: ID
    purpose: Literal["dub", "incomplete_preview", "original_only"]
    frame_rate: Rate
    background_gain: Annotated[float, Field(ge=0, le=4, allow_inf_nan=False)]
    voice_gain: Annotated[float, Field(ge=0, le=4, allow_inf_nan=False)]
    include_original_comparison: bool
    default_audio_track: Annotated[str, Field(min_length=2, max_length=40)]
    captions: Literal["sidecar", "none"]

    @model_validator(mode="after")
    def choices(self):
        from ..media.fit_video import FRAME_RATES

        if self.frame_rate.fraction() not in FRAME_RATES:
            raise ValueError("Unsupported exact CFR")
        if self.purpose == "original_only" and (
            not self.include_original_comparison or self.default_audio_track != "original"
        ):
            raise ValueError("Original only requires its original comparison track")
        return self
