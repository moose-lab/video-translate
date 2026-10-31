"""Strict budgets and measured, path-free receipts for local CPU finishing."""

import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .audio import AudioFile


@dataclass(frozen=True)
class RenderLimits:
    max_output_bytes: int
    max_temporary_bytes: int
    max_wall_seconds: int
    max_video_frames: int

    def __post_init__(self):
        for value, bound in zip(
            (
                self.max_output_bytes,
                self.max_temporary_bytes,
                self.max_wall_seconds,
                self.max_video_frames,
            ),
            (128 * 1024**3, 512 * 1024**3, 86400, 3456000),
            strict=True,
        ):
            if type(value) is not int or not 0 < value <= bound:
                raise ValueError("INVALID_RENDER_LIMITS")


@dataclass(frozen=True)
class FinishedAudio(AudioFile):
    sample_count: int = 0
    peak: float = 0.0
    receipt_json: str = "{}"

    def metadata(self):
        return {
            **super().metadata(),
            "sample_count": self.sample_count,
            "peak": self.peak,
            "receipt": json.loads(self.receipt_json),
        }


@dataclass(frozen=True)
class VideoFile:
    path: Path
    sha256: str
    byte_size: int
    duration_ms: int
    codec: str
    container: str
    width: int
    height: int
    frame_rate: Fraction
    frame_count: int
    receipt_json: str

    def metadata(self):
        return {
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "duration_ms": self.duration_ms,
            "codec": self.codec,
            "container": self.container,
            "width": self.width,
            "height": self.height,
            "frame_rate": rational(self.frame_rate),
            "frame_count": self.frame_count,
            "receipt": json.loads(self.receipt_json),
        }


def rational(value):
    value = Fraction(value)
    return [value.numerator, value.denominator]


def receipt(data):
    result = json.dumps(data, allow_nan=False, separators=(",", ":"), sort_keys=True)
    if len(result.encode()) > 65536:
        raise ValueError("RECEIPT_LIMIT")
    return result
