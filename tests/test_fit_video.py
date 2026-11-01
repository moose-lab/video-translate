import json
import subprocess
from fractions import Fraction as F

import pytest
from media_fixtures import golden_plan, sha
from test_float_audio import LIMITS

from videotranslate.media.fit_video import retime_video


def video(path, *, rate="30", offset=0, container=None, vfr=False):
    # Widely separated 5x5x5 RGB codes identify 120 source frames.
    # Output IDs are matched to decoded source centroids, not encoded RGB.
    raw = path.with_suffix(".rgb")
    colors = [
        (20 + (i % 5) * 50, 20 + ((i // 5) % 5) * 50, 20 + (i // 25) * 50) for i in range(120)
    ]
    raw.write_bytes(b"".join(bytes(color) * 32 * 32 for color in colors))
    args = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgb24",
        "-video_size",
        "32x32",
        "-framerate",
        rate,
        "-i",
        str(raw),
    ]
    if vfr:
        args += ["-vf", "select='not(eq(mod(n,5),2))'", "-fps_mode", "vfr"]
    args += ["-c:v", "libx264", "-crf", "0", "-pix_fmt", "yuv444p"]
    if offset:
        args += ["-output_ts_offset", str(offset)]
    if container:
        args += ["-f", container]
    args += [str(path)]
    subprocess.run(args, check=True, timeout=30)
    raw.unlink()
    return colors


def rgb_frames(path):
    data = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-pix_fmt",
            "rgb24",
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    return [tuple(data[i : i + 3]) for i in range(0, len(data), 32 * 32 * 3)]


def decode(path, reference):
    ideal = [(20 + (i % 5) * 50, 20 + ((i // 5) % 5) * 50, 20 + (i // 25) * 50) for i in range(120)]
    palette = rgb_frames(reference)

    def distance(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b, strict=True))

    ids = [min(range(120), key=lambda i: distance(rgb, ideal[i])) for rgb in palette]
    result = []
    for rgb in rgb_frames(path):
        best = min(range(len(palette)), key=lambda i: distance(rgb, palette[i]))
        # Independent codec identification bound (<12 RGB units, code spacing50).
        assert distance(rgb, palette[best]) < 144
        result.append(ids[best])
    return result


def assert_frame_grid(result, source, plan, start_ms=0, end_ms=4000):
    """Compare chosen pictures to source PTS after exact map and one ceiling grid."""
    from math import floor

    info = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_frames",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
    )
    base = F(info["format"].get("start_time", "0"))
    tb = F(info["streams"][0]["time_base"])
    source_ids = decode(source, source)
    selected = []
    for item, frame_id in zip(info["frames"], source_ids, strict=True):
        ms = (int(item["best_effort_timestamp"]) * tb - base) * 1000
        if start_ms <= ms < end_ms:
            ms -= start_ms
            piece = next(p for p in plan.pieces if p.source_start_ms <= ms <= p.source_end_ms)
            mapped = piece.output_start_ms + (ms - piece.source_start_ms) * (
                piece.output_end_ms - piece.output_start_ms
            ) / (piece.source_end_ms - piece.source_start_ms)
            selected.append((floor(mapped * result.frame_rate / 1000), frame_id))
    actual = decode(result.path, source)
    for index, frame_id in enumerate(actual):

        def expected_at(grid):
            candidates = [(at, f) for at, f in selected if at <= grid]
            return candidates[-1][1] if candidates else selected[0][1]

        expected = expected_at(index)
        # Source timestamp rescaling and setpts integer rounding contribute at
        # most one output-grid cell; RGB classification adds zero frame allowance.
        allowed = {expected_at(index - 1), expected, expected_at(index + 1)}
        assert frame_id in allowed, (index, frame_id, expected)
    return actual


def test_actual_golden_video_color_frame_coverage_and_tail(tmp_path):
    source = tmp_path / "in.mp4"
    video(source)
    before = sha(source)
    result = retime_video(
        source,
        tmp_path / "out.mp4",
        source_sha256=before,
        absolute_start_ms=0,
        absolute_end_ms=4000,
        plan=golden_plan(),
        frame_rate=F(30),
        limits=LIMITS,
        check=lambda: None,
    )
    assert result is not None, "actual decoded retimed video is required"
    assert result.frame_count == 195 and result.frame_rate == 30
    assert result.codec == "h264" and result.duration_ms == 6500
    frames = assert_frame_grid(result, source, golden_plan())
    assert len(frames) == 195 and frames[0] == 0 and frames[-1] == 119
    assert all(a <= b + 1 for a, b in zip(frames, frames[1:], strict=False))
    for at, expected in [(1.5, 30), (3.5, 60), (5.5, 90)]:
        assert abs(frames[round(at * 30)] - expected) <= 1
    assert sha(source) == before and "path" not in result.metadata()
    assert json.loads(result.receipt_json)["planned_duration_ms"] == [6500, 1]


@pytest.mark.parametrize(
    "rate", [F(24), F(25), F(30), F(50), F(60), F(24000, 1001), F(30000, 1001), F(60000, 1001)]
)
def test_all_exact_output_rates_one_global_grid(tmp_path, rate):
    from math import ceil

    source = tmp_path / "source.mp4"
    video(source, rate="30000/1001", vfr=True)
    result = retime_video(
        source,
        tmp_path / "out.mp4",
        source_sha256=sha(source),
        absolute_start_ms=0,
        absolute_end_ms=4000,
        plan=golden_plan(),
        frame_rate=rate,
        limits=LIMITS,
        check=lambda: None,
    )
    assert result.frame_count == ceil(F(13, 2) * rate)
    frames = assert_frame_grid(result, source, golden_plan())
    assert frames[-1] == 119 and len(frames) == result.frame_count
    assert all(a <= b + 1 for a, b in zip(frames, frames[1:], strict=False))
    padding = F(*json.loads(result.receipt_json)["frame_padding_ms"])
    assert 0 <= padding < 1000 / rate


@pytest.mark.parametrize("extension,offset", [("mp4", 5), ("mkv", 5), ("mkv", 0)])
def test_common_origin_absolute_between_frame_selection(tmp_path, extension, offset):
    from videotranslate.media.fit_plan import build_plan

    source = tmp_path / f"source.{extension}"
    video(source, offset=offset)
    result = retime_video(
        source,
        tmp_path / "out.mp4",
        source_sha256=sha(source),
        absolute_start_ms=1010,
        absolute_end_ms=3010,
        plan=build_plan(2000, []),
        frame_rate=F(30),
        limits=LIMITS,
        check=lambda: None,
    )
    frames = decode(result.path, source)
    assert len(frames) == 60 and frames[0] == 31 and frames[-1] == 90


def test_delayed_video_uses_audio_common_clock_and_empty_window_fails(tmp_path):
    from videotranslate.execution.contracts import StageFailure
    from videotranslate.media.fit_plan import build_plan

    source, delayed = tmp_path / "source.mp4", tmp_path / "delayed.mp4"
    video(source)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-itsoffset",
            "1",
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-t",
            "5",
            str(delayed),
        ],
        check=True,
        timeout=30,
    )
    result = retime_video(
        delayed,
        tmp_path / "out.mp4",
        source_sha256=sha(delayed),
        absolute_start_ms=0,
        absolute_end_ms=4000,
        plan=build_plan(4000, []),
        frame_rate=F(30),
        limits=LIMITS,
        check=lambda: None,
    )
    frames = decode(result.path, source)
    assert max(frames[:30]) <= 1 and abs(frames[60] - 30) <= 2
    with pytest.raises(StageFailure):
        retime_video(
            delayed,
            tmp_path / "none.mp4",
            source_sha256=sha(delayed),
            absolute_start_ms=0,
            absolute_end_ms=500,
            plan=build_plan(500, []),
            frame_rate=F(30),
            limits=LIMITS,
            check=lambda: None,
        )
    assert not (tmp_path / "none.mp4").exists()


def test_actual_dense_plan_balanced_parser_and_source_coverage(tmp_path):
    from videotranslate.media.fit_plan import build_plan
    from videotranslate.media.fit_types import FitLine, FitSettings
    from videotranslate.media.fit_video import MAX_FILTER_BYTES, expression

    plan = build_plan(
        4000,
        [FitLine("zh", str(i), str(i), 3 * i + 1, 3 * i + 2, 4) for i in range(1000)],
        FitSettings(mode="smart", max_audio_speed=F(1), max_borrow_ms=1),
    )
    assert len(plan.pieces) == 3001
    graph = expression(plan, "(PTS*TB*1000)")
    assert len(graph.encode()) < MAX_FILTER_BYTES
    source = tmp_path / "source.mp4"
    video(source)
    result = retime_video(
        source,
        tmp_path / "out.mp4",
        source_sha256=sha(source),
        absolute_start_ms=0,
        absolute_end_ms=4000,
        plan=plan,
        frame_rate=F(30),
        limits=LIMITS,
        check=lambda: None,
    )
    frames = decode(result.path, source)
    assert len(frames) == 180 and frames[-1] >= 118
    assert all(a <= b + 1 for a, b in zip(frames, frames[1:], strict=False))


def test_target_maps_actual_second_line_onsets(tmp_path):
    from videotranslate.media.fit_plan import build_plan
    from videotranslate.media.fit_types import FitLine, FitSettings

    zh = [FitLine("zh", "a", "r", 0, 2000, 3000), FitLine("zh", "b", "r", 3000, 4000, 1000)]
    ja = [FitLine("ja", "a", "r", 0, 2000, 4000), FitLine("ja", "b", "r", 3000, 4000, 1000)]
    source = tmp_path / "source.mp4"
    video(source)
    for key, rows, seconds, onset in [("zh", zh, 5, 4), ("ja", ja, 6, 5), ("both", zh + ja, 6, 5)]:
        plan = build_plan(4000, rows, FitSettings(mode="smart", max_audio_speed=F(1)))
        result = retime_video(
            source,
            tmp_path / f"{key}.mp4",
            source_sha256=sha(source),
            absolute_start_ms=0,
            absolute_end_ms=4000,
            plan=plan,
            frame_rate=F(30),
            limits=LIMITS,
            check=lambda: None,
        )
        frames = decode(result.path, source)
        assert len(frames) == seconds * 30 and abs(frames[onset * 30] - 90) <= 2


def test_video_caps_hash_cancel_and_no_overwrite(tmp_path):
    from dataclasses import replace

    from videotranslate.execution.contracts import StageFailure

    source = tmp_path / "source.mp4"
    video(source)
    common = dict(
        absolute_start_ms=0,
        absolute_end_ms=4000,
        plan=golden_plan(),
        frame_rate=F(30),
        check=lambda: None,
    )
    for limits, hash_value in [
        (LIMITS, "0" * 64),
        (replace(LIMITS, max_video_frames=2), sha(source)),
        (replace(LIMITS, max_output_bytes=100), sha(source)),
    ]:
        with pytest.raises(StageFailure):
            retime_video(
                source, tmp_path / "out.mp4", source_sha256=hash_value, limits=limits, **common
            )
        assert not (tmp_path / "out.mp4").exists()

    def cancel():
        raise RuntimeError("cancel-video")

    with pytest.raises(RuntimeError, match="cancel-video"):
        retime_video(
            source,
            tmp_path / "out.mp4",
            source_sha256=sha(source),
            limits=LIMITS,
            **{**common, "check": cancel},
        )
    assert not list(tmp_path.glob("vt-video-*"))


def test_odd_dimensions_preserved_with_explicit_right_bottom_padding(tmp_path):
    from videotranslate.media.fit_plan import build_plan

    source = tmp_path / "odd.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "nullsrc=s=33x35:r=25,format=rgb24",
            "-t",
            "0.2",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "bgr0",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    result = retime_video(
        source,
        tmp_path / "out.mp4",
        source_sha256=sha(source),
        absolute_start_ms=0,
        absolute_end_ms=200,
        plan=build_plan(200, []),
        frame_rate=F(25),
        limits=LIMITS,
        check=lambda: None,
    )
    assert (result.width, result.height) == (34, 36)
    assert json.loads(result.receipt_json)["odd_padding_right_bottom"] == [1, 1]


@pytest.mark.parametrize(
    "rotation,expected_ids",
    [(0, [0, 1, 2, 3]), (90, [1, 3, 0, 2]), (180, [3, 2, 1, 0]), (270, [2, 0, 3, 1])],
)
def test_phone_display_rotation_preserves_decoded_orientation(tmp_path, rotation, expected_ids):
    from videotranslate.media.fit_plan import build_plan

    colors = [(220, 20, 20), (20, 220, 20), (20, 20, 220), (220, 220, 20)]
    raw = tmp_path / "quadrants.rgb"
    raw.write_bytes(
        b"".join(bytes(colors[(y >= 16) * 2 + (x >= 32)]) for y in range(32) for x in range(64)) * 5
    )
    base = tmp_path / "base.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            "64x32",
            "-framerate",
            "25",
            "-i",
            str(raw),
            "-c:v",
            "libx264",
            "-crf",
            "0",
            "-pix_fmt",
            "yuv444p",
            str(base),
        ],
        check=True,
        timeout=30,
    )
    source = tmp_path / "phone.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-display_rotation:v:0",
            str(rotation),
            "-i",
            str(base),
            "-c",
            "copy",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    before = sha(source)
    result = retime_video(
        source,
        tmp_path / "output.mp4",
        source_sha256=before,
        absolute_start_ms=0,
        absolute_end_ms=200,
        plan=build_plan(200, []),
        frame_rate=F(25),
        limits=LIMITS,
        check=lambda: None,
    )
    width, height = (32, 64) if rotation in (90, 270) else (64, 32)
    assert (result.width, result.height, result.frame_count) == (width, height, 5)
    decoded = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(result.path),
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    assert len(decoded) == width * height * 3
    actual = []
    for x, y in (
        (width // 4, height // 4),
        (3 * width // 4, height // 4),
        (width // 4, 3 * height // 4),
        (3 * width // 4, 3 * height // 4),
    ):
        pixel = decoded[(y * width + x) * 3 : (y * width + x) * 3 + 3]
        distances = [
            sum((a - b) ** 2 for a, b in zip(pixel, color, strict=True)) for color in colors
        ]
        assert min(distances) < 144
        actual.append(distances.index(min(distances)))
    assert actual == expected_ids
    receipt = json.loads(result.receipt_json)
    assert receipt["display_rotation_degrees_ccw"] == rotation
    assert receipt["display_orientation_policy"] == "bake-orthogonal-display-matrix-v1"
    assert receipt["odd_padding_right_bottom"] == [0, 0]
    assert sha(source) == before


def test_arbitrary_display_matrix_fails_explicitly(tmp_path):
    from videotranslate.execution.contracts import StageFailure
    from videotranslate.media.fit_plan import build_plan

    base = tmp_path / "base.mp4"
    video(base)
    source = tmp_path / "angled.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-display_rotation:v:0",
            "45",
            "-i",
            str(base),
            "-c",
            "copy",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    with pytest.raises(StageFailure) as failure:
        retime_video(
            source,
            tmp_path / "out.mp4",
            source_sha256=sha(source),
            absolute_start_ms=0,
            absolute_end_ms=200,
            plan=build_plan(200, []),
            frame_rate=F(25),
            limits=LIMITS,
            check=lambda: None,
        )
    assert failure.value.code.value == "INVALID_MEDIA" and not (tmp_path / "out.mp4").exists()
