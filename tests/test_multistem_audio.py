"""Generated signals prove unity summation; these fixtures are not AI outputs."""

import math
import struct
import subprocess
import wave

import pytest

from videotranslate.execution.contracts import CancellationRequested, FailureCode, StageFailure


def tone(path, frequency, amplitude=0.65, duration=1.04):
    rate = 48000
    samples = [
        round(amplitude * 32767 * math.sin(2 * math.pi * frequency * n / rate))
        for n in range(round(rate * duration))
    ]
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(struct.pack("<hh", x, x) for x in samples))
    return path


def floats(path):
    data = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-c:a", "pcm_f32le", "-"]
    )
    return struct.unpack("<" + "f" * (len(data) // 4), data)


def test_real_three_tone_unity_sum_excludes_vocals_and_preserves_headroom(tmp_path):
    from videotranslate.media.audio import validate_audio
    from videotranslate.media.separation import prepare_outputs

    stems = {
        kind: validate_audio(tone(tmp_path / f"{kind}.wav", frequency))
        for kind, frequency in (("drums", 220), ("bass", 440), ("vocals", 1760), ("other", 880))
    }
    outputs = prepare_outputs(stems, tmp_path, adapter="demucs_multistem", duration_ms=1000)
    background = outputs["instrumental"]
    assert background.metadata()["codec"] == "pcm_f32le"
    assert background.metadata()["container"] == "wav"
    assert background.duration_ms == 1000 and background.channels == 2
    actual = floats(background.path)[::2]
    original = {kind: floats(stem.path)[::2] for kind, stem in stems.items()}
    expected = [sum(original[k][n] for k in ("drums", "bass", "other")) for n in range(48000)]
    assert len(actual) == 48000
    assert max(abs(a - e) for a, e in zip(actual, expected, strict=True)) < 1e-6
    assert max(actual) > 1.0  # headroom survives; no clipping or limiter
    for frequency in (220, 440, 880, 1760):
        amplitude = abs(
            2
            / len(actual)
            * sum(x * math.sin(2 * math.pi * frequency * n / 48000) for n, x in enumerate(actual))
        )
        assert amplitude == pytest.approx(0 if frequency == 1760 else 0.65, abs=0.0001)
    info = __import__("json").loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(background.path)]
        )
    )
    assert info["streams"][0]["codec_name"] == "pcm_f32le"
    assert outputs["vocals"].duration_ms == 1000


def test_compressed_stem_is_reencoded_to_real_wav(tmp_path):
    from videotranslate.media.audio import validate_audio
    from videotranslate.media.separation import prepare_outputs

    wav = tone(tmp_path / "input.wav", 300)
    compressed = tmp_path / "input.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), str(compressed)], check=True)
    audio = validate_audio(compressed)
    result = prepare_outputs(
        {"vocals": audio, "instrumental": audio}, tmp_path, adapter="demucs", duration_ms=1040
    )
    for stem in result.values():
        assert stem.path.read_bytes()[:4] == b"RIFF"
        assert stem.path.suffix == ".wav" and stem.duration_ms == 1040


def test_projected_float_limits_and_cancellation_are_bounded(tmp_path):
    from videotranslate.media.audio import validate_audio
    from videotranslate.media.separation import prepare_outputs, validate_projection

    with pytest.raises(StageFailure) as error:
        validate_projection(200000, "demucs_multistem")
    assert error.value.code == FailureCode.MEDIA_LIMIT
    with pytest.raises(StageFailure):
        validate_projection(14400001, "demucs_multistem")
    stem = validate_audio(tone(tmp_path / "input.wav", 300))

    checks = 0

    def cancel():
        nonlocal checks
        checks += 1
        if checks >= 3:
            raise CancellationRequested()

    with pytest.raises(CancellationRequested):
        prepare_outputs(
            {k: stem for k in ("drums", "bass", "vocals", "other")},
            tmp_path,
            adapter="demucs_multistem",
            duration_ms=1000,
            check=cancel,
        )
    assert checks >= 3
    assert not (tmp_path / "prepared-vocals.wav").exists()
    assert not (tmp_path / "prepared-instrumental.wav").exists()


@pytest.mark.parametrize("rate,channels", [(44100, 2), (48000, 1)])
def test_multistem_rejects_format_drift_before_implicit_channel_gain(tmp_path, rate, channels):
    from videotranslate.media.audio import validate_audio
    from videotranslate.media.separation import prepare_outputs

    source = tone(tmp_path / "source.wav", 220)
    path = tmp_path / "drift.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(source),
            "-ar",
            str(rate),
            "-ac",
            str(channels),
            str(path),
        ],
        check=True,
    )
    stem = validate_audio(path)
    with pytest.raises(StageFailure) as error:
        prepare_outputs(
            {kind: stem for kind in ("drums", "bass", "vocals", "other")},
            tmp_path,
            adapter="demucs_multistem",
            duration_ms=1000,
        )
    assert error.value.code == FailureCode.INVALID_MEDIA
