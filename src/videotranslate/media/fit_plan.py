"""Pure shared timing policy; no media processing or readiness decision."""

from fractions import Fraction

from videotranslate.media.fit_types import FitIssue, FitPlan, FitSettings, LinePlacement, MapPiece

_DEFAULT_SETTINGS = FitSettings()


def build_plan(source_duration_ms, lines, settings=_DEFAULT_SETTINGS):
    ordered = tuple(sorted(lines, key=lambda x: (x.start_ms, x.end_ms, x.track_key, x.segment_key)))
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
    pieces = tuple(
        MapPiece(left, right, Fraction(left), Fraction(right))
        for left, right in zip(boundaries, boundaries[1:], strict=False)
    )
    placements, issues = [], []
    for line, end in zip(ordered, available, strict=True):
        start = Fraction(line.start_ms)
        required = max(Fraction(1), Fraction(line.natural_duration_ms, end - line.start_ms))
        speed = required if required <= settings.max_audio_speed else None
        placements.append(
            LinePlacement(
                line.track_key,
                line.segment_key,
                end,
                end - line.end_ms,
                start,
                Fraction(line.end_ms),
                required,
                speed,
                start + line.natural_duration_ms / speed if speed is not None else None,
            )
        )
        if speed is None:
            issues.append(FitIssue("LINE_FIT_LIMIT", line.track_key, line.segment_key))
    return FitPlan(source_duration_ms, settings, ordered, pieces, tuple(placements), tuple(issues))


def map_time(plan, source_ms):
    for piece in plan.pieces:
        if piece.source_start_ms <= source_ms <= piece.source_end_ms:
            return piece.output_start_ms + (source_ms - piece.source_start_ms) * (
                piece.output_end_ms - piece.output_start_ms
            ) / (piece.source_end_ms - piece.source_start_ms)
    raise ValueError("Outside map")
