"""Real CPU fixtures: these are media checks, never inference proof."""

import math
import struct
import subprocess
import wave

import pytest

from videotranslate.execution.contracts import FailureCode, StageFailure


@pytest.fixture(scope="module")
def offset_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("offset-source") / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=64x48:r=5:d=8",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=8",
            "-itsoffset",
            "2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=6",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.mark.parametrize(
    "start,end,silent", [(0, 8000, True), (1000, 5000, True), (3000, 7000, False)]
)
def test_selected_audio_ordinal_preserves_delayed_common_timeline(
    offset_video, tmp_path, start, end, silent
):
    from videotranslate.media.audio import extract_audio

    result = extract_audio(
        offset_video,
        tmp_path / "audio.wav",
        audio_ordinal=1,
        start_ms=start,
        end_ms=end,
        sample_rate=16000,
        channels=1,
    )
    assert result.duration_ms == end - start
    assert result.sample_rate == 16000 and result.channels == 1
    assert len(result.sha256) == 64 and result.byte_size == result.path.stat().st_size
    with wave.open(str(result.path)) as wav:
        assert wav.getsampwidth() == 2
        samples = struct.unpack("<" + "h" * wav.getnframes(), wav.readframes(wav.getnframes()))
    rms = math.sqrt(sum(x * x for x in samples[:8000]) / 8000)
    assert (rms < 10) == silent
    tone = samples[-16000:]
    frequency = sum(a <= 0 < b for a, b in zip(tone, tone[1:], strict=False))
    assert 875 <= frequency <= 885
    assert offset_video.stat().st_size > 0  # whole immutable source still retained


@pytest.mark.parametrize("content", [b"not audio", b"#EXTM3U\nfile:///etc/passwd\n"])
def test_reject_nonmedia_and_nested_resources(tmp_path, content):
    from videotranslate.media.audio import validate_audio

    path = tmp_path / "untrusted.wav"
    path.write_bytes(content)
    with pytest.raises(StageFailure) as error:
        validate_audio(path)
    assert error.value.code == FailureCode.INVALID_MEDIA


def test_extract_rejects_unknown_ordinal_and_limits(offset_video, tmp_path):
    from videotranslate.media.audio import extract_audio

    with pytest.raises(StageFailure):
        extract_audio(offset_video, tmp_path / "bad.wav", audio_ordinal=2, start_ms=0, end_ms=8000)
    with pytest.raises(StageFailure) as error:
        extract_audio(
            offset_video,
            tmp_path / "large.wav",
            audio_ordinal=0,
            start_ms=0,
            end_ms=8000,
            max_bytes=100,
        )
    assert error.value.code == FailureCode.MEDIA_LIMIT
    assert not (tmp_path / "large.wav").exists()


@pytest.mark.parametrize("extension", ["mp4", "mkv"])
def test_nonzero_common_origin_has_relative_duration_and_window(tmp_path, extension):
    from videotranslate.media.audio import VIDEO_FORMATS, extract_audio, inspect
    from videotranslate.media.probe import normalize_probe

    path = tmp_path / ("offset." + extension)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=64x48:r=5:d=8",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:duration=8",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-output_ts_offset",
            "10",
            str(path),
        ],
        check=True,
    )
    info = inspect(path, VIDEO_FORMATS)
    probe = normalize_probe(info, max_duration=100, max_pixels=100000)
    assert 7900 < probe["duration_ms"] < 8200
    result = extract_audio(
        path,
        tmp_path / "normalized.wav",
        audio_ordinal=0,
        start_ms=3000,
        end_ms=7000,
        sample_rate=16000,
        channels=1,
    )
    assert result.duration_ms == 4000
    with wave.open(str(result.path)) as wav:
        tone = struct.unpack("<" + "h" * 16000, wav.readframes(16000))
    assert 655 <= sum(a <= 0 < b for a, b in zip(tone, tone[1:], strict=False)) <= 665


def test_normal_mp3_encoder_priming_is_supported_without_silent_trim(tmp_path):
    from videotranslate.media.audio import extract_audio, validate_audio

    source = tmp_path / "reference.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:duration=3",
            "-c:a",
            "libmp3lame",
            str(source),
        ],
        check=True,
    )
    info = validate_audio(source)
    audio = extract_audio(
        source,
        tmp_path / "reference.wav",
        audio_only=True,
        audio_ordinal=0,
        start_ms=0,
        end_ms=info.duration_ms,
        sample_rate=16000,
        channels=1,
    )
    assert audio.duration_ms == info.duration_ms
    with wave.open(str(audio.path)) as wav:
        first = struct.unpack("<" + "h" * 16000, wav.readframes(16000))
    assert 655 <= sum(a <= 0 < b for a, b in zip(first, first[1:], strict=False)) <= 665
