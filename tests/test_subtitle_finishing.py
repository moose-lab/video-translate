"""Real libass output, literal text and explicit font coverage failures."""

import json
import subprocess

import pytest
from test_float_audio import LIMITS


def test_ass_preserves_literal_dialogue_and_records_centisecond_rounding(tmp_path):
    from videotranslate.media.subtitle_finishing import ass_file

    cues = [dict(id="a", start_ms=501, end_ms=1101, text=r"你好 {\pos(1,1)}\N world")]
    result = ass_file(cues, tmp_path / "captions.ass", width=640, height=360, family="Arial")
    text = result.path.read_text()
    assert "0:00:00.50,0:00:01.11" in text
    assert r"\{" in text and r"\}" in text
    assert "\\\u2060N" in text and "{\\pos" not in text
    assert result.metadata()["cue_count"] == 1
    assert result.metadata()["clock_policy"] == "outward_centisecond_v1"


def test_font_preflight_uses_real_glyph_coverage_and_rejects_missing(tmp_path):
    from videotranslate.media.float_audio import Budget
    from videotranslate.media.subtitle_fonts import FontCoverageError, select_fonts

    budget = Budget(LIMITS, lambda: None, tmp_path)
    fonts = select_fonts("Hello 你好 مرحبا שלום", profile="auto", budget=budget)
    assert fonts and all(len(font.sha256) == 64 for font in fonts)
    assert all("/" not in font.facts()["family"] for font in fonts)
    with pytest.raises(FontCoverageError) as caught:
        select_fonts("Hello\U0010ffff", profile="auto", budget=budget)
    assert caught.value.code == "FONT_GLYPHS_MISSING"
    assert caught.value.missing == ("U+10FFFF",)


def test_real_cjk_rtl_burn_in_keeps_frame_grid_and_literal_tags_at_bottom(tmp_path):
    from videotranslate.media.float_audio import Budget
    from videotranslate.media.subtitle_finishing import burn_in
    from videotranslate.media.subtitle_fonts import select_fonts

    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=640x360:r=30:d=1.5",
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
    text = "你好 · Hello\nمرحبا بالعالم 123 · שלום " + r"{\pos(1,1)}\N"
    fonts = select_fonts(text, profile="auto", budget=budget)
    result = burn_in(
        source,
        [dict(id="a", start_ms=500, end_ms=1300, text=text)],
        tmp_path / "captioned.mp4",
        fonts=fonts,
        width=640,
        height=360,
        budget=budget,
    )
    data = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.8",
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
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout
    assert len(data) == 640 * 360 * 3
    assert max(data[: 640 * 120 * 3]) < 30, "Dialogue must not execute a top-left position tag"
    assert sum(value > 180 for value in data[640 * 220 * 3 :]) > 500
    facts = result.metadata()
    assert facts["frame_count"] == 45 and facts["width"] == 640 and facts["height"] == 360
    assert facts["fonts"] and facts["cue_count"] == 1
    assert facts["source_video_sha256"] != facts["sha256"]
    info = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(result.path)],
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
    )
    assert info["streams"][0]["avg_frame_rate"] == "30/1"
