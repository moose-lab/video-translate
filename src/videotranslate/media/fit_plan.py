"""Pure shared timing policy; no media processing or readiness decision."""

from fractions import Fraction

from videotranslate.media.fit_types import (
    FACTOR_PRECISION,
    MAX_LINES,
    MAX_OUTPUT_MS,
    MAX_SOURCE_MS,
    FitInputError,
    FitIssue,
    FitLine,
    FitPlan,
    FitSettings,
    LinePlacement,
    MapPiece,
)

_DEFAULT_SETTINGS = FitSettings()


def build_plan(
    source_duration_ms: int,
    lines: list[FitLine] | tuple[FitLine, ...],
    settings: FitSettings = _DEFAULT_SETTINGS,
) -> FitPlan:
    ordered = _validate_inputs(source_duration_ms, lines, settings)
    available = []
    for line in ordered:
        free_end = source_duration_ms
        if line.role_key is not None:
            for other in ordered:
                if (
                    (other.track_key, other.role_key) == (line.track_key, line.role_key)
                    and other != line
                    and other.end_ms > line.end_ms
                ):
                    free_end = min(free_end, max(line.end_ms, other.start_ms))
            borrowed = min(
                settings.max_borrow_ms,
                free_end - line.end_ms,
                max(0, line.natural_duration_ms - (line.end_ms - line.start_ms)),
            )
        else:
            borrowed = 0
        available.append(line.end_ms + borrowed)
    boundaries = sorted(
        {
            0,
            source_duration_ms,
            *(line.start_ms for line in ordered),
            *(line.end_ms for line in ordered),
            *available,
        }
    )
    factors = []
    for line, end in zip(ordered, available, strict=True):
        required = max(Fraction(1), Fraction(line.natural_duration_ms, end - line.start_ms))
        rounded = Fraction(
            (required.numerator * FACTOR_PRECISION + required.denominator - 1)
            // required.denominator,
            FACTOR_PRECISION,
        )
        factors.append(
            min(rounded, settings.max_picture_factor) if settings.mode == "smart" else Fraction(1)
        )
    pieces = []
    output = Fraction(0)
    for left, right in zip(boundaries, boundaries[1:], strict=False):
        factor = max(
            (
                factor
                for line, end, factor in zip(ordered, available, factors, strict=True)
                if line.start_ms < right and end > left
            ),
            default=Fraction(1),
        )
        next_output = output + (right - left) * factor
        pieces.append(MapPiece(left, right, output, next_output))
        output = next_output
    pieces = tuple(pieces)
    placements, issues = [], []
    for line, end in zip(ordered, available, strict=True):
        start = _map_pieces(pieces, line.start_ms)
        capacity = _map_pieces(pieces, end) - start
        required = max(Fraction(1), line.natural_duration_ms / capacity)
        speed = required if required <= settings.max_audio_speed else None
        placements.append(
            LinePlacement(
                line.track_key,
                line.segment_key,
                end,
                end - line.end_ms,
                start,
                _map_pieces(pieces, line.end_ms),
                required,
                speed,
                start + line.natural_duration_ms / speed if speed is not None else None,
            )
        )
        if speed is None:
            issues.append(FitIssue("LINE_FIT_LIMIT", line.track_key, line.segment_key))
    if output > settings.max_output_duration_ms:
        issues.append(FitIssue("OUTPUT_DURATION_LIMIT"))
    return FitPlan(source_duration_ms, settings, ordered, pieces, tuple(placements), tuple(issues))


def map_time(plan: FitPlan, source_ms: int) -> Fraction:
    if type(source_ms) is not int or not 0 <= source_ms <= plan.source_duration_ms:
        raise FitInputError("INVALID_FIT_TIME")
    return _map_pieces(plan.pieces, source_ms)


def _map_pieces(pieces, source_ms):
    for piece in pieces:
        if piece.source_start_ms <= source_ms <= piece.source_end_ms:
            return piece.output_start_ms + (source_ms - piece.source_start_ms) * (
                piece.output_end_ms - piece.output_start_ms
            ) / (piece.source_end_ms - piece.source_start_ms)
    raise FitInputError("INVALID_FIT_TIME")


def _require_integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise FitInputError("INVALID_FIT_INPUT")


def _require_key(value):
    if type(value) is not str or not value.strip() or len(value) > 128:
        raise FitInputError("INVALID_FIT_INPUT")


def _require_rate(value, maximum):
    if (
        type(value) is not Fraction
        or not 1 <= value <= maximum
        or value.denominator > FACTOR_PRECISION
        or value.numerator > 4_000_000
    ):
        raise FitInputError("INVALID_FIT_INPUT")


def _validate_inputs(source_duration_ms, lines, settings):
    _require_integer(source_duration_ms, 1, MAX_SOURCE_MS)
    if type(lines) not in (list, tuple) or len(lines) > MAX_LINES:
        raise FitInputError("INVALID_FIT_INPUT")
    if (
        type(settings) is not FitSettings
        or type(settings.mode) is not str
        or settings.mode not in {"fixed", "smart"}
    ):
        raise FitInputError("INVALID_FIT_INPUT")
    _require_rate(settings.max_audio_speed, Fraction(2))
    _require_rate(settings.max_picture_factor, Fraction(4))
    _require_integer(settings.max_borrow_ms, 0, 60000)
    _require_integer(settings.max_output_duration_ms, 1, MAX_OUTPUT_MS)
    keys = set()
    for line in lines:
        if type(line) is not FitLine:
            raise FitInputError("INVALID_FIT_INPUT")
        _require_key(line.track_key)
        _require_key(line.segment_key)
        if line.role_key is not None:
            _require_key(line.role_key)
        _require_integer(line.start_ms, 0, source_duration_ms)
        _require_integer(line.end_ms, line.start_ms + 1, source_duration_ms)
        _require_integer(line.natural_duration_ms, 1, MAX_SOURCE_MS)
        key = (line.track_key, line.segment_key)
        if key in keys:
            raise FitInputError("INVALID_FIT_INPUT")
        keys.add(key)
    return tuple(sorted(lines, key=lambda x: (x.start_ms, x.end_ms, x.track_key, x.segment_key)))


def _require_rational(value, *, optional=False):
    if optional and value is None:
        return
    if type(value) is not Fraction or value < 0:
        raise FitInputError("INVALID_FIT_PLAN")


def _require_tuple(value, maximum):
    if type(value) is not tuple or len(value) > maximum:
        raise FitInputError("INVALID_FIT_PLAN")


def _validate_plan_structure(plan):
    if type(plan) is not FitPlan:
        raise FitInputError("INVALID_FIT_PLAN")
    _require_tuple(plan.lines, MAX_LINES)
    _require_tuple(plan.pieces, 3 * MAX_LINES + 1)
    _require_tuple(plan.placements, MAX_LINES)
    _require_tuple(plan.issues, MAX_LINES + 1)
    _validate_inputs(plan.source_duration_ms, plan.lines, plan.settings)
    if not plan.pieces:
        raise FitInputError("INVALID_FIT_PLAN")
    source_cursor, output_cursor = 0, Fraction(0)
    for piece in plan.pieces:
        if type(piece) is not MapPiece:
            raise FitInputError("INVALID_FIT_PLAN")
        _require_integer(piece.source_start_ms, 0, plan.source_duration_ms)
        _require_integer(piece.source_end_ms, piece.source_start_ms + 1, plan.source_duration_ms)
        _require_rational(piece.output_start_ms)
        _require_rational(piece.output_end_ms)
        if (
            piece.source_start_ms != source_cursor
            or piece.output_start_ms != output_cursor
            or piece.output_end_ms <= piece.output_start_ms
        ):
            raise FitInputError("INVALID_FIT_PLAN")
        source_cursor, output_cursor = piece.source_end_ms, piece.output_end_ms
    if source_cursor != plan.source_duration_ms:
        raise FitInputError("INVALID_FIT_PLAN")
    for placement in plan.placements:
        if type(placement) is not LinePlacement:
            raise FitInputError("INVALID_FIT_PLAN")
        _require_key(placement.track_key)
        _require_key(placement.segment_key)
        _require_integer(placement.available_source_end_ms, 1, plan.source_duration_ms)
        _require_integer(placement.borrowed_ms, 0, 60000)
        _require_rational(placement.output_start_ms)
        _require_rational(placement.source_caption_end_ms)
        _require_rational(placement.required_audio_speed)
        _require_rational(placement.audio_speed, optional=True)
        _require_rational(placement.voice_end_ms, optional=True)
    for issue in plan.issues:
        if type(issue) is not FitIssue or type(issue.code) is not str:
            raise FitInputError("INVALID_FIT_PLAN")
        if issue.code == "LINE_FIT_LIMIT":
            _require_key(issue.track_key)
            _require_key(issue.segment_key)
        elif (
            issue.code != "OUTPUT_DURATION_LIMIT"
            or issue.track_key is not None
            or issue.segment_key is not None
        ):
            raise FitInputError("INVALID_FIT_PLAN")


def validate_plan(plan: FitPlan) -> None:
    """Check exact types/coverage, then recompute all policy decisions independently.

    Malformed structure cannot hide behind Python's equal-valued bool/int/float
    comparisons. Well-typed but altered derived values have a distinct error.
    """
    try:
        _validate_plan_structure(plan)
    except (FitInputError, AttributeError, TypeError, ValueError):
        raise FitInputError("INVALID_FIT_PLAN") from None
    expected = build_plan(plan.source_duration_ms, plan.lines, plan.settings)
    if plan != expected:
        raise FitInputError("FIT_PLAN_MISMATCH")


def _fraction_json(value: Fraction | None) -> dict | None:
    return (
        None if value is None else {"numerator": value.numerator, "denominator": value.denominator}
    )


def plan_json(plan: FitPlan) -> dict:
    """Explicit versioned projection, validated before producing reusable data."""
    validate_plan(plan)
    return {
        "policy": "shared_fit_v1",
        "source_duration_ms": plan.source_duration_ms,
        "output_duration_ms": _fraction_json(plan.output_duration_ms),
        "settings": {
            "mode": plan.settings.mode,
            "max_audio_speed": _fraction_json(plan.settings.max_audio_speed),
            "max_picture_factor": _fraction_json(plan.settings.max_picture_factor),
            "max_borrow_ms": plan.settings.max_borrow_ms,
            "max_output_duration_ms": plan.settings.max_output_duration_ms,
        },
        "lines": [
            {
                "track_key": line.track_key,
                "segment_key": line.segment_key,
                "role_key": line.role_key,
                "start_ms": line.start_ms,
                "end_ms": line.end_ms,
                "natural_duration_ms": line.natural_duration_ms,
            }
            for line in plan.lines
        ],
        "pieces": [
            {
                "source_start_ms": piece.source_start_ms,
                "source_end_ms": piece.source_end_ms,
                "output_start_ms": _fraction_json(piece.output_start_ms),
                "output_end_ms": _fraction_json(piece.output_end_ms),
            }
            for piece in plan.pieces
        ],
        "placements": [
            {
                "track_key": placement.track_key,
                "segment_key": placement.segment_key,
                "available_source_end_ms": placement.available_source_end_ms,
                "borrowed_ms": placement.borrowed_ms,
                "output_start_ms": _fraction_json(placement.output_start_ms),
                "source_caption_end_ms": _fraction_json(placement.source_caption_end_ms),
                "required_audio_speed": _fraction_json(placement.required_audio_speed),
                "audio_speed": _fraction_json(placement.audio_speed),
                "voice_end_ms": _fraction_json(placement.voice_end_ms),
            }
            for placement in plan.placements
        ],
        "issues": [
            {"code": issue.code, "track_key": issue.track_key, "segment_key": issue.segment_key}
            for issue in plan.issues
        ],
        "feasible": plan.feasible,
    }
