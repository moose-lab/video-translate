import json

import pytest
from media_fixtures import RATE, float_wav, sha
from test_float_audio import LIMITS
from test_offline_warp import samples

from videotranslate.execution.contracts import StageFailure
from videotranslate.media.background import build_background


def test_overlapping_dialogue_union_has_no_notch_or_double_replacement(tmp_path):
    working = float_wav(tmp_path / "working.wav", 5 * RATE, sample=lambda i, c: 1.4)
    bed = float_wav(tmp_path / "bed.wav", 5 * RATE, sample=lambda i, c: -0.8)
    result = build_background(
        working,
        bed,
        tmp_path / "out.wav",
        source_duration_ms=5000,
        dialogue_intervals=((1000, 3000), (2000, 4000)),
        crossfade_ms=100,
        limits=LIMITS,
        check=lambda: None,
    )
    assert result is not None, "actual source-preserving bed is required"
    values = samples(result, tmp_path)
    for ms in (500, 4500):
        assert values[ms * 48 * 2] == pytest.approx(1.4)
    for ms in (1100, 1500, 2000, 2500, 3000, 3500, 3900):
        assert values[ms * 48 * 2] == pytest.approx(-0.8)
    assert values[1050 * 48 * 2] == pytest.approx(0.3)
    assert result.sample_count == 240000 and result.peak == pytest.approx(1.4)
    assert sha(working.path) == working.sha256 and sha(bed.path) == bed.sha256
    assert json.loads(result.receipt_json)["dialogue_union_ms"] == [[1000, 4000]]


def test_target_included_spans_only_and_empty_working_bed(tmp_path):
    working = float_wav(tmp_path / "working.wav", RATE, sample=lambda i, c: 0.7)
    bed = float_wav(tmp_path / "bed.wav", RATE, sample=lambda i, c: -0.5)
    for target, intervals in (("zh", ((100, 200),)), ("ja", ((600, 700),)), ("empty", ())):
        result = build_background(
            working,
            bed,
            tmp_path / f"{target}.wav",
            source_duration_ms=1000,
            dialogue_intervals=intervals,
            crossfade_ms=0,
            limits=LIMITS,
            check=lambda: None,
        )
        assert result is not None
        values = samples(result, tmp_path)
        assert values[150 * 48 * 2] == pytest.approx(-0.5 if target == "zh" else 0.7)
        assert values[650 * 48 * 2] == pytest.approx(-0.5 if target == "ja" else 0.7)


def test_background_rejects_short_or_mismatched_inputs_and_crossfade(tmp_path):
    working = float_wav(tmp_path / "working.wav", RATE)
    bed = float_wav(tmp_path / "bed.wav", RATE // 2)
    with pytest.raises(StageFailure):
        build_background(
            working,
            bed,
            tmp_path / "out.wav",
            source_duration_ms=1000,
            dialogue_intervals=((100, 200),),
            crossfade_ms=0,
            limits=LIMITS,
            check=lambda: None,
        )


def test_crossfade_constraints_and_hash_mismatch(tmp_path):
    from dataclasses import replace

    working = float_wav(tmp_path / "a.wav", RATE)
    for fade in (True, -1, 101, 51):
        with pytest.raises(StageFailure):
            build_background(
                working,
                working,
                tmp_path / "out.wav",
                source_duration_ms=1000,
                dialogue_intervals=((100, 200),),
                crossfade_ms=fade,
                limits=LIMITS,
                check=lambda: None,
            )
    with pytest.raises(StageFailure):
        build_background(
            working,
            replace(working, sha256="0" * 64),
            tmp_path / "out.wav",
            source_duration_ms=1000,
            dialogue_intervals=(),
            crossfade_ms=0,
            limits=LIMITS,
            check=lambda: None,
        )
