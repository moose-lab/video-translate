"""Bounded waveform requests and immutable sample-grid artifacts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import ID, Fingerprint, SourceGuard, Strict


class WaveformCreate(Strict):
    guard: SourceGuard
    kind: Literal["source", "natural_voice"]
    output_id: ID | None = None
    bins: Annotated[int, Field(ge=1, le=2000)] = 600

    @model_validator(mode="after")
    def scope(self):
        if (self.kind == "natural_voice") != (self.output_id is not None):
            raise ValueError("Voice output required only for natural voice")
        return self


class WaveformOptions(WaveformCreate):
    proof: dict


class ArtifactModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class EnvelopeBin(ArtifactModel):
    start_sample: Annotated[int, Field(ge=0)]
    end_sample: Annotated[int, Field(ge=1)]
    min: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]
    max: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]
    rms: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class WaveformArtifact(ArtifactModel):
    policy: Literal["pcm-envelope-v1"]
    input_sha256: Fingerprint
    sample_rate: Annotated[int, Field(ge=8000, le=192000)]
    channels: Annotated[int, Field(ge=1, le=8)]
    sample_count: Annotated[int, Field(ge=1)]
    duration_ms: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    bin_count: Annotated[int, Field(ge=1, le=2000)]
    bins: Annotated[list[EnvelopeBin], Field(min_length=1, max_length=2000)]
    clock: Literal["source_selection_relative", "natural_audio_relative"]
    provenance: dict

    @model_validator(mode="after")
    def sample_grid(self):
        if self.bin_count != len(self.bins) or self.bin_count > self.sample_count:
            raise ValueError("Invalid waveform grid")
        if self.duration_ms != self.sample_count * 1000 / self.sample_rate:
            raise ValueError("Invalid waveform duration")
        for index, row in enumerate(self.bins):
            if (
                row.start_sample != index * self.sample_count // self.bin_count
                or row.end_sample != (index + 1) * self.sample_count // self.bin_count
                or row.min > row.max
                or row.rms > max(abs(row.min), abs(row.max)) + 1e-12
            ):
                raise ValueError("Invalid measured bin")
        return self
