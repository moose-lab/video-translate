from dataclasses import replace

import pytest
from media_fixtures import float_wav, sha

from videotranslate.execution.contracts import StageFailure
from videotranslate.media.finishing_types import RenderLimits
from videotranslate.media.float_audio import normalize

LIMITS = RenderLimits(8 * 1024**2, 32 * 1024**2, 30, 10000)


def test_float_above_unity_exact_count_and_sha(tmp_path):
    audio = float_wav(tmp_path / "in.wav", 4800, sample=lambda i, c: 1.5 if c == 0 else -0.7)
    result = normalize(audio, tmp_path / "out.raw", limits=LIMITS, check=lambda: None)
    assert result is not None, "normalization must materialize measured float frames"
    assert result.frames == 4800 and result.peak == pytest.approx(1.5)
    assert result.byte_size == 4800 * 8 and result.sha256 == sha(result.path)
    with pytest.raises(StageFailure):
        normalize(
            replace(audio, sha256="0" * 64), tmp_path / "bad.raw", limits=LIMITS, check=lambda: None
        )


def test_mono_duplicates_unity_and_nonfinite_or_mismatched_proof_rejects(tmp_path):
    mono = float_wav(tmp_path / "mono.wav", 480, channels=1, sample=lambda i, c: 0.6)
    result = normalize(mono, tmp_path / "mono.raw", limits=LIMITS, check=lambda: None)
    from array import array

    values = array("f", result.path.read_bytes())
    assert len(values) == 960 and all(abs(v - 0.6) < 1e-6 for v in values)
    bad = float_wav(tmp_path / "nan.wav", 48, sample=lambda i, c: float("nan"))
    with pytest.raises(StageFailure):
        normalize(bad, tmp_path / "nan.raw", limits=LIMITS, check=lambda: None)
    assert not (tmp_path / "nan.raw").exists()


def test_limits_strict_and_cancel_cleanup(tmp_path):
    for bad in (True, 1.5, "12", 10**100, 0, -1):
        with pytest.raises(ValueError):
            RenderLimits(bad, 1024, 1, 1)
    audio = float_wav(tmp_path / "a.wav", 4800)
    with pytest.raises(StageFailure):
        normalize(
            audio,
            tmp_path / "small.raw",
            limits=replace(LIMITS, max_output_bytes=4),
            check=lambda: None,
        )

    def cancel():
        raise RuntimeError("cancel")

    with pytest.raises(RuntimeError, match="cancel"):
        normalize(audio, tmp_path / "cancel.raw", limits=LIMITS, check=cancel)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.wav"]


def test_raw_partial_empty_and_infinite_rejected(tmp_path):
    from array import array

    from videotranslate.media.float_audio import Budget, measure

    budget = Budget(LIMITS, lambda: None, tmp_path)
    for payload in (b"", b"123", array("f", [float("inf"), 0]).tobytes()):
        path = tmp_path / "raw"
        path.write_bytes(payload)
        with pytest.raises(StageFailure):
            measure(path, budget)


def test_corrupt_input_and_unsupported_channels_rejected(tmp_path):
    from videotranslate.media.audio import AudioFile

    path = tmp_path / "bad.wav"
    path.write_bytes(b"not a wave")
    audio = AudioFile(path, 100, 48000, 2, path.stat().st_size, sha(path))
    with pytest.raises(StageFailure):
        normalize(audio, tmp_path / "out.raw", limits=LIMITS, check=lambda: None)
    multi = float_wav(tmp_path / "multi.wav", 48, channels=3)
    with pytest.raises(StageFailure):
        normalize(multi, tmp_path / "multi.raw", limits=LIMITS, check=lambda: None)
