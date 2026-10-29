"""Bounded CPU-only inspection of private uploaded video."""

import json
import math
import subprocess
import tempfile
import time
from fractions import Fraction
from pathlib import Path

from ..execution.contracts import FailureCode, StageFailure
from .timing import timeline_bounds


def normalize_probe(data, *, max_duration, max_pixels):
    try:
        origin, duration = timeline_bounds(data)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError()
        if duration > max_duration:
            raise StageFailure(FailureCode.MEDIA_LIMIT)
        streams = data["streams"]
        video = next(
            s
            for s in streams
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        )
        width, height = int(video["width"]), int(video["height"])
        if width <= 0 or height <= 0:
            raise ValueError()
        if width * height > max_pixels:
            raise StageFailure(FailureCode.MEDIA_LIMIT)
        rate = float(Fraction(video.get("avg_frame_rate", "0/1")))
        if not math.isfinite(rate) or rate < 0 or rate > 1000:
            raise ValueError()
        audio = []
        for stream in streams:
            if stream.get("codec_type") != "audio":
                continue
            audio.append(
                {
                    "audio_ordinal": len(audio),
                    "stream_index": int(stream["index"]),
                    "language": str(stream.get("tags", {}).get("language", "und"))[:40],
                    "codec": str(stream.get("codec_name", "unknown"))[:80],
                    "channels": int(stream.get("channels", 0)),
                    "sample_rate": int(stream.get("sample_rate", 0)),
                    "default": bool(stream.get("disposition", {}).get("default", 0)),
                }
            )
        return {
            "duration_ms": round(duration * 1000),
            "timeline_origin_ms": round(origin * 1000),
            "video": {
                "codec": str(video.get("codec_name", "unknown"))[:80],
                "width": width,
                "height": height,
                "frame_rate": rate,
            },
            "audio": audio,
        }
    except StageFailure:
        raise
    except (KeyError, TypeError, ValueError, StopIteration, ZeroDivisionError, OverflowError):
        raise StageFailure(FailureCode.INVALID_MEDIA) from None


def probe_source(context):
    asset = context.source_asset()
    settings = context.settings
    if asset.byte_size > settings.probe_max_bytes:
        raise StageFailure(FailureCode.MEDIA_LIMIT)
    with tempfile.TemporaryDirectory(prefix="videotranslate-probe-") as directory:
        path = Path(directory) / "source"
        size = 0
        with context.storage.open(asset.storage_key) as source, path.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                context.check_active()
                size += len(chunk)
                if size > settings.probe_max_bytes:
                    raise StageFailure(FailureCode.MEDIA_LIMIT)
                output.write(chunk)
        with tempfile.TemporaryFile() as output:
            try:
                process = subprocess.Popen(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-protocol_whitelist",
                        "file,pipe",
                        "-format_whitelist",
                        "mov,matroska,avi",
                        "-show_format",
                        "-show_streams",
                        "-of",
                        "json",
                        str(path),
                    ],
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                raise StageFailure(FailureCode.CONFIGURATION) from None
            try:
                deadline = time.monotonic() + settings.probe_timeout_seconds
                while process.poll() is None:
                    context.check_active()
                    if time.monotonic() > deadline or output.tell() > 1024 * 1024:
                        raise StageFailure(FailureCode.MEDIA_LIMIT)
                    time.sleep(0.05)
                if process.returncode or output.tell() > 1024 * 1024:
                    raise StageFailure(FailureCode.INVALID_MEDIA)
                output.seek(0)
                try:
                    data = json.load(output)
                except (ValueError, UnicodeDecodeError):
                    raise StageFailure(FailureCode.INVALID_MEDIA) from None
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        return normalize_probe(
            data,
            max_duration=settings.probe_max_duration_seconds,
            max_pixels=settings.probe_max_pixels,
        )
