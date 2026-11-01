import json
import math
from array import array
from fractions import Fraction as F
from pathlib import Path

import pytest
from media_fixtures import RATE, golden_plan, marked
from test_float_audio import LIMITS

from videotranslate.media.fit_plan import map_time
from videotranslate.media.float_audio import normalize
from videotranslate.media.offline_warp import warp


def samples(audio, tmp_path):
    return array(
        "f",
        normalize(
            audio, tmp_path / (audio.path.stem + "-decode.raw"), limits=LIMITS, check=lambda: None
        ).path.read_bytes(),
    )


def marker_bounds(data, hz, channel=0):
    energies = []
    n = 480
    for start in range(0, len(data) // 2 - n, n):
        re = sum(
            data[(start + i) * 2 + channel] * math.cos(2 * math.pi * hz * i / RATE)
            for i in range(n)
        )
        im = sum(
            data[(start + i) * 2 + channel] * math.sin(2 * math.pi * hz * i / RATE)
            for i in range(n)
        )
        energies.append((re * re + im * im) ** 0.5 / n)
    threshold = max(energies) * 0.3
    active = [i for i, e in enumerate(energies) if e > max(0.03, threshold)]
    assert active, f"lost {hz}Hz marker"
    return active[0] / 100, (active[-1] + 1) / 100


def test_real_offline_golden_map_preserves_all_markers_and_headroom(tmp_path):
    audio, marks = marked(tmp_path / "in.wav")
    plan = golden_plan()
    knots = [(F(p.source_start_ms * 48), p.output_start_ms * 48) for p in plan.pieces]
    knots.append((F(192000), F(312000)))
    result = warp(
        audio, tmp_path / "out.wav", knots=tuple(knots), limits=LIMITS, check=lambda: None
    )
    assert result is not None, "actual offline DSP output is required"
    assert result.sample_count == 312000 and result.peak > 1
    data = samples(result, tmp_path)
    for a, b, hz in marks:
        actual = marker_bounds(data, hz)
        expected = [float(map_time(plan, round(t * 1000)) / 1000) for t in (a, b)]
        assert max(abs(x - y) for x, y in zip(actual, expected, strict=True)) <= 0.060
    facts = json.loads(result.receipt_json)
    assert facts["engine"] == 3 and facts["pitch_scale"] == 1


@pytest.mark.parametrize("ratio", [F(1), F(1, 2), F(4)])
def test_constant_ratio_pitch_tail_and_stereo_channels(tmp_path, ratio):
    audio, marks = marked(tmp_path / "voice.wav", seconds=2.5)
    n = F(120000)
    result = warp(
        audio,
        tmp_path / "out.wav",
        knots=((F(0), F(0)), (n, n * ratio)),
        limits=LIMITS,
        check=lambda: None,
    )
    assert result.sample_count == round(n * ratio)
    data = samples(result, tmp_path)
    # Distinct channel frequencies test pitch and prevent an accidental downmix.
    for c in (0, 1):
        a, b = marker_bounds(data, 1200 + c * 100, c)
        assert (
            max(
                abs(a - float(F(str(marks[-1][0])) * ratio)),
                abs(b - float(F(str(marks[-1][1])) * ratio)),
            )
            <= 0.06
        )
    assert data[100:1000:2] != data[101:1001:2]


def test_real_dense_3001_piece_plan_with_nonuniform_gaps(tmp_path):
    from videotranslate.media.fit_plan import build_plan
    from videotranslate.media.fit_types import FitLine, FitSettings

    # Each row contributes start/end/borrow-end, yielding all 3001 genuine pieces.
    starts = [1]
    for i in range(999):
        starts.append(starts[-1] + 3 + i % 2)
    lines = [FitLine("zh", str(i), str(i), start, start + 1, 4) for i, start in enumerate(starts)]
    plan = build_plan(4000, lines, FitSettings(mode="smart", max_audio_speed=F(1), max_borrow_ms=1))
    assert len(plan.pieces) == 3001
    knots = tuple((F(p.source_start_ms * 48), p.output_start_ms * 48) for p in plan.pieces)
    knots += ((F(192000), plan.output_duration_ms * 48),)
    audio, marks = marked(tmp_path / "dense.wav")
    result = warp(audio, tmp_path / "out.wav", knots=knots, limits=LIMITS, check=lambda: None)
    assert result.sample_count == plan.output_duration_ms * 48
    facts = json.loads(result.receipt_json)
    assert facts["interior_controls"] < 20
    assert F(*facts["rounded_control_error_samples"]) <= 240
    data = samples(result, tmp_path)
    for a, b, hz in marks:
        actual = marker_bounds(data, hz)
        expected = [float(map_time(plan, round(t * 1000)) / 1000) for t in (a, b)]
        assert max(abs(x - y) for x, y in zip(actual, expected, strict=True)) <= 0.06


def test_naive_dynamic_tempo_fails_same_tail_position_criterion(tmp_path):
    from videotranslate.media.audio import run_process, validate_audio

    audio, _ = marked(tmp_path / "negative.wav")
    schedule = tmp_path / "schedule.txt"
    schedule.write_text(
        "0.0 atempo@warp tempo 0.6666666666666666;\n"
        "1.0 atempo@warp tempo 0.5;\n3.0 atempo@warp tempo 1.0;\n"
    )
    out = tmp_path / "negative-out.wav"
    run_process(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(audio.path),
            "-af",
            f"asetnsamples=n=48:p=0,asendcmd=f={schedule},atempo@warp=0.6666666666666666",
            "-c:a",
            "pcm_f32le",
            str(out),
        ]
    )
    actual = marker_bounds(samples(validate_audio(out), tmp_path), 1200)
    assert max(abs(actual[0] - 6.35), abs(actual[1] - 6.49)) > 0.06


@pytest.mark.parametrize("phase", ["study", "process"])
def test_cancel_during_native_pass_kills_reaps_and_cleans(tmp_path, phase, monkeypatch):
    import os
    import subprocess

    from media_fixtures import float_wav

    audio = float_wav(
        tmp_path / "long.wav", 48000 * 10, sample=lambda i, c: 0.3 * math.sin(i * 0.08)
    )
    seen, children, waited = [], [], []
    original_popen = subprocess.Popen

    def captured_popen(args, **kwargs):
        child = original_popen(args, **kwargs)
        if len(args) > 1 and Path(args[1]).name == "offline_warp_runner.py":
            children.append(child)
            actual_wait = child.wait

            def wait(*args, **kwargs):
                result = actual_wait(*args, **kwargs)
                waited.append(child.pid)
                return result

            monkeypatch.setattr(child, "wait", wait)
        return child

    monkeypatch.setattr(subprocess, "Popen", captured_popen)

    def check():
        for path in tmp_path.glob("vt-warp-*/phase"):
            raw = path.read_text()
            progress = (
                json.loads(raw) if raw.startswith("{") else {"phase": raw, "completed_frames": 0}
            )
            if progress["phase"] == phase:
                assert progress["completed_frames"] > 0, (
                    "phase-entry text does not prove completed native work"
                )
                if progress["completed_frames"] == progress["input_frames"]:
                    continue
                assert 0 < progress["completed_frames"] < progress["input_frames"] == 480000
                child = children[-1]
                assert progress["pid"] == child.pid and child.poll() is None
                seen.append(progress)
                raise RuntimeError("cancel-native")

    with pytest.raises(RuntimeError, match="cancel-native"):
        warp(
            audio,
            tmp_path / "out.wav",
            knots=((F(0), F(0)), (F(480000), F(960000))),
            limits=LIMITS,
            check=check,
        )
    assert seen and len(children) == 1 and children[0].pid in waited
    assert children[0].poll() is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(children[0].pid, os.WNOHANG)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["long.wav"]


def test_silence_invalid_coordinates_and_output_budget(tmp_path):
    from dataclasses import replace

    from media_fixtures import float_wav

    from videotranslate.execution.contracts import StageFailure
    from videotranslate.media.offline_warp import control_map

    audio = float_wav(tmp_path / "silence.wav", 4800)
    result = warp(
        audio,
        tmp_path / "out.wav",
        knots=((F(0), F(0)), (F(4800), F(9600))),
        limits=LIMITS,
        check=lambda: None,
    )
    assert result.sample_count == 9600 and result.peak == 0
    for knots in (((F(0), F(0)), (F(1), F(1)), (F(1), F(2))), ((F(0), F(0)), (F(1, 3), F(1, 3)))):
        with pytest.raises(StageFailure):
            control_map(knots)
    with pytest.raises(StageFailure):
        warp(
            audio,
            tmp_path / "small.wav",
            knots=((F(0), F(0)), (F(4800), F(9600))),
            limits=replace(LIMITS, max_output_bytes=10),
            check=lambda: None,
        )


def test_control_proof_is_cancellable_during_dense_computation():
    from videotranslate.media.offline_warp import control_map

    knots = tuple((F(i * 48), F(i * 72 + (24 if i % 2 else 0))) for i in range(3002))

    def check():
        raise RuntimeError("cancel-control-proof")

    with pytest.raises(RuntimeError, match="cancel-control-proof"):
        control_map(knots, check=check)


def test_original_alternating_one_ms_counterexample_keeps_final_marker(tmp_path):
    knots = [(F(0), F(0))]
    y = 0
    for i in range(1, 3001):
        y += 48 * (1 if i % 2 else 2)
        knots.append((F(i * 48), F(y)))
    knots.append((F(192000), F(264000)))
    audio, _ = marked(tmp_path / "alternating.wav")
    result = warp(
        audio, tmp_path / "out.wav", knots=tuple(knots), limits=LIMITS, check=lambda: None
    )
    assert result.sample_count == 264000
    data = samples(result, tmp_path)
    for a, b, hz in [
        (0.01, 0.15, 400),
        (0.85, 0.99, 600),
        (1.85, 1.99, 800),
        (2.85, 2.99, 1000),
        (3.85, 3.99, 1200),
    ]:
        expected = [t * 1.5 if t <= 3 else 4.5 + t - 3 for t in (a, b)]
        actual = marker_bounds(data, hz)
        assert max(abs(x - y) for x, y in zip(actual, expected, strict=True)) <= 0.06
    facts = json.loads(result.receipt_json)
    assert F(*facts["control_error_samples"]) == 24


def test_continuous_pitch_and_mono_center_preserved(tmp_path):
    from media_fixtures import float_wav

    audio = float_wav(
        tmp_path / "tone.wav",
        RATE,
        channels=1,
        sample=lambda i, c: 0.6 * math.sin(2 * math.pi * 440 * i / RATE),
    )
    result = warp(audio, tmp_path / "out.wav", ratio=F(3, 2), limits=LIMITS, check=lambda: None)
    data = samples(result, tmp_path)
    assert result.sample_count == 72000
    assert max(abs(a - b) for a, b in zip(data[::2], data[1::2], strict=True)) < 1e-6
    middle = data[24000:48000:2]

    def energy(hz):
        return abs(
            sum(
                v
                * complex(
                    math.cos(2 * math.pi * hz * i / RATE), math.sin(2 * math.pi * hz * i / RATE)
                )
                for i, v in enumerate(middle)
            )
        )

    assert energy(440) > 10 * max(energy(420), energy(460))


def test_native_failure_and_malformed_receipt_are_visible_fault_boundaries(tmp_path, monkeypatch):
    from media_fixtures import float_wav

    from videotranslate.execution.contracts import StageFailure
    from videotranslate.media.float_audio import Budget

    audio = float_wav(tmp_path / "a.wav", 4800)
    original = Budget.run

    def fake(self, args, **kwargs):
        if len(args) > 1 and Path(args[1]).name == "offline_warp_runner.py":
            # Labelled fault double: successful exit with invalid/truncated protocol.
            Path(args[-2]).write_text('{"engine":true}')
            Path(args[-3]).write_bytes(b"bad")
            return b""
        return original(self, args, **kwargs)

    monkeypatch.setattr(Budget, "run", fake)
    with pytest.raises(StageFailure):
        warp(audio, tmp_path / "out.wav", ratio=F(2), limits=LIMITS, check=lambda: None)
    assert not (tmp_path / "out.wav").exists() and not list(tmp_path.glob("vt-warp-*"))


def test_unbounded_local_dilation_is_rejected_before_native():
    from videotranslate.execution.contracts import StageFailure
    from videotranslate.media.offline_warp import control_map

    with pytest.raises(StageFailure):
        control_map(((F(0), F(0)), (F(1), F(1000000))))


def test_successful_native_exit_with_missing_output_is_bounded_fault(tmp_path, monkeypatch):
    from media_fixtures import float_wav

    from videotranslate.execution.contracts import StageFailure
    from videotranslate.media.float_audio import Budget

    audio = float_wav(tmp_path / "a.wav", 4800)
    original = Budget.run

    def fake(self, args, **kwargs):
        if len(args) > 1 and Path(args[1]).name == "offline_warp_runner.py":
            Path(args[-2]).write_text(
                json.dumps(
                    dict(engine=3, pitch_scale=1, input_frames=4800, output_frames=9600, peak=0)
                )
            )
            return b""
        return original(self, args, **kwargs)

    monkeypatch.setattr(Budget, "run", fake)
    with pytest.raises(StageFailure):
        warp(audio, tmp_path / "out.wav", ratio=F(2), limits=LIMITS, check=lambda: None)
    assert not (tmp_path / "out.wav").exists()


@pytest.mark.parametrize("fault", ["partial-frame", "short-count", "nonfinite"])
def test_valid_native_receipt_reaches_invalid_output_measurement(tmp_path, monkeypatch, fault):
    """Labelled output-boundary faults; the report itself is valid for this exact request."""
    from pathlib import Path

    from media_fixtures import float_wav

    from videotranslate.execution.contracts import StageFailure
    from videotranslate.media import offline_warp
    from videotranslate.media.float_audio import Budget

    audio = float_wav(tmp_path / "a.wav", 4800)
    original_run, original_measure = Budget.run, offline_warp.measure
    measured = []

    def fake(self, args, **kwargs):
        if len(args) > 1 and Path(args[1]).name == "offline_warp_runner.py":
            Path(args[-2]).write_text(
                json.dumps(
                    dict(engine=3, pitch_scale=1, input_frames=4800, output_frames=9600, peak=0)
                )
            )
            if fault == "partial-frame":
                payload = b"1234567"
            elif fault == "short-count":
                payload = b"\0" * (9599 * 8)
            else:
                payload = array("f", [float("nan"), 0]).tobytes() + b"\0" * (9599 * 8)
            Path(args[-3]).write_bytes(payload)
            return b""
        return original_run(self, args, **kwargs)

    def observed_measure(path, budget):
        measured.append(path.name)
        return original_measure(path, budget)

    monkeypatch.setattr(Budget, "run", fake)
    monkeypatch.setattr(offline_warp, "measure", observed_measure)
    with pytest.raises(StageFailure) as failure:
        warp(audio, tmp_path / "out.wav", ratio=F(2), limits=LIMITS, check=lambda: None)
    assert failure.value.code.value == "INVALID_MEDIA"
    assert measured == ["warped.raw"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["a.wav"]


@pytest.mark.parametrize("fault,exit_code", [("missing-library", 1), ("native-process-exit", 37)])
def test_actual_isolated_native_capability_and_nonzero_fault_cleanup(
    tmp_path, monkeypatch, fault, exit_code
):
    """Labelled fault injection in a real isolated child, with real probe/decode/hash."""
    import subprocess
    import sys

    from media_fixtures import float_wav

    from videotranslate.execution.contracts import StageFailure
    from videotranslate.media.float_audio import Budget

    audio = float_wav(tmp_path / "a.wav", 4800)
    original_run, original_popen = Budget.run, subprocess.Popen
    children = []

    def capture(args, **kwargs):
        child = original_popen(args, **kwargs)
        if args[0] == sys.executable and args[1] == "-c":
            children.append(child)
        return child

    def injected_run(self, args, **kwargs):
        if len(args) > 1 and Path(args[1]).name == "offline_warp_runner.py":
            script = "import os\nfrom videotranslate.media import offline_warp_runner as runner\n"
            if fault == "missing-library":
                script += (
                    "def unavailable(*args,**kwargs):\n raise OSError('injected missing library')\n"
                    "runner.C.CDLL=unavailable\n"
                )
            else:
                script += (
                    "original=runner.library\n"
                    "def fatal_library():\n lib=original()\n"
                    " lib.rubberband_process=lambda *args:os._exit(37)\n return lib\n"
                    "runner.library=fatal_library\n"
                )
            script += "runner.main()\n"
            args = [sys.executable, "-c", script, *args[2:]]
        return original_run(self, args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", capture)
    monkeypatch.setattr(Budget, "run", injected_run)
    with pytest.raises(StageFailure) as failure:
        warp(audio, tmp_path / "out.wav", ratio=F(2), limits=LIMITS, check=lambda: None)
    assert failure.value.code.value == "INVALID_MEDIA"
    assert len(children) == 1 and children[0].poll() == exit_code
    assert sorted(path.name for path in tmp_path.iterdir()) == ["a.wav"]
