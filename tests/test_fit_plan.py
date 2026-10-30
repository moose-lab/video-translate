"""Exact numeric policy examples; no rendered-media acceptance claims."""

from fractions import Fraction as F

from videotranslate.media.fit_plan import build_plan, map_time
from videotranslate.media.fit_types import FitLine, FitSettings


def test_fixed_borrows_silence_before_speed_and_preserves_next_onset():
    lines = [
        FitLine("zh", "a", "speaker-a", 0, 2000, 2500),
        FitLine("zh", "b", "speaker-a", 3000, 4000, 1000),
    ]
    plan = build_plan(4000, lines, FitSettings(max_borrow_ms=500))
    assert plan.feasible
    first, second = plan.placements
    assert (first.borrowed_ms, first.audio_speed, first.voice_end_ms) == (500, F(1), F(2500))
    assert second.output_start_ms == 3000
    assert map_time(plan, 4000) == 4000


def test_fixed_insufficient_speed_is_a_specific_unresolved_line():
    line = FitLine("ja", "a", "speaker-a", 0, 2000, 2500)
    plan = build_plan(4000, [line])
    assert not plan.feasible
    assert [(x.code, x.track_key, x.segment_key) for x in plan.issues] == [
        ("LINE_FIT_LIMIT", "ja", "a")
    ]
    assert plan.placements[0].required_audio_speed == F(5, 4)
    assert plan.placements[0].audio_speed is None
    assert plan.placements[0].voice_end_ms is None
    allowed = build_plan(4000, [line], FitSettings(max_audio_speed=F(5, 4)))
    assert allowed.feasible
    assert allowed.placements[0].voice_end_ms == 2000


def test_fixed_borrowing_respects_tail_occupancy_role_and_target():
    cases = [
        ([], "r", 3900, 100),
        ([FitLine("zh", "b", "r", 2400, 3500, 100)], "r", 2000, 400),
        ([FitLine("zh", "b", "r", 1500, 3500, 100)], "r", 2000, 0),
        ([FitLine("zh", "b", "other", 1500, 3500, 100)], "r", 2000, 1000),
        ([FitLine("ja", "b", "r", 1500, 3500, 100)], "r", 2000, 1000),
        ([], None, 2000, 0),
    ]
    for others, role, end, expected in cases:
        line = FitLine("zh", "a", role, end - 1000, end, 2000)
        plan = build_plan(4000, [line, *others], FitSettings(max_borrow_ms=5000))
        placement = next(p for p in plan.placements if p.segment_key == "a")
        assert placement.borrowed_ms == expected
        assert placement.available_source_end_ms == end + expected


def test_short_natural_voice_stays_at_normal_rate_and_empty_is_identity():
    plan = build_plan(4000, [FitLine("zh", "a", "r", 1000, 3000, 500)])
    voice = plan.placements[0]
    assert (voice.audio_speed, voice.voice_end_ms, voice.source_caption_end_ms) == (
        F(1),
        F(1500),
        F(3000),
    )
    empty = build_plan(4000, [])
    assert empty.feasible and empty.output_duration_ms == F(4000)
    assert empty.lines == empty.placements == empty.issues == ()
    assert [(p.source_start_ms, p.source_end_ms) for p in empty.pieces] == [(0, 4000)]
