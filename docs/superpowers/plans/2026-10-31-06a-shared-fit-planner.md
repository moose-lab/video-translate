# Shared fit planner implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development and test-driven-development. One implementer for this coherent increment, followed by independent SPEC then distinct QUALITY. Implementation is gated on both task5B reviews. The user already approved continuous construction; do not ask for another execution choice. Steps use checkbox syntax.

**Goal:** Build the bounded, deterministic timing planner used by fixed-picture and shared Smart Fit rendering, with explicit unresolved lines and exact common-map coordinates.

**Architecture:** A pure CPU-independent planner consumes measured natural durations and selection-relative source spans. It returns immutable map pieces, per-line placements, explicit borrowing/speed decisions and feasibility issues. Later owned commands capture actual project/audio/readiness proofs and persist this result; later workers render against this exact common map.

**Tech Stack:** Existing Python3.12 standard library dataclasses/Fraction and pytest. No new dependency, SQL schema, provider call, media rendering, route or browser change in6A.

## Scope and actual dependencies

The approved [finishing boundary](../specs/2026-10-30-media-finishing-boundaries.md) and independently calculated [numeric fixtures](../../engineering/media-finishing-numeric-fixtures.md) are the scope authority. Do not copy upstream implementation. Task5B's final inspected interfaces are `dubbing/voice_qc.current_proof`, `output_assessment`, `target_readiness`; task5A supplies `NaturalOutput.duration_ms`, exact audio/output identity and immutable selections. Their gate reports remain separate from this planner.

The planner must not interpret a feasible timeline as accepted audio.6B will bind source selection/current transcript, actual selected targets/output/audio hashes and review readiness under the project lock. No inference identity changes when a derived timing plan changes. Existing `media/timing.py` handles demuxer origin; leave it unchanged. Absolute extraction origin belongs to the later command snapshot. Inputs here are integer milliseconds relative to the selected window.

Subsequent mandatory increments remain:6B owned immutable fit/settings commands and guarded CPU retime/voice/background intermediates;6C explicit gains/peak protection, previews, captions and validated private media exports. Write those execution plans against gated6A interfaces. Task6 does not close until actual FFmpeg waveform/frame/stream/caption and recovery evidence passes. Then durable cross-stage continuation, full workbench and actual paired-language/multi-role acceptance still remain.

## Files and public interface

- Create `src/videotranslate/media/fit_types.py`: frozen typed values, explicit limits and `FitInputError`.
- Create `src/videotranslate/media/fit_plan.py`: input validation, bounded borrowing, common-map construction, mapping, strict verification and canonical JSON projection.
- Create `tests/test_fit_contracts.py` and `tests/test_fit_plan.py`: independent numeric expectations, malformed/limit cases and immutable-plan tampering.
- Create `docs/verification/task6a-fit-planner.md`: observed RED/GREEN, commands, output and remaining render boundaries.

Use these concrete public names and field meanings; do not expose ORM/provider objects:

```python
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

MAX_SOURCE_MS = 14_400_000
MAX_OUTPUT_MS = 57_600_000
MAX_LINES = 1000
FACTOR_PRECISION = 1_000_000


class FitInputError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FitSettings:
    mode: Literal["fixed", "smart"] = "fixed"
    max_audio_speed: Fraction = Fraction(6, 5)
    max_picture_factor: Fraction = Fraction(2)
    max_borrow_ms: int = 0
    max_output_duration_ms: int = MAX_OUTPUT_MS


@dataclass(frozen=True)
class FitLine:
    track_key: str
    segment_key: str
    role_key: str | None
    start_ms: int
    end_ms: int
    natural_duration_ms: int


@dataclass(frozen=True)
class MapPiece:
    source_start_ms: int
    source_end_ms: int
    output_start_ms: Fraction
    output_end_ms: Fraction


@dataclass(frozen=True)
class LinePlacement:
    track_key: str
    segment_key: str
    available_source_end_ms: int
    borrowed_ms: int
    output_start_ms: Fraction
    source_caption_end_ms: Fraction
    required_audio_speed: Fraction
    audio_speed: Fraction | None
    voice_end_ms: Fraction | None


@dataclass(frozen=True)
class FitIssue:
    code: Literal["LINE_FIT_LIMIT", "OUTPUT_DURATION_LIMIT"]
    track_key: str | None = None
    segment_key: str | None = None


@dataclass(frozen=True)
class FitPlan:
    source_duration_ms: int
    settings: FitSettings
    lines: tuple[FitLine, ...]
    pieces: tuple[MapPiece, ...]
    placements: tuple[LinePlacement, ...]
    issues: tuple[FitIssue, ...]

    @property
    def feasible(self) -> bool:
        return not self.issues

    @property
    def output_duration_ms(self) -> Fraction:
        return self.pieces[-1].output_end_ms
```

## Task1: Strict bounded inputs and fixed-picture planning

- [ ] Write numeric fixed-picture tests before adding production modules. They must test final decisions, rather than reproduce the implementation algorithm. The next same-role onset stays3000; borrowed silence is explicit; insufficient speed has no fabricated/truncated voice endpoint.

```python
from fractions import Fraction as F
from videotranslate.media.fit_types import FitLine, FitSettings
from videotranslate.media.fit_plan import build_plan, map_time


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
    plan = build_plan(4000, [line], FitSettings(max_audio_speed=F(6, 5)))
    assert not plan.feasible
    assert [(x.code, x.track_key, x.segment_key) for x in plan.issues] == [
        ("LINE_FIT_LIMIT", "ja", "a")
    ]
    assert plan.placements[0].required_audio_speed == F(5, 4)
    assert plan.placements[0].audio_speed is None
    assert plan.placements[0].voice_end_ms is None
```

- [ ] Run `PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest -q tests/test_fit_plan.py`. Capture feature-missing RED; fix test typos/import mistakes separately and do not count them as feature evidence.
- [ ] Add the frozen types above and validation helpers. Reject unsupported modes; non-exact numeric types including bool/float/NaN/infinity; out-of-window/reversed/empty spans; nonpositive natural duration; duplicate `(track_key, segment_key)`; blank or >128-character keys; >1000lines. Accept only list/tuple line containers and check length before copying; do not consume arbitrary generators. Require strict integer milliseconds, source1..MAX_SOURCE_MS, natural1..MAX_SOURCE_MS, borrowing0..60000, output limit1..MAX_OUTPUT_MS. Rates must be actual `Fraction`, audio1..2, picture1..4, denominator≤1,000,000 and numerator≤4,000,000. Unknown role is `None`, never an inferred label.

The integer/key/rate validation helpers can use this exact policy:

```python
def require_integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise FitInputError("INVALID_FIT_INPUT")


def require_key(value):
    if type(value) is not str or not value.strip() or len(value) > 128:
        raise FitInputError("INVALID_FIT_INPUT")


def require_rate(value, maximum):
    if (
        type(value) is not Fraction
        or not Fraction(1) <= value <= maximum
        or value.denominator > FACTOR_PRECISION
        or value.numerator > 4_000_000
    ):
        raise FitInputError("INVALID_FIT_INPUT")


def validate_inputs(source_duration_ms, lines, settings):
    require_integer(source_duration_ms, 1, MAX_SOURCE_MS)
    if type(lines) not in (list, tuple) or len(lines) > MAX_LINES:
        raise FitInputError("INVALID_FIT_INPUT")
    if type(settings) is not FitSettings or type(settings.mode) is not str:
        raise FitInputError("INVALID_FIT_INPUT")
    if settings.mode not in {"fixed", "smart"}:
        raise FitInputError("INVALID_FIT_INPUT")
    require_rate(settings.max_audio_speed, Fraction(2))
    require_rate(settings.max_picture_factor, Fraction(4))
    require_integer(settings.max_borrow_ms, 0, 60_000)
    require_integer(settings.max_output_duration_ms, 1, MAX_OUTPUT_MS)
    keys = set()
    for line in lines:
        if type(line) is not FitLine:
            raise FitInputError("INVALID_FIT_INPUT")
        require_key(line.track_key)
        require_key(line.segment_key)
        if line.role_key is not None:
            require_key(line.role_key)
        require_integer(line.start_ms, 0, source_duration_ms - 1)
        require_integer(line.end_ms, line.start_ms + 1, source_duration_ms)
        require_integer(line.natural_duration_ms, 1, MAX_SOURCE_MS)
        key = (line.track_key, line.segment_key)
        if key in keys:
            raise FitInputError("INVALID_FIT_INPUT")
        keys.add(key)
    return tuple(sorted(lines, key=lambda x: (x.start_ms, x.end_ms, x.track_key, x.segment_key)))


def borrowed_end(line, lines, source_duration_ms, settings):
    if line.role_key is None or not settings.max_borrow_ms:
        return line.end_ms
    free_end = source_duration_ms
    for other in lines:
        if (other.track_key, other.segment_key) == (line.track_key, line.segment_key):
            continue
        if (other.track_key, other.role_key) != (line.track_key, line.role_key):
            continue
        if other.end_ms > line.end_ms:
            free_end = min(free_end, max(line.end_ms, other.start_ms))
    shortage = max(0, line.natural_duration_ms - (line.end_ms - line.start_ms))
    return line.end_ms + min(settings.max_borrow_ms, free_end - line.end_ms, shortage)
```

- [ ] Implement fixed-picture planning in the common builder described inTask2. Borrow only after a line's original end, at natural speed first, bounded by requested allowance, required extra duration, selected-window tail and the first occupied same-role interval on the same target track. A same-role interval already occupying that boundary permits zero borrowing. Other targets do not consume this track's silence. Different roles may overlap. Unknown role disables borrowing conservatively. Do not move another onset or edit any input line.
- [ ] Add and observe RED/GREEN for tail cap, unknown role, same-role overlap at the borrow boundary, different-role overlap, independent target tracks, short natural speech and explicit1.25 allowed speed. Commit the coherent fixed-path change after GREEN.

## Task2: One deterministic shared Smart Fit map

- [ ] Add the two external numeric fixtures before the Smart path. The common overlap factor is a maximum, not a product, and both targets must share the second onset in a combined plan.

```python
def endpoints(plan):
    return [(p.source_start_ms, p.output_start_ms) for p in plan.pieces] + [
        (plan.source_duration_ms, plan.output_duration_ms)
    ]


def test_shared_overlap_uses_largest_factor_once():
    lines = [
        FitLine("zh", "a", "a", 0, 2000, 3000),
        FitLine("zh", "b", "b", 1000, 3000, 4000),
    ]
    plan = build_plan(4000, lines, FitSettings(mode="smart", max_audio_speed=F(1)))
    assert endpoints(plan) == [(0, 0), (1000, 1500), (2000, 3500), (3000, 5500), (4000, 6500)]
    assert [(p.output_start_ms, p.voice_end_ms) for p in plan.placements] == [(0, 3000), (1500, 5500)]
    assert plan.placements[0].source_caption_end_ms == 3500


def test_two_targets_get_one_map_and_one_second_onset():
    lines = [
        FitLine("zh", "a", "a", 0, 2000, 3000),
        FitLine("zh", "b", "a", 3000, 4000, 1000),
        FitLine("ja", "a", "a", 0, 2000, 4000),
        FitLine("ja", "b", "a", 3000, 4000, 1000),
    ]
    settings = FitSettings(mode="smart", max_audio_speed=F(1))
    combined = build_plan(4000, lines, settings)
    assert combined.output_duration_ms == 6000
    assert {p.output_start_ms for p in combined.placements if p.segment_key == "b"} == {F(5000)}
    assert build_plan(4000, lines[:2], settings).output_duration_ms == 5000
    assert build_plan(4000, list(reversed(lines)), settings) == combined
```

- [ ] Run the new cases and capture proper RED. Implement the shared map and placement functions; use the following complete calculation, with `validate_inputs` and `borrowed_end` implementingTask1's explicit policy. `validate_inputs` returns a canonically ordered tuple by `(start_ms,end_ms,track_key,segment_key)`; no caller-owned collection is mutated.

```python
def picture_factor(required, maximum):
    # Ceil to one part per million, then respect the exact configured cap.
    # This bounds denominator growth across1000 unrelated ratios. All factors
    # use the fixed grid or the one shared cap; golden1.5/2 factors stay exact.
    required = max(Fraction(1), required)
    scaled = required * FACTOR_PRECISION
    rounded = Fraction(-(-scaled.numerator // scaled.denominator), FACTOR_PRECISION)
    return min(maximum, rounded)


def map_pieces(pieces, source_ms):
    for piece in pieces:
        if piece.source_start_ms <= source_ms <= piece.source_end_ms:
            return piece.output_start_ms + (
                Fraction(source_ms - piece.source_start_ms, piece.source_end_ms - piece.source_start_ms)
                * (piece.output_end_ms - piece.output_start_ms)
            )
    raise FitInputError("INVALID_FIT_TIME")


def build_plan(source_duration_ms, lines, settings=FitSettings()):
    lines = validate_inputs(source_duration_ms, lines, settings)
    ends = {(x.track_key, x.segment_key): borrowed_end(x, lines, source_duration_ms, settings) for x in lines}
    boundaries = sorted({0, source_duration_ms, *(x.start_ms for x in lines), *(x.end_ms for x in lines), *ends.values()})
    factors = {
        (x.track_key, x.segment_key): picture_factor(
            Fraction(x.natural_duration_ms, ends[(x.track_key, x.segment_key)] - x.start_ms),
            settings.max_picture_factor,
        )
        for x in lines
    }
    pieces, output = [], Fraction(0)
    for left, right in zip(boundaries, boundaries[1:]):
        factor = Fraction(1)
        if settings.mode == "smart":
            factor = max(
                [factor]
                + [factors[(x.track_key, x.segment_key)] for x in lines
                   if x.start_ms < right and ends[(x.track_key, x.segment_key)] > left]
            )
        end = output + (right - left) * factor
        pieces.append(MapPiece(left, right, output, end))
        output = end
    pieces = tuple(pieces)
    placements, issues = [], []
    for line in lines:
        available_end = ends[(line.track_key, line.segment_key)]
        start = map_pieces(pieces, line.start_ms)
        capacity = map_pieces(pieces, available_end) - start
        required = max(Fraction(1), Fraction(line.natural_duration_ms) / capacity)
        speed = required if required <= settings.max_audio_speed else None
        if speed is None:
            issues.append(FitIssue("LINE_FIT_LIMIT", line.track_key, line.segment_key))
        placements.append(LinePlacement(
            line.track_key, line.segment_key, available_end, available_end - line.end_ms,
            start, map_pieces(pieces, line.end_ms), required, speed,
            None if speed is None else start + Fraction(line.natural_duration_ms) / speed,
        ))
    if output > settings.max_output_duration_ms:
        issues.append(FitIssue("OUTPUT_DURATION_LIMIT"))
    return FitPlan(source_duration_ms, settings, lines, pieces, tuple(placements), tuple(issues))


def map_time(plan, source_ms):
    if type(source_ms) is not int or not 0 <= source_ms <= plan.source_duration_ms:
        raise FitInputError("INVALID_FIT_TIME")
    return map_pieces(plan.pieces, source_ms)
```

Smart policy is explicit: borrow requested silence first; preserve natural voice speed by extending local picture up to its configured cap; use bounded speed only for the remaining required duration. Overlap from any included role/target may give a line extra capacity, but never forces a short voice to fill it. The minimum audio speed is1; slower/shorter audio keeps its natural end. An unresolved line has no fitted speed/endpoint and cannot be silently rendered. A feasible original-only empty-line plan is an identity map, not proof of a dub.

- [ ] Add RED/GREEN for preroll/gaps/tail, identical boundaries, three-role overlap, rational limits such as4/3, awkward relatively prime source spans, picture cap+remaining audio speed, global output-duration limit and deterministic line ordering. Verify source coverage/strictly positive rates/continuity/endpoints for bounded generated combinations; expected outcomes must not merely call the same helper under test. Commit after GREEN.

## Task3: Strict immutable verification and JSON coordinates

- [ ] Add tests that mutate copied plan values with `dataclasses.replace`: a gap, backwards/zero-rate piece, changed output endpoint, wrong placement, missing line and an int→equal-valued float/bool substitution. Every case must be rejected. Equality alone is insufficient because Python considers some float/int/Fraction/bool values equal.
- [ ] Implement `validate_plan(plan) -> None`: require actual declared frozen types and tuple collections, strict int fields and actual Fraction fields (or allowedNone) throughout, then reconstruct with `build_plan(plan.source_duration_ms, plan.lines, plan.settings)` and require exact structural agreement. Malformed structure/type raises `FitInputError("INVALID_FIT_PLAN")`; validly typed but different derived values raise `FitInputError("FIT_PLAN_MISMATCH")`. No I/O, clocks, ORM or model access. Do not trust deserialized rates merely because JSON parsing succeeded.

Use this exact rational projection in `plan_json(plan)`, after strict validation, so later persistence does not depend on float rounding:

```python
def rational_json(value):
    if type(value) is not Fraction:
        raise FitInputError("INVALID_FIT_PLAN")
    return {"numerator": value.numerator, "denominator": value.denominator}
```

The full JSON object must contain policy`shared_fit_v1`, source/output duration, immutable settings, ordered input lines, all map pieces, all placements and issues, with Fraction values represented only by `rational_json`; optional unresolved fields staynull. `feasible` is derived, not a forged acceptance flag. Use explicit field projection, not arbitrary object serialization. No JSON parser/HTTP API is added in6A;6B will validate the stored typed contract before reuse.

- [ ] Test exact golden coordinates in JSON, deterministic input-order-independent JSON, no float values anywhere, null unresolved speed/end, stable line coverage and bounded size at1000lines. Verify over-limit input rejects before quadratic work. Commit after GREEN.

## Task4: Verification, evidence and gates

- [ ] Run focused new tests plus actual existing media boundaries:

```sh
PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest -q --tb=short tests/test_fit_contracts.py tests/test_fit_plan.py tests/test_probe.py tests/test_multistem_audio.py tests/test_analysis_media.py tests/test_whisper_timing_quantization.py
```

Use an owned `TemporaryDirectory` basetemp and failed-only retention; clean only that directory. These pure unregistered modules do not change any old execution/provider/DB contract, so do not repeat the13-minute full backend solely for arithmetic/docs. If implementation unexpectedly touches a shared integration surface, stop scope growth, explain why and run the checks that new dependency requires. No frontend checks are needed without frontend changes.

- [ ] Run `.venv/bin/ruff check src tests`, `.venv/bin/ruff format --check src tests`, `.venv/bin/python3.12 -m compileall -q src tests`, `uv lock --check --offline`, `git diff --check`. Retain actual commands/stdout/exit codes privately outsideGit, redact no secret because none is used. Write the verification note with exact completed outcomes and explain that map arithmetic is not measured rendering, background replacement, export readiness or live model acceptance.
- [ ] Self-review against each boundary/fixture and the stated limits, commit exact scoped files, leave worktree clean, return DONE or concrete concerns. The controller independently dispatches SPEC then distinct QUALITY; the author cannot self-issue either gate. Only after both pass may6B implementation begin. No remote model call, protected preview/schema mutation, push or deployment is part of6A.
