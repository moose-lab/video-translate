"""Guarded direct adaptive downloads and bounded local-only lossless MP4 mux."""

import math
import time

from ..execution.contracts import FailureCode, StageFailure
from .finishing_types import RenderLimits
from .float_audio import Budget, digest


def download_pair(http, spec, output, *, maximum, deadline, check_active):
    def check():
        check_active()
        if time.monotonic() >= deadline:
            raise StageFailure(FailureCode.MEDIA_LIMIT)

    check()
    budget = Budget(
        RenderLimits(
            max_output_bytes=maximum,
            # Both input streams together <= maximum; output <= maximum.
            max_temporary_bytes=2 * maximum + 1024 * 1024,
            max_wall_seconds=max(1, min(300, math.ceil(deadline - time.monotonic()))),
            max_video_frames=3456000,
        ),
        check,
        output.parent,
    )
    video, audio = output.with_name("video.mp4"), output.with_name("audio.m4a")
    remaining = maximum
    for url, path in ((spec.video_url, video), (spec.audio_url, audio)):
        budget.check()
        if remaining <= 0:
            raise StageFailure(FailureCode.MEDIA_LIMIT)
        with path.open("xb") as stream:
            metadata = http.fetch(
                url,
                stream,
                max_bytes=remaining,
                deadline=deadline,
                check_active=budget.check,
                youtube=True,
            )
        remaining -= metadata["byte_size"]
        budget.check()
    budget.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-n",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            "mov",
            "-i",
            str(video),
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            "mov",
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c",
            "copy",
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-movflags",
            "+faststart",
            str(output),
        ],
        output=output,
    )
    budget.check()
    size = output.stat().st_size
    if not 0 < size <= maximum:
        raise StageFailure(FailureCode.MEDIA_LIMIT)
    return dict(byte_size=size, sha256=digest(output, budget.check))
