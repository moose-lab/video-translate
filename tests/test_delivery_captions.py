from fractions import Fraction

from videotranslate.media.fit_plan import build_plan
from videotranslate.media.fit_types import FitLine, FitSettings


def test_caption_shared_map_absolute_selection_is_not_added_and_text_is_escaped(tmp_path):
    from videotranslate.media.delivery_captions import sidecars

    plan = build_plan(
        4000,
        [FitLine("zh", "a", None, 0, 2000, 3000), FitLine("zh", "b", None, 1000, 3000, 4000)],
        FitSettings(mode="smart", max_audio_speed=Fraction(1), max_picture_factor=Fraction(4)),
    )
    cues = [
        dict(
            segment_id="a",
            track_id="zh",
            source_text="source <&>",
            target_text="你好 <&>",
            start_ms=0,
            end_ms=2000,
            included=True,
        ),
        dict(
            segment_id="b",
            track_id="zh",
            source_text="second",
            target_text="第二",
            start_ms=1000,
            end_ms=3000,
            included=True,
        ),
    ]
    results = sidecars(plan, cues, [dict(id="zh", tag="zh")], tmp_path)
    vtt = next(m for tag, format, m in results if tag == "zh" and format == "vtt")
    text = vtt.path.read_text()
    assert "WEBVTT" in text and "zh:a" in text and "你好 &lt;&amp;&gt;" in text
    assert "00:00:00.000 --> 00:00:03.000" in text
    assert "00:00:01.500 --> 00:00:05.500" in text
    assert vtt.metadata()["cue_policy"] == "target_actual_declared_speech_source_mapped_cue_v1"
