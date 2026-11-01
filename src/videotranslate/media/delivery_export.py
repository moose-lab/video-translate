"""CPU muxing: explicit AAC track metadata, full decode and path-free receipts."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .float_audio import digest, invalid


@dataclass(frozen=True)
class ExportedFile:
    path: Path
    facts: dict

    def metadata(self):
        return self.facts


def mux(
    video,
    audios,
    destination,
    *,
    default_track,
    duration_ms,
    budget,
    video_metadata=None,
    original_language="auto",
):
    if not audios or default_track not in [tag for tag, _ in audios]:
        raise invalid()
    args = ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-y", "-i", str(video)]
    for _, audio in audios:
        args += ["-i", str(audio)]
    args += ["-map", "0:v:0"]
    for i in range(len(audios)):
        args += ["-map", f"{i + 1}:a:0"]
    args += [
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
    ]
    expected_tags = []
    for i, (tag, _) in enumerate(audios):
        from ..languages.catalog import resolve

        try:
            selected = original_language if tag == "original" else tag
            language = (
                "zho" if selected.split("-")[0] == "zh" else resolve(selected)["iso639_3"] or "und"
            )
        except ValueError:
            raise invalid() from None
        expected_tags.append(language)
        args += [
            f"-metadata:s:a:{i}",
            f"language={language}",
            f"-metadata:s:a:{i}",
            f"title={tag}",
            f"-disposition:a:{i}",
            "default" if tag == default_track else "0",
        ]
    # Explicit padding policy: audio is padded to the measured CFR picture end.
    args += ["-af", "apad", "-t", f"{duration_ms / 1000:.9f}", str(destination)]
    budget.run(args, output=destination)
    info = json.loads(
        budget.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-count_frames",
                "-of",
                "json",
                str(destination),
            ]
        )
    )
    streams = info["streams"]
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if (
        len(videos) != 1
        or len(audio_streams) != len(audios)
        or len(streams) != 1 + len(audios)
        or videos[0]["codec_name"] != "h264"
        or videos[0]["pix_fmt"] != "yuv420p"
    ):
        raise invalid()
    if video_metadata and (
        int(videos[0].get("nb_read_frames", 0)) != video_metadata["frame_count"]
        or videos[0]["avg_frame_rate"]
        != f"{video_metadata['frame_rate'][0]}/{video_metadata['frame_rate'][1]}"
    ):
        raise invalid()
    if sum(a["disposition"]["default"] for a in audio_streams) != 1:
        raise invalid()
    for stream, language, (tag, _) in zip(audio_streams, expected_tags, audios, strict=True):
        if (
            stream["codec_name"] != "aac"
            or int(stream["sample_rate"]) != 48000
            or stream["channels"] != 2
            or stream.get("tags", {}).get("language") != language
            or bool(stream["disposition"]["default"]) != (tag == default_track)
        ):
            raise invalid()
        if abs(float(stream["duration"]) * 1000 - duration_ms) > 24:
            raise invalid()
    actual_duration = float(info["format"]["duration"]) * 1000
    if not math.isfinite(actual_duration) or abs(actual_duration - duration_ms) > 42:
        raise invalid()
    budget.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(destination),
            "-map",
            "0",
            "-f",
            "null",
            "-",
        ]
    )
    return ExportedFile(
        destination,
        dict(
            sha256=digest(destination, budget.check),
            byte_size=destination.stat().st_size,
            duration_ms=round(actual_duration),
            codec="h264",
            container="mp4",
            audio_tracks=[
                dict(tag=tag, language=language, default=tag == default_track)
                for (tag, _), language in zip(audios, expected_tags, strict=True)
            ],
            audio_padding_policy="silence_to_cfr_picture_end_v1",
            audio_padding_limit_ms=42,
        ),
    )


def mp3(audio, destination, *, budget, expected_samples=None):
    from .float_audio import measure

    budget.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-y",
            "-i",
            str(audio),
            "-map",
            "0:a:0",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(destination),
        ],
        output=destination,
    )
    info = json.loads(
        budget.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(destination),
            ]
        )
    )
    streams = info["streams"]
    if (
        len(streams) != 1
        or streams[0]["codec_type"] != "audio"
        or streams[0]["codec_name"] != "mp3"
        or int(streams[0]["sample_rate"]) != 48000
        or streams[0]["channels"] != 2
    ):
        raise invalid()
    decoded = destination.with_suffix(".decoded.raw")
    budget.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-y",
            "-i",
            str(destination),
            "-map",
            "0:a:0",
            "-c:a",
            "pcm_f32le",
            "-f",
            "f32le",
            str(decoded),
        ],
        output=decoded,
    )
    proof = measure(decoded, budget)
    decoded.unlink()
    if expected_samples is not None and proof.frames != expected_samples:
        raise invalid()
    # MP3 carries encoder delay in its Xing header; report decoded speech samples.
    return ExportedFile(
        destination,
        dict(
            sha256=digest(destination, budget.check),
            byte_size=destination.stat().st_size,
            codec="mp3",
            container="mp3",
            sample_rate=48000,
            channels=2,
            actual_decoded_samples=proof.frames,
            decoded_peak=proof.peak,
            duration_ms=round(proof.frames / 48),
            padding_policy="xing_gapless_decoded_samples_v1",
        ),
    )
