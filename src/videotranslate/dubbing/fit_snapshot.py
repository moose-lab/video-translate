"""Bounded strict shared_fit_v1 decoding and captured-row equality, outside SQL."""

from dataclasses import fields
from fractions import Fraction

from ..media.fit_plan import plan_json, validate_plan
from ..media.fit_types import FitIssue, FitLine, FitPlan, LinePlacement, MapPiece
from .fit_contracts import POLICY, FitSettingsBody

PLAN_LIMIT = 2 * 1024 * 1024
OPERATION_LIMIT = PLAN_LIMIT + 64 * 1024


def exact(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError("Invalid stored fit schema")


def integer(value):
    if type(value) is not int:
        raise ValueError("Invalid stored fit integer")
    return value


def rational(value, *, nullable=False):
    if nullable and value is None:
        return None
    exact(value, ("numerator", "denominator"))
    n, d = integer(value["numerator"]), integer(value["denominator"])
    if d <= 0:
        raise ValueError("Invalid stored fit fraction")
    result = Fraction(n, d)
    if result.numerator != n or result.denominator != d:
        raise ValueError("Noncanonical stored fit fraction")
    return result


def key(value, *, nullable=False):
    if nullable and value is None:
        return None
    if type(value) is not str or not 1 <= len(value) <= 36:
        raise ValueError("Invalid stored fit key")
    return value


def sequence(value, maximum):
    if type(value) is not list or len(value) > maximum:
        raise ValueError("Invalid stored fit collection")
    return value


def decode(data):
    from .fit_plans import json_size

    if json_size(data) > PLAN_LIMIT:
        raise ValueError("Stored fit plan exceeds limit")
    exact(
        data,
        (
            "policy",
            "source_duration_ms",
            "output_duration_ms",
            "settings",
            "lines",
            "pieces",
            "placements",
            "issues",
            "feasible",
        ),
    )
    if data["policy"] != POLICY or type(data["feasible"]) is not bool:
        raise ValueError("Invalid stored fit policy")
    settings = FitSettingsBody.model_validate(data["settings"]).pure()
    lines = []
    for r in sequence(data["lines"], 1000):
        exact(r, (f.name for f in fields(FitLine)))
        lines.append(
            FitLine(
                key(r["track_key"]),
                key(r["segment_key"]),
                key(r["role_key"], nullable=True),
                integer(r["start_ms"]),
                integer(r["end_ms"]),
                integer(r["natural_duration_ms"]),
            )
        )
    pieces = []
    for r in sequence(data["pieces"], 4001):
        exact(r, (f.name for f in fields(MapPiece)))
        pieces.append(
            MapPiece(
                integer(r["source_start_ms"]),
                integer(r["source_end_ms"]),
                rational(r["output_start_ms"]),
                rational(r["output_end_ms"]),
            )
        )
    placements = []
    for r in sequence(data["placements"], 1000):
        exact(r, (f.name for f in fields(LinePlacement)))
        placements.append(
            LinePlacement(
                key(r["track_key"]),
                key(r["segment_key"]),
                integer(r["available_source_end_ms"]),
                integer(r["borrowed_ms"]),
                rational(r["output_start_ms"]),
                rational(r["source_caption_end_ms"]),
                rational(r["required_audio_speed"]),
                rational(r["audio_speed"], nullable=True),
                rational(r["voice_end_ms"], nullable=True),
            )
        )
    issues = []
    for r in sequence(data["issues"], 1001):
        exact(r, (f.name for f in fields(FitIssue)))
        if r["code"] not in {"LINE_FIT_LIMIT", "OUTPUT_DURATION_LIMIT"}:
            raise ValueError("Invalid fit issue")
        issues.append(
            FitIssue(
                r["code"], key(r["track_key"], nullable=True), key(r["segment_key"], nullable=True)
            )
        )
    plan = FitPlan(
        integer(data["source_duration_ms"]),
        settings,
        tuple(lines),
        tuple(pieces),
        tuple(placements),
        tuple(issues),
    )
    validate_plan(plan)
    if rational(data["output_duration_ms"]) != plan.output_duration_ms or plan_json(plan) != data:
        raise ValueError("Noncanonical fit projection")
    return plan


def validate_stored(data, snapshot, rows):
    plan = decode(data)
    if (
        snapshot["policy"] != POLICY
        or plan.source_duration_ms != snapshot["end_ms"] - snapshot["start_ms"]
        or plan.settings != FitSettingsBody.model_validate(snapshot["settings"]).pure()
    ):
        raise ValueError("Fit source/settings mismatch")
    expected = {
        (r["track_id"], r["segment_id"]): FitLine(
            r["track_id"],
            r["segment_id"],
            r["role_id"],
            r["start_ms"],
            r["end_ms"],
            r["natural_duration_ms"],
        )
        for r in rows
        if r["included"]
    }
    if (
        len(expected) != sum(r["included"] for r in rows)
        or {(r.track_key, r.segment_key): r for r in plan.lines} != expected
        or len(plan.lines) != len(expected)
    ):
        raise ValueError("Fit captured cell mismatch")
    return plan
