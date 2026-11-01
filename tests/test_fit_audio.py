from fractions import Fraction as F

from media_fixtures import golden_plan, marked, sha
from test_float_audio import LIMITS
from test_offline_warp import marker_bounds, samples

from videotranslate.media.fit_audio import fit_voice, retime_audio


def test_fitted_125_voice_is_two_seconds_keeps_tail_and_source(tmp_path):
    audio, marks = marked(tmp_path / "natural.wav", seconds=2.5)
    before = sha(audio.path)
    result = fit_voice(
        audio, tmp_path / "fit.wav", speed=F(5, 4), limits=LIMITS, check=lambda: None
    )
    assert result is not None, "voice fitting must materialize derived PCM"
    assert result.sample_count == 96000 and result.duration_ms == 2000
    actual = marker_bounds(samples(result, tmp_path), 1200)
    assert max(abs(x - y / 1.25) for x, y in zip(actual, marks[-1][:2], strict=True)) <= 0.06
    assert sha(audio.path) == before == audio.sha256
    identity = fit_voice(
        audio, tmp_path / "normal.wav", speed=F(1), limits=LIMITS, check=lambda: None
    )
    assert identity.sample_count == 120000


def test_comparison_audio_uses_exact_shared_plan(tmp_path):
    audio, _ = marked(tmp_path / "comparison.wav")
    result = retime_audio(
        audio, golden_plan(), tmp_path / "retimed.wav", limits=LIMITS, check=lambda: None
    )
    assert result is not None, "common-map audio retiming is required"
    assert result.sample_count == 312000


def test_invalid_speed_infeasible_plan_and_window_mismatch(tmp_path):
    import pytest

    from videotranslate.execution.contracts import StageFailure
    from videotranslate.media.fit_plan import build_plan
    from videotranslate.media.fit_types import FitLine

    audio, _ = marked(tmp_path / "natural.wav", seconds=2.5)
    for speed in (True, 1, 1.25, F(99, 100), F(201, 100)):
        with pytest.raises(StageFailure):
            fit_voice(audio, tmp_path / "bad.wav", speed=speed, limits=LIMITS, check=lambda: None)
    with pytest.raises(StageFailure):
        retime_audio(
            audio, golden_plan(), tmp_path / "mismatch.wav", limits=LIMITS, check=lambda: None
        )
    infeasible = build_plan(2500, [FitLine("zh", "a", "r", 0, 100, 1000)])
    with pytest.raises(StageFailure):
        retime_audio(
            audio, infeasible, tmp_path / "infeasible.wav", limits=LIMITS, check=lambda: None
        )


def test_native_warp_child_uses_frozen_module_file_without_pythonpath(tmp_path, monkeypatch):
    """Hosted controllers may import an archive without installing it in the venv."""
    audio, _ = marked(tmp_path / "natural.wav", seconds=1)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    result = fit_voice(
        audio, tmp_path / "fit.wav", speed=F(5, 4), limits=LIMITS, check=lambda: None
    )
    assert result.sample_count == 38400
