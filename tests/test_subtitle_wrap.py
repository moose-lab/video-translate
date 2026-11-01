"""Actual long CJK line wrapping retains complete text inside safe frame bounds."""

import subprocess

from test_float_audio import LIMITS


def test_long_cjk_wraps_inside_safe_edges_and_preserves_complete_text(tmp_path):
    from videotranslate.media.float_audio import Budget
    from videotranslate.media.subtitle_finishing import burn_in
    from videotranslate.media.subtitle_fonts import select_fonts

    source = tmp_path / "black.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=640x360:r=25:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    text = "你好世界欢迎使用字幕自动换行" * 8
    budget = Budget(LIMITS, lambda: None, tmp_path)
    fonts = select_fonts(text, budget=budget)
    pixels = []
    for name, content in [
        ("automatic", text),
        ("reference", "\n".join(text[i : i + 28] for i in range(0, len(text), 28))),
    ]:
        movie = burn_in(
            source,
            [dict(id="long-current", start_ms=0, end_ms=1000, text=content)],
            tmp_path / (name + ".mp4"),
            fonts=fonts,
            width=640,
            height=360,
            font_size=36,
            budget=budget,
        )
        pixels.append(
            subprocess.check_output(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    "0.5",
                    "-i",
                    str(movie.path),
                    "-frames:v",
                    "1",
                    "-pix_fmt",
                    "gray",
                    "-f",
                    "rawvideo",
                    "-",
                ],
                timeout=30,
            )
        )
        assert movie.facts["frame_count"] == 25
    white = [(i % 640, i // 640) for i, value in enumerate(pixels[0]) if value > 180]
    assert min(x for x, y in white) >= 8 and max(x for x, y in white) < 632, (
        "CJK text clips at horizontal edges"
    )
    assert max(y for x, y in white) - min(y for x, y in white) > 40, (
        "Long CJK dialogue did not form multiple lines"
    )
    reference_count = sum(value > 180 for value in pixels[1])
    assert len(white) >= reference_count * 0.9, (
        "Automatic wrapping lost visible text compared with complete manual-line reference"
    )


def test_exit_zero_libass_without_unicode_feature_is_rejected_before_full_burn(
    tmp_path, monkeypatch
):
    import pytest

    from videotranslate.execution.contracts import StageFailure
    from videotranslate.media.float_audio import Budget
    from videotranslate.media.subtitle_finishing import burn_in
    from videotranslate.media.subtitle_fonts import select_fonts

    source = tmp_path / "black.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=64x64:r=5:d=0.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    budget = Budget(LIMITS, lambda: None, tmp_path)
    fonts = select_fonts("Hello", budget=budget)
    real_run = budget.run

    def lacks_libunibreak(args, **kwargs):
        if kwargs.get("capture_diagnostics"):
            return b"[Parsed_subtitles] libass wasn't built with ASS_FEATURE_WRAP_UNICODE support\n"
        return real_run(args, **kwargs)

    monkeypatch.setattr(budget, "run", lacks_libunibreak)
    with pytest.raises(StageFailure) as caught:
        burn_in(
            source,
            [dict(id="current", start_ms=0, end_ms=200, text="Hello")],
            tmp_path / "rejected.mp4",
            fonts=fonts,
            width=64,
            height=64,
            budget=budget,
        )
    assert caught.value.code.value == "CONFIGURATION"
    assert not (tmp_path / "rejected.mp4").exists()
    assert budget.reserved_bytes == 0 and not list(tmp_path.glob("vt-subs-*"))
