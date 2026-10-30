"""Strict immutable inputs and independently verified canonical plan contracts."""

import json
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction as F

import pytest

from videotranslate.media import fit_plan
from videotranslate.media.fit_types import (
    FACTOR_PRECISION,
    MAX_LINES,
    MAX_OUTPUT_MS,
    MAX_SOURCE_MS,
    FitInputError,
    FitIssue,
    FitLine,
    FitSettings,
    LinePlacement,
    MapPiece,
)

LINE = FitLine("zh", "a", "r", 0, 2000, 2500)


def rejected(code, fn):
    with pytest.raises(FitInputError) as caught:
        fn()
    assert caught.value.code == str(caught.value) == code


@pytest.mark.parametrize(
    "source",
    [
        True,
        False,
        0,
        -1,
        MAX_SOURCE_MS + 1,
        4000.0,
        F(4000),
        float("nan"),
        float("inf"),
        "4000",
        None,
    ],
)
def test_source_requires_bounded_actual_integer(source):
    rejected("INVALID_FIT_INPUT", lambda: fit_plan.build_plan(source, []))


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "other"),
        ("mode", True),
        ("mode", None),
        ("max_audio_speed", 1),
        ("max_audio_speed", 1.2),
        ("max_audio_speed", True),
        ("max_audio_speed", float("nan")),
        ("max_audio_speed", float("inf")),
        ("max_audio_speed", F(0)),
        ("max_audio_speed", F(2000001, 1000000)),
        ("max_audio_speed", F(1000002, 1000001)),
        ("max_picture_factor", F(5)),
        ("max_picture_factor", F(4000001, 1000000)),
        ("max_picture_factor", F(1, 2)),
        ("max_borrow_ms", -1),
        ("max_borrow_ms", 60001),
        ("max_borrow_ms", True),
        ("max_borrow_ms", 0.0),
        ("max_output_duration_ms", 0),
        ("max_output_duration_ms", MAX_OUTPUT_MS + 1),
        ("max_output_duration_ms", True),
    ],
)
def test_settings_are_strict_and_bounded(field, value):
    rejected(
        "INVALID_FIT_INPUT",
        lambda: fit_plan.build_plan(4000, [LINE], replace(FitSettings(), **{field: value})),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("track_key", ""),
        ("track_key", "  "),
        ("track_key", "x" * 129),
        ("track_key", 1),
        ("segment_key", None),
        ("role_key", ""),
        ("role_key", False),
        ("role_key", "x" * 129),
        ("start_ms", -1),
        ("start_ms", True),
        ("start_ms", 0.0),
        ("start_ms", F(0)),
        ("end_ms", 0),
        ("end_ms", 4001),
        ("end_ms", float("nan")),
        ("end_ms", F(2000)),
        ("natural_duration_ms", 0),
        ("natural_duration_ms", -1),
        ("natural_duration_ms", MAX_SOURCE_MS + 1),
        ("natural_duration_ms", True),
        ("natural_duration_ms", float("inf")),
        ("natural_duration_ms", 2500.0),
    ],
)
def test_line_fields_are_strict_and_bounded(field, value):
    rejected(
        "INVALID_FIT_INPUT", lambda: fit_plan.build_plan(4000, [replace(LINE, **{field: value})])
    )


def test_rejects_containers_duplicates_subclasses_and_foreign_values_without_consuming():
    def forbidden():
        raise AssertionError("generator consumed")
        yield LINE

    class Lines(list):
        pass

    class Settings(FitSettings):
        pass

    class Line(FitLine):
        pass

    for lines in [
        forbidden(),
        {LINE},
        {"a": LINE},
        None,
        Lines([LINE]),
        [object()],
        [LINE] * 1001,
        [LINE, LINE],
        [Line("zh", "a", "r", 0, 2000, 2500)],
    ]:
        rejected("INVALID_FIT_INPUT", lambda lines=lines: fit_plan.build_plan(4000, lines))
    for settings in [None, {}, Settings()]:
        rejected(
            "INVALID_FIT_INPUT",
            lambda settings=settings: fit_plan.build_plan(4000, [LINE], settings),
        )


@pytest.mark.parametrize(
    "time", [True, False, -1, 4001, 1.0, F(1), float("nan"), float("inf"), "1", None]
)
def test_map_time_rejects_invalid_time_with_only_bounded_code(time):
    plan = fit_plan.build_plan(4000, [])
    rejected("INVALID_FIT_TIME", lambda: fit_plan.map_time(plan, time))


def test_exact_limits_normalization_immutability_and_bounded_error_code():
    assert (MAX_SOURCE_MS, MAX_OUTPUT_MS, MAX_LINES, FACTOR_PRECISION) == (
        14_400_000,
        57_600_000,
        1000,
        1_000_000,
    )
    first = FitLine("z" * 128, "b", None, 1000, 2000, MAX_SOURCE_MS)
    rows = [first, FitLine("a", "a", "r", 0, 100, 1)]
    before = rows.copy()
    plan = fit_plan.build_plan(
        MAX_SOURCE_MS,
        rows,
        FitSettings(max_audio_speed=F(2), max_picture_factor=F(4), max_borrow_ms=60000),
    )
    assert rows == before and plan.lines == tuple(reversed(before))
    for value in [
        FitSettings(),
        LINE,
        MapPiece(0, 1, F(0), F(1)),
        LinePlacement("a", "a", 1, 0, F(0), F(1), F(1), None, None),
        FitIssue("LINE_FIT_LIMIT"),
        plan,
    ]:
        with pytest.raises(FrozenInstanceError):
            value.extra = 1
    for value in ["unbounded private payload", None, [], True]:
        assert str(FitInputError(value)) == "INVALID_FIT_INPUT"


def valid_plan():
    return fit_plan.build_plan(4000, [LINE])


@pytest.mark.parametrize(
    "change",
    [
        lambda p: replace(p, pieces=list(p.pieces)),
        lambda p: replace(p, placements=list(p.placements)),
        lambda p: replace(p, lines=list(p.lines)),
        lambda p: replace(p, issues=list(p.issues)),
        lambda p: replace(p, source_duration_ms=4000.0),
        lambda p: replace(p, source_duration_ms=True),
        lambda p: replace(p, settings=replace(p.settings, max_audio_speed=1.2)),
        lambda p: replace(p, lines=(replace(LINE, start_ms=False),)),
        lambda p: replace(p, pieces=(replace(p.pieces[0], output_start_ms=0.0), *p.pieces[1:])),
        lambda p: replace(p, pieces=(replace(p.pieces[0], output_start_ms=False), *p.pieces[1:])),
        lambda p: replace(p, pieces=(replace(p.pieces[0], source_start_ms=0.0), *p.pieces[1:])),
        lambda p: replace(p, placements=(replace(p.placements[0], borrowed_ms=False),)),
        lambda p: replace(p, placements=(replace(p.placements[0], required_audio_speed=1.25),)),
        lambda p: replace(p, pieces=()),
        lambda p: replace(p, pieces=(replace(p.pieces[0], source_end_ms=0), *p.pieces[1:])),
        lambda p: replace(p, pieces=(replace(p.pieces[0], source_end_ms=1999), *p.pieces[1:])),
        lambda p: replace(p, pieces=(replace(p.pieces[0], output_end_ms=F(-1)), *p.pieces[1:])),
        lambda p: replace(p, issues=(FitIssue("other"),)),
    ],
)
def test_malformed_plan_structure_rejected(change):
    rejected("INVALID_FIT_PLAN", lambda: fit_plan.validate_plan(change(valid_plan())))


@pytest.mark.parametrize(
    "change",
    [
        lambda p: replace(p, placements=()),
        lambda p: replace(p, lines=()),
        lambda p: replace(p, placements=(replace(p.placements[0], source_caption_end_ms=F(1999)),)),
        lambda p: replace(
            p, placements=(replace(p.placements[0], audio_speed=F(5, 4), voice_end_ms=F(2000)),)
        ),
        lambda p: replace(p, issues=()),
        lambda p: replace(
            p, pieces=(MapPiece(0, 2000, F(0), F(3000)), MapPiece(2000, 4000, F(3000), F(5000)))
        ),
    ],
)
def test_typed_but_different_derived_plan_rejected(change):
    rejected("FIT_PLAN_MISMATCH", lambda: fit_plan.validate_plan(change(valid_plan())))


def test_plan_validation_requires_declared_types_and_every_rational_field():
    rejected("INVALID_FIT_PLAN", lambda: fit_plan.validate_plan({}))
    plan = fit_plan.build_plan(4000, [LINE], FitSettings(max_audio_speed=F(5, 4)))
    fit_plan.validate_plan(plan)
    for field in [
        "output_start_ms",
        "source_caption_end_ms",
        "required_audio_speed",
        "audio_speed",
        "voice_end_ms",
    ]:
        value = getattr(plan.placements[0], field)
        for masquerade in [float(value), int(value)]:
            bad = replace(plan, placements=(replace(plan.placements[0], **{field: masquerade}),))
            rejected("INVALID_FIT_PLAN", lambda bad=bad: fit_plan.validate_plan(bad))
    for field in ["output_start_ms", "output_end_ms"]:
        for masquerade in [
            float(getattr(plan.pieces[0], field)),
            int(getattr(plan.pieces[0], field)),
        ]:
            bad = replace(
                plan, pieces=(replace(plan.pieces[0], **{field: masquerade}), *plan.pieces[1:])
            )
            rejected("INVALID_FIT_PLAN", lambda bad=bad: fit_plan.validate_plan(bad))


def test_json_projects_exact_fractions_nulls_and_stable_identity():
    plan = valid_plan()
    result = fit_plan.plan_json(plan)

    def rational(n, d=1):
        return {"numerator": n, "denominator": d}

    assert result == {
        "policy": "shared_fit_v1",
        "source_duration_ms": 4000,
        "output_duration_ms": rational(4000),
        "settings": {
            "mode": "fixed",
            "max_audio_speed": rational(6, 5),
            "max_picture_factor": rational(2),
            "max_borrow_ms": 0,
            "max_output_duration_ms": MAX_OUTPUT_MS,
        },
        "lines": [
            {
                "track_key": "zh",
                "segment_key": "a",
                "role_key": "r",
                "start_ms": 0,
                "end_ms": 2000,
                "natural_duration_ms": 2500,
            }
        ],
        "pieces": [
            {
                "source_start_ms": 0,
                "source_end_ms": 2000,
                "output_start_ms": rational(0),
                "output_end_ms": rational(2000),
            },
            {
                "source_start_ms": 2000,
                "source_end_ms": 4000,
                "output_start_ms": rational(2000),
                "output_end_ms": rational(4000),
            },
        ],
        "placements": [
            {
                "track_key": "zh",
                "segment_key": "a",
                "available_source_end_ms": 2000,
                "borrowed_ms": 0,
                "output_start_ms": rational(0),
                "source_caption_end_ms": rational(2000),
                "required_audio_speed": rational(5, 4),
                "audio_speed": None,
                "voice_end_ms": None,
            }
        ],
        "issues": [{"code": "LINE_FIT_LIMIT", "track_key": "zh", "segment_key": "a"}],
        "feasible": False,
    }
    assert "null" in json.dumps(result, allow_nan=False)

    def no_float(value):
        assert type(value) is not float
        if type(value) is dict:
            for item in value.values():
                no_float(item)
        if type(value) is list:
            for item in value:
                no_float(item)

    no_float(result)
    rejected("FIT_PLAN_MISMATCH", lambda: fit_plan.plan_json(replace(plan, issues=())))


def test_thousand_lines_have_bounded_map_and_stable_json():
    lines = [FitLine("zh", str(i), "r", 10 * i + 1, 10 * i + 8, 11) for i in range(1000)]
    before = list(lines)
    plan = fit_plan.build_plan(10000, lines, FitSettings(mode="smart"))
    fit_plan.validate_plan(plan)
    assert lines == before
    assert len(plan.lines) == len(plan.placements) == 1000
    assert len(plan.pieces) <= 3 * 1000 + 1
    assert plan.output_duration_ms == F(14_000_003, 1000)
    assert fit_plan.plan_json(plan) == fit_plan.plan_json(
        fit_plan.build_plan(10000, tuple(reversed(lines)), FitSettings(mode="smart"))
    )
    assert len(json.dumps(fit_plan.plan_json(plan))) < 1_000_000
