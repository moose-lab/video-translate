"""Exact piecewise map, one post-map CFR grid and measured video-only output.

Clock policy: FFmpeg copyts/start_at_zero uses the container's common demuxer
origin. Selection is absolute relative to that origin, FitPlan is selection
relative. The first selected picture is cloned backwards to grid zero if
missing; no picture anywhere in the window is an error. Last picture is held
through ceil(planned_seconds*fps) frames. Padding is strictly < one frame.
"""

import json
import math
import re
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Callable

from .audio import VIDEO_FORMATS
from .finishing_types import RenderLimits, VideoFile, rational, receipt
from .fit_plan import validate_plan
from .fit_types import MAX_SOURCE_MS, FitPlan
from .float_audio import Budget, digest, invalid, limited, publish
from .timing import timeline_bounds

FRAME_RATES = frozenset(map(Fraction, (24, 25, 30, 50, 60))) | frozenset(
    (Fraction(24000, 1001), Fraction(30000, 1001), Fraction(60000, 1001))
)
MAX_FILTER_BYTES = 1024 * 1024


def number(value):
    value = Fraction(value)
    return f"({value.numerator}/{value.denominator})"


def expression(plan, timestamp):
    """Balanced numeric syntax only: depth <=12 at 3001 pieces, no linear chain."""

    def branch(left, right):
        if right - left == 1:
            p = plan.pieces[left]
            slope = (p.output_end_ms - p.output_start_ms) / (p.source_end_ms - p.source_start_ms)
            return (
                f"({number(p.output_start_ms)}+({timestamp}-{p.source_start_ms})*{number(slope)})"
            )
        middle = (left + right) // 2
        boundary = plan.pieces[middle].source_start_ms
        return f"if(lt({timestamp},{boundary}),{branch(left, middle)},{branch(middle, right)})"

    result = branch(0, len(plan.pieces))
    if len(result.encode()) > MAX_FILTER_BYTES:
        raise limited()
    return result


def _probe(path, budget, *, counted=False):
    args = [
        "ffprobe",
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-format_whitelist",
        VIDEO_FORMATS,
        "-show_format",
        "-show_streams",
        "-of",
        "json",
    ]
    if counted:
        args.append("-count_frames")
    args.append(str(path))
    try:
        return json.loads(budget.run(args))
    except (ValueError, UnicodeError):
        raise invalid() from None


def retime_video(
    source: Path,
    destination: Path,
    *,
    source_sha256: str,
    absolute_start_ms: int,
    absolute_end_ms: int,
    plan: FitPlan,
    frame_rate: Fraction,
    limits: RenderLimits,
    check: Callable[[], None],
) -> VideoFile:
    validate_plan(plan)
    if (
        not plan.feasible
        or type(frame_rate) is not Fraction
        or frame_rate not in FRAME_RATES
        or type(absolute_start_ms) is not int
        or type(absolute_end_ms) is not int
        or not 0 <= absolute_start_ms < absolute_end_ms <= MAX_SOURCE_MS
        or absolute_end_ms - absolute_start_ms != plan.source_duration_ms
        or type(source_sha256) is not str
        or not re.fullmatch("[0-9a-f]{64}", source_sha256)
    ):
        raise invalid()
    source, destination = Path(source), Path(destination)
    if destination.exists() or source == destination:
        raise invalid()
    frames = math.ceil(plan.output_duration_ms * frame_rate / 1000)
    with tempfile.TemporaryDirectory(prefix="vt-video-", dir=destination.parent) as d:
        directory = Path(d)
        budget = Budget(limits, check, directory)
        if frames > limits.max_video_frames:
            raise limited()
        if digest(source, budget.check) != source_sha256:
            raise invalid()
        info = _probe(source, budget)
        try:
            origin, duration = timeline_bounds(info)
            stream = next(s for s in info["streams"] if s.get("codec_type") == "video")
            width, height = int(stream["width"]), int(stream["height"])
            if (
                absolute_end_ms > round(duration * 1000) + 1
                or not 1 <= width <= 8192
                or not 1 <= height <= 8192
                or width * height > 33554432
            ):
                raise ValueError()
        except (ValueError, KeyError, TypeError, StopIteration, OverflowError):
            raise invalid() from None
        timestamp = f"(PTS*TB*1000-{absolute_start_ms})"
        mapped = expression(plan, timestamp)
        rate = f"{frame_rate.numerator}/{frame_rate.denominator}"
        graph = (
            f"trim=start={float(Fraction(absolute_start_ms, 1000))}:"
            f"end={float(Fraction(absolute_end_ms, 1000))},"
            f"settb=expr=1/1000000,setpts='{mapped}/1000/TB',"
            f"tpad=stop_mode=clone:stop_duration={float(plan.output_duration_ms / 1000)},"
            f"fps=fps={rate}:round=down:eof_action=pass:start_time=0,trim=end_frame={frames},"
            "pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:color=black,format=yuv420p"
        )
        if len(graph.encode()) > MAX_FILTER_BYTES:
            raise limited()
        control = directory / "filter.txt"
        budget.preflight(len(graph.encode()), output=False)
        control.write_text(graph)
        output = directory / "video.mp4"
        budget.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-format_whitelist",
                VIDEO_FORMATS,
                "-copyts",
                "-start_at_zero",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-an",
                "-sn",
                "-dn",
                "-filter_script:v",
                str(control),
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-fps_mode",
                "passthrough",
                "-movflags",
                "+faststart",
                str(output),
            ],
            output=output,
        )
        # -count_frames traverses the full stream, then xerror decode rejects
        # damaged payload rather than treating container headers as proof.
        actual = _probe(output, budget, counted=True)
        try:
            if len(actual["streams"]) != 1:
                raise ValueError()
            measured = actual["streams"][0]
            count = int(measured["nb_read_frames"])
            measured_rate = Fraction(measured["avg_frame_rate"])
            seconds = Fraction(measured["duration"])
            if (
                count != frames
                or measured_rate != frame_rate
                or measured["codec_name"] != "h264"
                or measured["pix_fmt"] != "yuv420p"
                or int(measured["width"]) != width + (width % 2)
                or int(measured["height"]) != height + (height % 2)
                or abs(seconds - Fraction(count, 1) / frame_rate) > Fraction(1, 1000000)
                or not 0 < output.stat().st_size <= limits.max_output_bytes
            ):
                raise ValueError()
        except (ValueError, KeyError, TypeError, ZeroDivisionError):
            raise invalid() from None
        budget.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-i",
                str(output),
                "-map",
                "0:v:0",
                "-f",
                "null",
                "-",
            ]
        )
        facts = {
            "policy": "common-origin-balanced-map-global-cfr-v1",
            "planned_duration_ms": rational(plan.output_duration_ms),
            "actual_frames": count,
            "frame_rate": rational(frame_rate),
            "frame_padding_ms": rational(
                Fraction(count, 1) / frame_rate * 1000 - plan.output_duration_ms
            ),
            "frame_arrival_rounding": "floor-after-map-1us-ticks-v1",
            "initial_picture": "clone-first-selected-to-zero",
            "tail_picture": "clone-last-through-ceiling-grid",
            "odd_padding_right_bottom": [width % 2, height % 2],
            "source_sha256": source_sha256,
            "absolute_selection_ms": [absolute_start_ms, absolute_end_ms],
            "common_origin_seconds": origin,
            "filter_bytes": len(graph.encode()),
        }
        result = VideoFile(
            destination,
            digest(output, budget.check),
            output.stat().st_size,
            round(seconds * 1000),
            "h264",
            "mov,mp4,m4a,3gp,3g2,mj2",
            width + width % 2,
            height + height % 2,
            frame_rate,
            count,
            receipt(facts),
        )
        budget.check()
        publish(output, destination)
        return result
