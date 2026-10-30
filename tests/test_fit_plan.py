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


def smart(**kwargs):
    return FitSettings(mode="smart", max_audio_speed=F(1), **kwargs)


def test_smart_golden_overlap_uses_maximum_once_and_separates_caption():
    plan = build_plan(
        4000,
        [FitLine("zh", "a", "r", 0, 2000, 3000), FitLine("zh", "b", "s", 1000, 3000, 4000)],
        smart(),
    )
    assert [map_time(plan, t) for t in [0, 1000, 2000, 3000, 4000]] == [
        F(0),
        F(1500),
        F(3500),
        F(5500),
        F(6500),
    ]
    a, b = plan.placements
    assert (a.output_start_ms, a.voice_end_ms, a.source_caption_end_ms) == (F(0), F(3000), F(3500))
    assert (b.output_start_ms, b.voice_end_ms) == (F(1500), F(5500))
    assert plan.feasible


def test_shared_targets_have_one_common_map_and_stable_order():
    zh = [FitLine("zh", "a", "r", 0, 2000, 3000), FitLine("zh", "b", "r", 3000, 4000, 1000)]
    ja = [FitLine("ja", "a", "r", 0, 2000, 4000), FitLine("ja", "b", "r", 3000, 4000, 1000)]
    z, j, both = [build_plan(4000, rows, smart()) for rows in [zh, ja, zh + ja]]
    assert (z.output_duration_ms, z.placements[1].output_start_ms) == (F(5000), F(4000))
    assert (j.output_duration_ms, j.placements[1].output_start_ms) == (F(6000), F(5000))
    assert both.output_duration_ms == F(6000)
    assert [p.output_start_ms for p in both.placements if p.segment_key == "b"] == [
        F(5000),
        F(5000),
    ]
    assert both == build_plan(4000, list(reversed(zh + ja)), smart())


def test_preroll_gaps_tail_coincident_and_three_overlapping_roles():
    plan = build_plan(
        6000,
        [
            FitLine("zh", "a", "r", 1000, 2000, 1500),
            FitLine("zh", "b", "s", 1000, 2000, 2000),
            FitLine("ja", "c", "t", 1000, 2000, 1700),
            FitLine("ja", "d", "t", 4000, 5000, 1500),
        ],
        smart(),
    )
    assert [map_time(plan, t) for t in range(0, 6001, 1000)] == list(
        map(F, [0, 1000, 3000, 4000, 5000, 6500, 7500])
    )
    assert len(plan.pieces) == 5


def test_exact_rational_cap_then_bounded_audio_speed_and_output_limit():
    plan = build_plan(
        3000,
        [FitLine("zh", "a", "r", 0, 2000, 3000)],
        FitSettings(mode="smart", max_picture_factor=F(4, 3), max_output_duration_ms=3600),
    )
    placement = plan.placements[0]
    assert plan.output_duration_ms == F(11000, 3)
    assert (placement.required_audio_speed, placement.audio_speed, placement.voice_end_ms) == (
        F(9, 8),
        F(9, 8),
        F(8000, 3),
    )
    assert [(i.code, i.track_key, i.segment_key) for i in plan.issues] == [
        ("OUTPUT_DURATION_LIMIT", None, None)
    ]
    unresolved = build_plan(
        2000,
        [FitLine("zh", "a", "r", 0, 2000, 6000)],
        smart(max_picture_factor=F(2), max_output_duration_ms=3999),
    )
    assert [i.code for i in unresolved.issues] == ["LINE_FIT_LIMIT", "OUTPUT_DURATION_LIMIT"]
    assert unresolved.placements[0].voice_end_ms is None


def test_borrow_precedes_picture_and_only_required_shortage_is_borrowed():
    plan = build_plan(4000, [FitLine("zh", "a", "r", 0, 2000, 3000)], smart(max_borrow_ms=500))
    assert plan.placements[0].borrowed_ms == 500
    assert map_time(plan, 2500) == F(3000)
    assert plan.output_duration_ms == F(4500)


def test_awkward_ratios_round_up_to_fixed_ppm_grid():
    lines = [
        FitLine("zh", str(i), "r", i * 100, i * 100 + width, width + 1)
        for i, width in enumerate([7, 11, 13, 17, 19, 23])
    ]
    plan = build_plan(600, lines, smart())
    # Six disjoint spans each gain the rounded-up excess over one source millisecond.
    expected = F(600) + sum(
        (F(((width + 1) * 1_000_000 + width - 1) // width, 1_000_000) - 1) * width
        for width in [7, 11, 13, 17, 19, 23]
    )
    assert plan.output_duration_ms == expected
    assert all(p.output_end_ms.denominator <= 1_000_000 for p in plan.pieces)
    assert plan.feasible


def test_generated_overlap_combinations_have_measurable_duration_and_coverage():
    from itertools import product

    for demands in product([100, 150, 200, 300], repeat=3):
        lines = [FitLine(str(i), "a", "r", 100, 200, n) for i, n in enumerate(demands)]
        plan = build_plan(400, lines, FitSettings(mode="smart", max_audio_speed=F(2)))
        factor = min(F(2), F(max(demands), 100))
        assert plan.output_duration_ms == 300 + 100 * factor
        assert plan.pieces[0].source_start_ms == 0
        assert plan.pieces[-1].source_end_ms == 400
        for left, right in zip(plan.pieces, plan.pieces[1:], strict=False):
            assert left.source_end_ms == right.source_start_ms
            assert left.output_end_ms == right.output_start_ms
        for piece in plan.pieces:
            assert piece.source_end_ms > piece.source_start_ms
            assert piece.output_end_ms > piece.output_start_ms
        for placement, natural in zip(plan.placements, demands, strict=True):
            assert placement.audio_speed == max(F(1), F(natural, 100) / factor)
