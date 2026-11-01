"""Block-streamed 48 kHz stereo f32le; finite headroom is never clipped.

Each operation owns only its TemporaryDirectory. Budgets include every owned
file, check wall time during Python/native subprocess work, and reap on failure.
"""

import hashlib
import json
import math
import stat
import subprocess
import sys
import tempfile
import time
from array import array
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..execution.contracts import FailureCode, StageFailure
from .audio import AUDIO_FORMATS, AudioFile, validate_audio
from .finishing_types import FinishedAudio, RenderLimits, receipt
from .timing import timeline_bounds

RATE = 48000
CHANNELS = 2
FRAME_BYTES = 8
BLOCK = 4096
MAX_FRAMES = 57600 * RATE


def invalid():
    return StageFailure(FailureCode.INVALID_MEDIA)


def limited():
    return StageFailure(FailureCode.MEDIA_LIMIT)


class Budget:
    def __init__(self, limits, check, directory):
        if type(limits) is not RenderLimits:
            raise ValueError("INVALID_RENDER_LIMITS")
        self.limits, self.callback, self.directory = limits, check, Path(directory)
        self.deadline = time.monotonic() + limits.max_wall_seconds
        self.reserved_bytes = 0

    def used_bytes(self):
        total = self.reserved_bytes
        for path in self.directory.iterdir():
            try:
                item = path.stat()
            except FileNotFoundError:
                # The native helper atomically replaces its bounded progress.
                # One stat avoids a check/stat race; a removed name owns no bytes.
                continue
            if stat.S_ISREG(item.st_mode):
                total += item.st_size
        return total

    def check(self):
        self.callback()
        if time.monotonic() > self.deadline or self.used_bytes() > self.limits.max_temporary_bytes:
            raise limited()

    def preflight(self, size, *, output=True):
        self.check()
        if type(size) is not int or size < 1 or size > self.limits.max_temporary_bytes:
            raise limited()
        if output and size > self.limits.max_output_bytes:
            raise limited()
        if self.used_bytes() + size > self.limits.max_temporary_bytes:
            raise limited()

    @contextmanager
    def reserve(self, size):
        """Account bounded allocations owned by reused helpers outside our directory."""
        self.preflight(size, output=False)
        self.reserved_bytes += size
        try:
            yield
        finally:
            self.reserved_bytes -= size

    def run(self, args, *, output=None, capture_diagnostics=False):
        # Temporary stdout is counted too; no pipe deadlock or unbounded communicate().
        log = self.directory / "process.stdout"
        self.check()
        with log.open("wb") as out:
            try:
                p = subprocess.Popen(
                    args, stdout=out, stderr=out if capture_diagnostics else subprocess.DEVNULL
                )
            except OSError:
                raise StageFailure(FailureCode.CONFIGURATION) from None
            try:
                while True:
                    self.check()
                    if log.stat().st_size > 1024 * 1024:
                        raise limited()
                    if (
                        output
                        and output.exists()
                        and output.stat().st_size > (self.limits.max_output_bytes)
                    ):
                        raise limited()
                    if p.poll() is not None:
                        break
                    time.sleep(0.01)
                if p.returncode:
                    raise invalid()
            finally:
                if p.poll() is None:
                    p.kill()
                p.wait()
        data = log.read_bytes()
        log.unlink()
        return data


@dataclass(frozen=True)
class FloatAudio:
    path: Path
    frames: int
    peak: float
    sha256: str
    byte_size: int


def digest(path, check):
    result = hashlib.sha256()
    try:
        with Path(path).open("rb") as source:
            while data := source.read(1024 * 1024):
                check()
                result.update(data)
    except OSError:
        raise invalid() from None
    return result.hexdigest()


def verify_input(audio, budget):
    if not isinstance(audio, AudioFile):
        raise invalid()
    try:
        if audio.path.stat().st_size != audio.byte_size:
            raise invalid()
    except OSError:
        raise invalid() from None
    if digest(audio.path, budget.check) != audio.sha256:
        raise invalid()


def blocks(path, check):
    with Path(path).open("rb") as source:
        while data := source.read(BLOCK * FRAME_BYTES):
            check()
            if len(data) % FRAME_BYTES:
                raise invalid()
            values = array("f")
            values.frombytes(data)
            if sys.byteorder != "little":
                values.byteswap()
            if not all(math.isfinite(v) for v in values):
                raise invalid()
            yield values


def write_block(out, values):
    if sys.byteorder != "little":
        values = array("f", values)
        values.byteswap()
    out.write(values.tobytes())


def measure(path, budget):
    try:
        size = path.stat().st_size
        if not 0 < size <= budget.limits.max_output_bytes or size % FRAME_BYTES:
            raise invalid()
        frames, peak = 0, 0.0
        for data in blocks(path, budget.check):
            frames += len(data) // CHANNELS
            peak = max(peak, max(abs(x) for x in data))
            if frames > MAX_FRAMES:
                raise limited()
        return FloatAudio(path, frames, peak, digest(path, budget.check), size)
    except OSError:
        raise invalid() from None


def _normalize(audio, destination, budget):
    verify_input(audio, budget)
    if audio.channels not in (1, 2):
        raise invalid()
    # Rounding policy for resampling: nearest sample, ties to even; permit one
    # sample decoder rounding only for non-48k input, never infer actual length.
    estimate = (audio.duration_ms * RATE + 999) // 1000
    budget.preflight(estimate * FRAME_BYTES + 8192)
    try:
        info = json.loads(
            budget.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-format_whitelist",
                    AUDIO_FORMATS,
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(audio.path),
                ]
            )
        )
        stream = info["streams"][0]
        _, duration = timeline_bounds(info)
        if (
            round(duration * 1000) != audio.duration_ms
            or int(stream["sample_rate"]) != audio.sample_rate
        ):
            raise ValueError()
    except (ValueError, KeyError, IndexError, TypeError, OverflowError):
        raise invalid() from None
    if (
        len(info["streams"]) != 1
        or stream.get("codec_type") != "audio"
        or stream.get("channels") != audio.channels
        or stream.get("channel_layout", "unknown") not in ("unknown", "mono", "stereo")
    ):
        raise invalid()
    matrix = "pan=stereo|c0=c0|c1=c0" if audio.channels == 1 else "pan=stereo|c0=c0|c1=c1"
    budget.run(
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
            AUDIO_FORMATS,
            "-i",
            str(audio.path),
            "-map",
            "0:a:0",
            "-af",
            matrix,
            "-ar",
            str(RATE),
            "-c:a",
            "pcm_f32le",
            "-f",
            "f32le",
            str(destination),
        ],
        output=destination,
    )
    return measure(destination, budget)


def normalize(audio, destination, *, limits, check):
    destination = Path(destination)
    if destination.exists():
        raise invalid()
    with tempfile.TemporaryDirectory(prefix="vt-float-", dir=destination.parent) as d:
        budget = Budget(limits, check, d)
        result = _normalize(audio, Path(d) / "input.raw", budget)
        publish(result.path, destination)
        return FloatAudio(destination, result.frames, result.peak, result.sha256, result.byte_size)


def finish(raw, destination, budget, facts):
    """Fully decode the final float WAV and compare all raw samples before publish."""
    destination = Path(destination)
    if destination.exists():
        raise invalid()
    measured = measure(raw, budget)
    budget.preflight(measured.byte_size + 4096)
    wav = budget.directory / "finished.wav"
    budget.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-y",
            "-f",
            "f32le",
            "-ar",
            str(RATE),
            "-ac",
            "2",
            "-i",
            str(raw),
            "-c:a",
            "pcm_f32le",
            "-rf64",
            "auto",
            str(wav),
        ],
        output=wav,
    )
    # Legacy inspect/decode supervise one TemporaryFile stdout at a time, capped
    # at 1 MiB. Reserve its full bound, including while callbacks check our files.
    # Keep legacy defaults and its public validation contract unchanged.
    with budget.reserve(1024 * 1024):
        validated = validate_audio(
            wav,
            max_bytes=budget.limits.max_output_bytes,
            max_duration=57600,
            timeout=budget.limits.max_wall_seconds,
            check=budget.check,
        )
    decoded = budget.directory / "verified.raw"
    budget.preflight(measured.byte_size)
    budget.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-y",
            "-i",
            str(wav),
            "-map",
            "0:a:0",
            "-c:a",
            "pcm_f32le",
            "-f",
            "f32le",
            str(decoded),
        ],
        output=decoded,
    )
    proof = measure(decoded, budget)
    if proof.sha256 != measured.sha256:
        raise invalid()
    facts = {
        **facts,
        "sample_rate": RATE,
        "channels": 2,
        "actual_samples": proof.frames,
        "peak": proof.peak,
        "padding_samples": 0,
        "rounding": "nearest-ties-even-v1",
    }
    result = FinishedAudio(
        destination,
        validated.duration_ms,
        RATE,
        2,
        validated.byte_size,
        validated.sha256,
        validated.codec,
        validated.container,
        proof.frames,
        proof.peak,
        receipt(facts),
    )
    budget.check()
    publish(wav, destination)
    return result


def publish(owned, destination):
    """Exclusive same-filesystem publication; remove only the owned temp name."""
    try:
        destination.hardlink_to(owned)
    except OSError:
        raise invalid() from None
    owned.unlink()
