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


def test_corrupted_duration_proof_rejects_before_resampling(tmp_path):
    audio = float_wav(tmp_path / "a.wav", 4800)
    with pytest.raises(StageFailure):
        normalize(
            replace(audio, duration_ms=1), tmp_path / "bad.raw", limits=LIMITS, check=lambda: None
        )


def test_aggregate_temporary_deadline_and_exclusive_publication(tmp_path):
    import time
    from dataclasses import replace

    from videotranslate.media.float_audio import Budget, publish

    budget = Budget(replace(LIMITS, max_temporary_bytes=100), lambda: None, tmp_path)
    (tmp_path / "first").write_bytes(b"x" * 60)
    with pytest.raises(StageFailure):
        budget.preflight(50)
    budget.deadline = time.monotonic() - 1
    with pytest.raises(StageFailure):
        budget.check()
    owned, other = tmp_path / "owned", tmp_path / "other"
    owned.write_bytes(b"mine")
    other.write_bytes(b"theirs")
    with pytest.raises(StageFailure):
        publish(owned, other)
    assert other.read_bytes() == b"theirs" and owned.read_bytes() == b"mine"


@pytest.mark.parametrize(
    "field", ["max_output_bytes", "max_temporary_bytes", "max_wall_seconds", "max_video_frames"]
)
@pytest.mark.parametrize("value", [True, 1.1, "1", 0, -1, 10**100])
def test_every_limit_field_uses_strict_bounded_integer(field, value):
    from dataclasses import asdict

    config = asdict(LIMITS)
    config[field] = value
    with pytest.raises(ValueError):
        RenderLimits(**config)


def test_real_supervised_process_timeout_is_killed_and_reaped(tmp_path, monkeypatch):
    import subprocess
    import sys
    import time

    from videotranslate.media.float_audio import Budget

    original = subprocess.Popen
    children = []

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", capture)
    budget = Budget(LIMITS, lambda: None, tmp_path)
    budget.deadline = time.monotonic() + 0.03
    with pytest.raises(StageFailure):
        budget.run([sys.executable, "-c", "import time;time.sleep(3)"])
    assert len(children) == 1 and children[0].poll() is not None
