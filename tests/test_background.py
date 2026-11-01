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


def test_target_preview_beds_comparison_and_video_share_exact_map_with_real_markers(tmp_path):
    """Required composition: own source masks, borrowed/excluded spans, same exact map."""
    import math
    from fractions import Fraction as F

    from test_fit_video import assert_frame_grid, video

    from videotranslate.media.fit_audio import fit_voice, retime_audio
    from videotranslate.media.fit_plan import build_plan, map_time
    from videotranslate.media.fit_types import FitLine, FitSettings
    from videotranslate.media.fit_video import retime_video

    marks = [
        (0.01, 0.15, 400),
        (0.85, 0.99, 600),
        (1.03, 1.09, 1400),
        (1.85, 1.99, 800),
        (2.03, 2.09, 2800),
        (2.85, 2.99, 1000),
        (3.85, 3.99, 1200),
    ]

    def waveform(instrumental):
        def sample(i, c):
            t = i / RATE
            for a, b, hz in marks:
                if a <= t < b:
                    return 1.2 * math.sin(
                        2 * math.pi * (hz + (6000 if instrumental else 0) + c * 50) * t
                    )
            return 0.0

        return sample

    working = float_wav(tmp_path / "working.wav", 4 * RATE, sample=waveform(False))
    instrumental = float_wav(tmp_path / "instrumental.wav", 4 * RATE, sample=waveform(True))
    lines = [
        FitLine("zh", "included", "r", 800, 1000, 600),
        FitLine("ja", "included", "s", 1800, 2000, 600),
    ]
    plan = build_plan(
        4000, lines, FitSettings(mode="smart", max_audio_speed=F(1), max_borrow_ms=100)
    )
    assert plan.feasible and plan.output_duration_ms == 4600
    assert [p.available_source_end_ms for p in plan.placements] == [1100, 2100]
    # Natural files are independent immutable inputs, not overwritten by derived fitting.
    naturals = [
        float_wav(
            tmp_path / f"natural-{key}.wav",
            28800,
            sample=lambda i, c: 0.5 * math.sin(2 * math.pi * 350 * i / RATE),
        )
        for key in ("zh", "ja")
    ]
    for key, natural in zip(("zh", "ja"), naturals, strict=True):
        assert (
            fit_voice(
                natural,
                tmp_path / f"fitted-{key}.wav",
                speed=F(1),
                limits=LIMITS,
                check=lambda: None,
            ).sample_count
            == 28800
        )
    comparison = retime_audio(
        working, plan, tmp_path / "comparison.wav", limits=LIMITS, check=lambda: None
    )
    original_samples = samples(comparison, tmp_path)

    bands = [hz for _, _, hz in marks] + [hz + 6000 for _, _, hz in marks]
    kernels = {
        hz: [
            complex(math.cos(2 * math.pi * hz * i / RATE), math.sin(2 * math.pi * hz * i / RATE))
            for i in range(480)
        ]
        for hz in bands
    }

    def identified_bounds(data):
        # Identify the dominant known tone, rather than treating a sidelobe from
        # a different burst as the missing/shifted marker. Timing stays <=60ms.
        active = {hz: [] for hz in bands}
        for offset in range(0, len(data) // 2 - 480, 480):
            window = data[offset * 2 : (offset + 480) * 2 : 2]
            energy = {
                hz: abs(sum(v * k for v, k in zip(window, kernel, strict=True))) / 480
                for hz, kernel in kernels.items()
            }
            winner = max(energy, key=energy.get)
            if energy[winner] > 0.03:
                active[winner].append(offset // 480)
        return {
            hz: (values[0] / 100, (values[-1] + 1) / 100) for hz, values in active.items() if values
        }

    def assert_marker(bounds, a, b, hz):
        assert hz in bounds, f"lost {hz}Hz marker"
        actual = bounds[hz]
        expected = [float(map_time(plan, round(t * 1000)) / 1000) for t in (a, b)]
        assert max(abs(x - y) for x, y in zip(actual, expected, strict=True)) <= 0.060, (
            hz,
            actual,
            expected,
        )

    original_bounds = identified_bounds(original_samples)
    for a, b, hz in marks:
        assert_marker(original_bounds, a, b, hz)
    for key, included, replaced in (("zh", ((800, 1000),), 600), ("ja", ((1800, 2000),), 800)):
        bed = build_background(
            working,
            instrumental,
            tmp_path / f"bed-{key}.wav",
            source_duration_ms=4000,
            dialogue_intervals=included,
            crossfade_ms=0,
            limits=LIMITS,
            check=lambda: None,
        )
        assert json.loads(bed.receipt_json)["dialogue_union_ms"] == [
            list(pair) for pair in included
        ]
        retimed = retime_audio(
            bed, plan, tmp_path / f"retimed-{key}.wav", limits=LIMITS, check=lambda: None
        )
        assert retimed.sample_count == comparison.sample_count == 220800
        data = samples(retimed, tmp_path)
        bounds = identified_bounds(data)
        for a, b, hz in marks:
            assert_marker(bounds, a, b, hz + 6000 if hz == replaced else hz)
        # Each target keeps the other target's original row, its own borrowed
        # tail (1400/2800Hz), and excluded2.85s row(1000Hz); no foreign bed appears.
        assert replaced not in bounds
        assert not (set(bands[7:]) - {replaced + 6000}).intersection(bounds)
        assert json.loads(retimed.receipt_json)["planned_duration_ms"] == [4600, 1]
    source = tmp_path / "source.mp4"
    video(source)
    picture = retime_video(
        source,
        tmp_path / "video.mp4",
        source_sha256=sha(source),
        absolute_start_ms=0,
        absolute_end_ms=4000,
        plan=plan,
        frame_rate=F(30),
        limits=LIMITS,
        check=lambda: None,
    )
    frames = assert_frame_grid(picture, source, plan)
    assert len(frames) == 138 and frames[-1] == 119
    assert json.loads(picture.receipt_json)["planned_duration_ms"] == [4600, 1]
    for immutable in (working, instrumental, *naturals):
        assert sha(immutable.path) == immutable.sha256
