"""Explicit, strict bounded delivery choices; paths and asset identities are server derived."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import ID, Strict
from .fit_contracts import Rate


class CaptionOptions(Strict):
    formats: Annotated[list[Literal["srt", "vtt", "ass"]], Field(max_length=3)] = Field(
        default_factory=lambda: ["srt", "vtt"]
    )
    burn_in: bool = False
    track: Literal["source", "target", "bilingual"] = "source"
    target_track: Annotated[
        str | None, Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9-]+$")
    ] = None
    font_profile: Literal["auto", "sans", "cjk", "arabic", "hebrew"] = "auto"
    font_size: Annotated[int, Field(ge=12, le=96)] = 42
    style: Literal["outlined"] = "outlined"
    layout_policy: Literal["unicode_wrap_v2"] = "unicode_wrap_v2"

    @model_validator(mode="after")
    def selected(self):
        if len(set(self.formats)) != len(self.formats) or not (self.formats or self.burn_in):
            raise ValueError("Choose unique sidecar formats or burn-in")
        if (self.track == "source") != (self.target_track is None):
            raise ValueError("Target and bilingual captions require a selected target tag")
        return self


class DeliveryCreate(Strict):
    fit_plan_id: ID
    expected_fit_run_id: ID
    purpose: Literal["dub", "incomplete_preview", "original_only"]
    frame_rate: Rate
    background_gain: Annotated[float, Field(ge=0, le=4, allow_inf_nan=False)]
    voice_gain: Annotated[float, Field(ge=0, le=4, allow_inf_nan=False)]
    include_original_comparison: bool
    default_audio_track: Annotated[str, Field(min_length=2, max_length=40)]
    caption_options: CaptionOptions | None = None
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
