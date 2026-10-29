"""Bounded CPU media preparation. No inference and no network protocols."""

import hashlib
import json
import math
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from ..execution.contracts import FailureCode, StageFailure
from .timing import timeline_bounds

MAX_BYTES = 64 * 1024 * 1024
VIDEO_FORMATS = "mov,matroska,avi"
AUDIO_FORMATS = "wav,mp3,ogg,flac,mov,matroska"


@dataclass(frozen=True)
class AudioFile:
    path: Path
    duration_ms: int
    sample_rate: int
    channels: int
    byte_size: int
    sha256: str

    def metadata(self):
        return {
            k: getattr(self, k)
            for k in ("duration_ms", "sample_rate", "channels", "byte_size", "sha256")
        }


def run_process(args, *, timeout=60, check=lambda: None, output_path=None, max_bytes=MAX_BYTES):
    """Bound stdout, output files and time; always reap the child on stop/failure."""
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(args, stdout=output, stderr=subprocess.DEVNULL)
        except OSError:
            raise StageFailure(FailureCode.CONFIGURATION) from None
        try:
            deadline = time.monotonic() + timeout
            while True:
                check()
                size = output_path.stat().st_size if output_path and output_path.exists() else 0
                if output.tell() > 1024 * 1024 or size > max_bytes or time.monotonic() > deadline:
                    raise StageFailure(FailureCode.MEDIA_LIMIT)
                if process.poll() is not None:
                    break
                time.sleep(0.02)
            if process.returncode:
                raise StageFailure(FailureCode.INVALID_MEDIA)
            output.seek(0)
            return output.read(1024 * 1024)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def inspect(path, formats, *, timeout=60, check=lambda: None):
    raw = run_process(
        [
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            formats,
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        timeout=timeout,
        check=check,
    )
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise StageFailure(FailureCode.INVALID_MEDIA) from None


def validate_audio(
    path,
    *,
    max_bytes=MAX_BYTES,
    max_duration=14400,
    expected_duration_ms=None,
    check=lambda: None,
    timeout=60,
):
    """Inspect AND fully decode an actual audio object before publication."""
    path = Path(path)
    if not 0 < path.stat().st_size <= max_bytes:
        raise StageFailure(FailureCode.MEDIA_LIMIT)
    info = inspect(path, AUDIO_FORMATS, timeout=timeout, check=check)
    try:
        streams = info["streams"]
        if len(streams) != 1 or streams[0]["codec_type"] != "audio":
            raise ValueError()
        stream = streams[0]
        _, duration = timeline_bounds(info)
        channels, rate = int(stream["channels"]), int(stream["sample_rate"])
        if (
            not math.isfinite(duration)
            or not 0 < duration <= max_duration
            or not 1 <= channels <= 8
            or not 8000 <= rate <= 192000
        ):
            raise ValueError()
        duration_ms = round(duration * 1000)
        if expected_duration_ms is not None and abs(duration_ms - expected_duration_ms) > 80:
            raise ValueError()
    except (ValueError, KeyError, TypeError, OverflowError):
        raise StageFailure(FailureCode.INVALID_MEDIA) from None
    run_process(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            AUDIO_FORMATS,
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        timeout=timeout,
        check=check,
    )
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            check()
            digest.update(chunk)
    return AudioFile(path, duration_ms, rate, channels, path.stat().st_size, digest.hexdigest())


def extract_audio(
    source,
    destination,
    *,
    audio_ordinal,
    start_ms,
    end_ms,
    sample_rate=48000,
    channels=2,
    max_bytes=MAX_BYTES,
    timeout=60,
    check=lambda: None,
    audio_only=False,
):
    """Align selected audio to the explicit common demuxer origin and window.

    MP4/MKV offset origins, delayed tracks and MP3 priming have real fixtures.
    Audio ordinals must never be interpreted as absolute stream IDs.
    """
    destination = Path(destination)
    if (
        not isinstance(audio_ordinal, int)
        or isinstance(audio_ordinal, bool)
        or not 0 <= audio_ordinal <= 100
        or not 0 <= start_ms < end_ms
        or sample_rate not in {16000, 48000}
        or channels not in {1, 2}
    ):
        raise StageFailure(FailureCode.INVALID_MEDIA)
    if (end_ms - start_ms) * sample_rate * channels * 2 / 1000 + 4096 > max_bytes:
        raise StageFailure(FailureCode.MEDIA_LIMIT)
    formats = AUDIO_FORMATS if audio_only else VIDEO_FORMATS
    info = inspect(source, formats, timeout=timeout, check=check)
    try:
        origin, logical_duration = timeline_bounds(info)
        videos = [s for s in info["streams"] if s.get("codec_type") == "video"]
        audio = [s for s in info["streams"] if s.get("codec_type") == "audio"]
        if (
            (not audio_only and not videos)
            or audio_ordinal >= len(audio)
            or end_ms > round(logical_duration * 1000) + 80
        ):
            raise ValueError()
    except (KeyError, ValueError, TypeError, OverflowError):
        raise StageFailure(FailureCode.INVALID_MEDIA) from None
    start, end, duration = start_ms / 1000, end_ms / 1000, (end_ms - start_ms) / 1000
    filters = (
        f"aresample={sample_rate}:async=1:first_pts={round(start * sample_rate)},"
        f"atrim=start={start}:end={end},asetpts=PTS-{start}/TB,"
        f"apad=whole_dur={duration},atrim=duration={duration}"
    )
    try:
        run_process(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-format_whitelist",
                formats,
                "-ss",
                str(start),
                "-copyts",
                "-start_at_zero",
                "-i",
                str(source),
                "-map",
                f"0:a:{audio_ordinal}",
                "-vn",
                "-af",
                filters,
                "-ar",
                str(sample_rate),
                "-ac",
                str(channels),
                "-c:a",
                "pcm_s16le",
                str(destination),
            ],
            timeout=timeout,
            check=check,
            output_path=destination,
            max_bytes=max_bytes,
        )
        result = validate_audio(
            destination,
            max_bytes=max_bytes,
            expected_duration_ms=end_ms - start_ms,
            check=check,
            timeout=timeout,
        )
        with wave.open(str(destination)) as pcm:
            if pcm.getsampwidth() != 2 or pcm.getcomptype() != "NONE":
                raise StageFailure(FailureCode.INVALID_MEDIA)
        return result
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
