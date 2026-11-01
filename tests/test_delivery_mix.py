"""Real FLOAT summing with overlap, explicit gain and visible overrun errors."""

from fractions import Fraction

import pytest
from media_fixtures import RATE, float_wav
from test_float_audio import LIMITS
from test_offline_warp import samples


def test_overlap_sum_has_one_explicit_uniform_peak_protection(tmp_path):
    from videotranslate.media.delivery_mix import mix

    bed = float_wav(tmp_path / "bed.wav", RATE * 2, sample=lambda i, c: 0.4)
    a = float_wav(tmp_path / "a.wav", RATE, sample=lambda i, c: 0.8)
    b = float_wav(tmp_path / "b.wav", RATE, sample=lambda i, c: 0.6)
    result = mix(
        bed,
        [(a, Fraction(0), Fraction(1000)), (b, Fraction(500), Fraction(1500))],
        tmp_path / "mixed.wav",
        background_gain=1.0,
        voice_gain=1.0,
        limits=LIMITS,
        check=lambda: None,
    )
    values = samples(result, tmp_path)
    import json

    receipt = json.loads(result.receipt_json)
    assert receipt["unprotected_peak"] == pytest.approx(1.8, abs=1e-6)
    assert receipt["applied_uniform_gain"] == pytest.approx(0.98 / 1.8, abs=1e-6)
    assert receipt["protected_peak"] <= 0.980001
    assert values[750 * 48 * 2] == pytest.approx(0.98, abs=1e-6)
    assert values[1750 * 48 * 2] == pytest.approx(0.4 * 0.98 / 1.8, abs=1e-6)
    assert result.sample_count == 2 * RATE


def test_mix_rejects_actual_voice_beyond_declared_placement(tmp_path):
    from videotranslate.execution.contracts import StageFailure
    from videotranslate.media.delivery_mix import mix

    bed = float_wav(tmp_path / "bed.wav", RATE * 2, sample=lambda i, c: 0.1)
    voice = float_wav(tmp_path / "voice.wav", RATE, sample=lambda i, c: 0.2)
    with pytest.raises(StageFailure):
        mix(
            bed,
            [(voice, Fraction(0), Fraction(900))],
            tmp_path / "out.wav",
            background_gain=1.0,
            voice_gain=1.0,
            limits=LIMITS,
            check=lambda: None,
        )


def test_mp3_is_real_gapless_stereo_audio_and_fully_decoded(tmp_path):
    from videotranslate.media.delivery_export import mp3
    from videotranslate.media.float_audio import Budget

    audio = float_wav(tmp_path / "source.wav", RATE, sample=lambda i, c: 0.2)
    budget = Budget(LIMITS, lambda: None, tmp_path)
    result = mp3(audio.path, tmp_path / "delivery.mp3", budget=budget)
    assert result.metadata()["codec"] == "mp3"
    assert result.metadata()["actual_decoded_samples"] == RATE
    assert result.metadata()["sample_rate"] == 48000 and result.metadata()["channels"] == 2


def test_real_48010_frame_voice_preserves_millisecond_quantization_tail(tmp_path):
    from videotranslate.media.delivery_mix import mix

    audio = float_wav(tmp_path / "natural.wav", 48010, sample=lambda i, c: 0.2)
    assert audio.duration_ms == 1000
    bed = float_wav(tmp_path / "bed.wav", 96000, sample=lambda i, c: 0.0)
    result = mix(
        bed,
        [(audio, Fraction(0), Fraction(1000))],
        tmp_path / "out.wav",
        background_gain=1.0,
        voice_gain=1.0,
        limits=LIMITS,
        check=lambda: None,
    )
    import json

    receipt = json.loads(result.receipt_json)
    assert receipt["max_declared_end_overrun_samples"] == 10
    actual = samples(result, tmp_path)
    assert actual[48009 * 2] > 0.19 and actual[48010 * 2] == 0.0
