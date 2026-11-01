"""Actual PCM envelope fixtures; no inference or invented waveform data."""

import hashlib
import math
import struct
import wave

import pytest

from videotranslate.execution.contracts import CancellationRequested, StageFailure


def pcm(path, frames, channels=1, rate=8000):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(struct.pack("<" + "h" * len(frames), *frames))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_stereo_extrema_rms_and_last_sample_have_exact_bin_clock(tmp_path):
    from videotranslate.media.waveform import envelope

    path = tmp_path / "actual.wav"
    sha = pcm(path, [0, 0, -32768, 32767, 0, 0, 0, 0, 16384, -16384], 2)
    result = envelope(path, expected_sha256=sha, bins=3)
    assert result["sample_count"] == 5 and result["channels"] == 2
    assert result["duration_ms"] == 0.625
    a, b, tail = result["bins"]
    assert [(x["start_sample"], x["end_sample"]) for x in (a, b, tail)] == [(0, 1), (1, 3), (3, 5)]
    assert a["min"] == a["max"] == a["rms"] == 0
    assert b["min"] == -1 and b["max"] == 32767 / 32768
    assert tail["max"] == 0.5 and tail["min"] == -0.5
    assert tail["rms"] == pytest.approx(math.sqrt(0.125))
    assert result["input_sha256"] == sha


def test_peak_after_stream_block_boundary_and_tiny_sample_tail(tmp_path):
    from videotranslate.media.waveform import envelope

    path = tmp_path / "late.wav"
    sha = pcm(path, [0] * 9000 + [30000])
    result = envelope(path, expected_sha256=sha, bins=2000)
    assert len(result["bins"]) == 2000
    assert result["bins"][-1]["max"] == 30000 / 32768
    assert result["bins"][-1]["end_sample"] == 9001
    assert sum(b["end_sample"] - b["start_sample"] for b in result["bins"]) == 9001
    from videotranslate.dubbing.waveforms_contracts import WaveformArtifact

    assert (
        WaveformArtifact.model_validate(
            result | dict(clock="natural_audio_relative", provenance={})
        ).bin_count
        == 2000
    )


@pytest.mark.parametrize("bins", [0, 2001, True, 1.5])
def test_bin_limits_are_strict(tmp_path, bins):
    from videotranslate.media.waveform import envelope

    path = tmp_path / "small.wav"
    sha = pcm(path, [1, 2])
    with pytest.raises(ValueError):
        envelope(path, expected_sha256=sha, bins=bins)


def test_full_bytes_hash_limits_and_cancel(tmp_path):
    from videotranslate.media.waveform import envelope

    path = tmp_path / "small.wav"
    sha = pcm(path, [100] * 9000)
    with pytest.raises(StageFailure):
        envelope(path, expected_sha256="0" * 64)
    with pytest.raises(StageFailure):
        envelope(path, expected_sha256=sha, max_bytes=10)

    def stop():
        raise CancellationRequested()

    with pytest.raises(CancellationRequested):
        envelope(path, expected_sha256=sha, check=stop)


def test_truncated_pcm_unsupported_width_and_timeout_are_rejected(tmp_path):
    from videotranslate.media.waveform import envelope

    path = tmp_path / "bad.wav"
    pcm(path, [1] * 8000)
    data = path.read_bytes()[:-10]
    path.write_bytes(data)
    with pytest.raises(StageFailure):
        envelope(path, expected_sha256=hashlib.sha256(data).hexdigest())
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(1)
        out.setframerate(8000)
        out.writeframes(b"\x80" * 8)
    with pytest.raises(StageFailure):
        envelope(path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    sha = pcm(path, [1] * 8000)
    with pytest.raises(StageFailure):
        envelope(path, expected_sha256=sha, timeout=0)
