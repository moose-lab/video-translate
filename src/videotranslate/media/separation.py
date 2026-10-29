"""Bounded CPU preparation of remote stems, never model inference or final dub mixing."""

from pathlib import Path

from ..execution.contracts import FailureCode, StageFailure
from .audio import AUDIO_FORMATS, MAX_BYTES, run_process, validate_audio


def validate_projection(duration_ms, adapter, *, max_bytes=MAX_BYTES):
    # Published WAVs use the working-audio format: 48 kHz stereo.
    # Float preserves the unity sum even when it exceeds integer full scale.
    width = 4 if adapter == "demucs_multistem" else 2
    if (
        type(duration_ms) is not int
        or not 0 < duration_ms <= 14400000
        or duration_ms * 48000 * 2 * width / 1000 + 4096 > max_bytes
    ):
        raise StageFailure(FailureCode.MEDIA_LIMIT)


def _render(inputs, destination, *, duration_ms, floating, check, timeout, max_bytes):
    """Normalize a single stem or add three stems without attenuation/clipping."""
    destination = Path(destination)
    check()
    args = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-xerror",
        "-y",
        "-filter_complex_threads",
        "1",
        "-filter_threads",
        "1",
    ]
    for path in inputs:
        args += [
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            AUDIO_FORMATS,
            "-threads",
            "1",
            "-i",
            str(path),
        ]
    frames = duration_ms * 48
    tail = f"aresample=48000,apad=whole_len={frames},atrim=end_sample={frames},asetpts=PTS-STARTPTS"
    if len(inputs) == 3:
        args += [
            "-filter_complex",
            "[0:a:0][1:a:0][2:a:0]"
            "amix=inputs=3:duration=longest:weights='1 1 1':normalize=false:"
            "dropout_transition=0," + tail + "[out]",
            "-map",
            "[out]",
        ]
    else:
        args += ["-map", "0:a:0", "-af", tail]
    args += [
        "-vn",
        "-threads",
        "1",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_f32le" if floating else "pcm_s16le",
        "-f",
        "wav",
        str(destination),
    ]
    try:
        run_process(
            args, timeout=timeout, check=check, output_path=destination, max_bytes=max_bytes
        )
        return validate_audio(
            destination,
            max_bytes=max_bytes,
            expected_duration_ms=duration_ms,
            check=check,
            timeout=timeout,
        )
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def normalize_stem(
    audio, destination, *, duration_ms, check=lambda: None, timeout=60, max_bytes=MAX_BYTES
):
    """Preserve legacy per-stem checkpointing while ensuring an actual WAV container."""
    validate_projection(duration_ms, "demucs", max_bytes=max_bytes)
    return _render(
        [audio.path],
        destination,
        duration_ms=duration_ms,
        floating=False,
        check=check,
        timeout=timeout,
        max_bytes=max_bytes,
    )


def prepare_outputs(
    stems, directory, *, adapter, duration_ms, check=lambda: None, timeout=60, max_bytes=MAX_BYTES
):
    """Use only drums + bass + other at unity gain; vocals remain separate.

    FFmpeg `-h filter=amix` documents normalize=true as the default. Explicit
    normalize=false and unit weights are essential; pcm_f32le retains headroom.
    Every input has already passed full decode and size/duration validation.
    """
    from ..providers.demucs import output_mapping

    validate_projection(duration_ms, adapter, max_bytes=max_bytes)
    if set(stems) != set(output_mapping(adapter)):
        raise StageFailure(FailureCode.INVALID_MEDIA)
    if adapter == "demucs_multistem" and any(
        stem.sample_rate != 48000 or stem.channels != 2 for stem in stems.values()
    ):
        # This profile retains the stereo/48k working input. Reject format drift
        # instead of implicitly changing channel gain while reconstructing it.
        raise StageFailure(FailureCode.INVALID_MEDIA)
    results = {}
    try:
        for kind in ("vocals", "instrumental"):
            selected = (
                [stems[k].path for k in ("drums", "bass", "other")]
                if adapter == "demucs_multistem" and kind == "instrumental"
                else [stems[kind].path]
            )
            results[kind] = _render(
                selected,
                Path(directory) / ("prepared-" + kind + ".wav"),
                duration_ms=duration_ms,
                floating=adapter == "demucs_multistem",
                check=check,
                timeout=timeout,
                max_bytes=max_bytes,
            )
        return results
    except BaseException:
        for audio in results.values():
            audio.path.unlink(missing_ok=True)
        raise
