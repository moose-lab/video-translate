# Actual CPU media primitives implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development and test-driven-development. Start one fresh implementer only after 6B1 independent SPEC and distinct QUALITY both pass. Then obtain this increment's own SPEC and distinct QUALITY gates. Continuous execution is authorized; do not ask for another execution choice. Checkboxes track actual work, not design intent.

**Goal:** Turn the gated common fit map into measured local video, original-comparison audio, fitted natural line audio and target-specific source-preserving background beds.

**Architecture:** Focused CPU functions accept validated local files and an immutable `FitPlan`; they have no database, network, model or object-storage access. FFmpeg performs demuxing, conversion, video retime/encode and full decode. A bounded isolated offline DSP helper handles variable audio time warping without implicit gain or clipping. The subsequent 6B2B increment binds these functions to owned commands and the existing Worker/Operations/PreparedObject lifecycle. 6C adds explicit mixing, protection, captions, mux and exports.

**Tech Stack:** Existing Python 3.12 standard library, FFmpeg/FFprobe and system Rubber Band 4.0.0 C API. No Python inference/runtime dependency or model weights. No new lifecycle, schema or route in this increment. The approved CPU worker architecture permits these media operations; HyperFrames/HTML animation does not replace the source-preserving pipeline.

## Actual inputs, research and boundaries

- Gated 6A `media/fit_types.py` and `fit_plan.py`: exact Fraction map, 1000 lines, up to 3001 partitions, factor bounds, null endpoints for infeasible lines. Call `validate_plan` before work and reject infeasible plans explicitly. Do not reinterpret its arithmetic or change natural output identity.
- Existing `media/audio.py`: `AudioFile`, `run_process`, `inspect`, `validate_audio`, `extract_audio`. Its default 64 MiB bound remains unchanged. Explicit new render budgets may be larger; a new caller must not silently relax legacy limits.
- `media/timing.py::timeline_bounds` defines the common demuxer origin. Source-window times are absolute relative to that origin; fit times are selection-relative. Do not reset away a delayed stream's position using its own first PTS.
- `models/analysis.py::AnalysisMedia` supplies owned working/instrumental assets later. This primitive layer only receives files. Future 6B2B must capture their exact selection, producer, hashes and current lineage; 6B1 does not already contain those bed inputs.
- Read [finishing boundaries](../specs/2026-10-30-media-finishing-boundaries.md), [numeric fixtures](../../engineering/media-finishing-numeric-fixtures.md) and [measured engine investigation](../../engineering/retiming-engine-investigation.md). The controller's naive `asendcmd`/`atempo` experiment is a retained negative example: it decoded, but the last marker was roughly 120 ms early. Padding total length would not fix it.
- Rubber Band CLI default behavior and `--ignore-clipping` both alter above-unity samples. Do not use that CLI as an unprotected float intermediate. The pinned C API prototype retains headroom and exact total samples for one fixture; it is not production code or broad acceptance. Reimplement a small typed, bounded helper against the official header. Do not copy the upstream application's implementation.

## Files and public primitive interface

Create these focused modules, keeping existing execution/source/synthesis/QC files untouched:

- `media/finishing_types.py`: strict frozen render limits, local video proof, numerical reports and public-safe error codes. Reuse `AudioFile` rather than introduce a second audio object model.
- `media/float_audio.py`: bounded interleaved float conversion, finite/peak/sample inspection and block iteration; no whole-film memory read.
- `media/offline_warp.py`: parent-side helper supervision and canonical sample keyframe generation from exact Fraction coordinates.
- `media/offline_warp_runner.py`: isolated native C API process, two-pass block processing, typed signatures, explicit engine/version/options and guaranteed native-state release.
- `media/fit_audio.py`: fit one natural file using its declared speed and retime a full comparison/bed through the common map.
- `media/background.py`: merge target-specific source dialogue intervals, complementary crossfade weights and float bed construction before common retime.
- `media/fit_video.py`: bounded balanced common-map expression, explicit origin/window/frame grid, FFmpeg video-only MP4 generation and complete validation.
- `tests/media_fixtures.py`: small deterministic generated audio and numbered/color source frames. No checked-in large binary or inference double masquerading as real media.
- `tests/test_float_audio.py`, `test_offline_warp.py`, `test_fit_audio.py`, `test_background.py`, `test_fit_video.py`.
- `docs/verification/task6b2a-cpu-media-primitives.md`.

The named interfaces are:

```python
@dataclass(frozen=True)
class RenderLimits:
    max_output_bytes: int
    max_temporary_bytes: int
    max_wall_seconds: int
    max_video_frames: int

# AudioFile includes the previously measured path, duration, byte size and SHA.
# Every materialized input is rechecked against its declared hash before use.
def fit_voice(natural: AudioFile, destination: Path, *, speed: Fraction,
              limits: RenderLimits, check: Callable[[], None]) -> AudioFile: ...

def build_background(working: AudioFile, instrumental: AudioFile,
                     destination: Path, *, source_duration_ms: int,
                     dialogue_intervals: tuple[tuple[int, int], ...],
                     crossfade_ms: int, limits: RenderLimits,
                     check: Callable[[], None]) -> AudioFile: ...

def retime_audio(audio: AudioFile, plan: FitPlan, destination: Path, *,
                 limits: RenderLimits, check: Callable[[], None]) -> AudioFile: ...

def retime_video(source: Path, destination: Path, *, source_sha256: str,
                 absolute_start_ms: int, absolute_end_ms: int,
                 plan: FitPlan, frame_rate: Fraction,
                 limits: RenderLimits, check: Callable[[], None]) -> VideoFile: ...
```

These signatures define the intended functions, not placeholder implementation bodies. Define `VideoFile` with path, SHA, byte size, actual duration, codec/container, dimensions, exact frame rate and measured frame count; its metadata omits the server path. Add explicit report fields for policy, planned rational duration, actual sample/frame counts, peak and padding/rounding. Metadata returned to later owned execution must remain bounded plain JSON. Limits require positive actual integers, explicit upper bounds compatible with the existing 4-hour source/16-hour arithmetic maxima, and checked resource estimates before files are written. Arithmetic maxima do not assert that every configured worker budget can render the largest case.

## Task 1: Bounded float input/output and numerical fixtures

- [ ] Write a feature RED for above-unity finite stereo PCM preserving its peak through the internal format, exact sample counts, expected SHA mismatch rejection, NaN/Inf rejection and cancellation cleanup. An import error is not the completed behavioral RED; record a minimal missing-behavior assertion after the callable exists.
- [ ] Normalize local validated mono/stereo audio to 48 kHz stereo float PCM with FFmpeg, preserving explicit source alignment. Mono must duplicate its waveform at unity into both channels through an explicit channel matrix; do not silently inherit an equal-power rematrix gain. Stereo retains each channel at unity. Unsupported layouts require an explicit visible policy, not an implicit downmix. Test 0.6 mono impulses remain 0.6 in each output channel and retain the input SHA. Use standard-library block I/O and `array`/`struct`; do not load an entire track into memory or clamp values to [-1,1]. Internal raw format and frame-byte count are explicit. The output WAV is float PCM, fully decoded and hashed before return.
- [ ] Keep existing `run_process` defaults compatible. If supervising the DSP helper needs stderr/stdout or aggregate temporary-size observation, add a narrow optional capability or a finishing-specific wrapper; retain bounded files, periodic `check()`, wall deadline, kill and reap on every exception. Do not introduce shell execution or forward untrusted strings into a filter.
- [ ] Add strict limit/type tests including bool, float, string, huge integer, partial frame bytes, empty file and corrupted input proof. Demonstrate budget rejection before an oversized allocation/write. Commit the GREEN primitive and fixtures.

## Task 2: Offline pitch-preserving audio warp

- [ ] Write RED using the four-second marked audio and exact common map from the numeric fixtures. Assert 312,000 output frames at 48 kHz, all five tone bursts including the final marker, bounded individual onset/end error and unchanged dominant frequencies. The controller's naive dynamic pipeline must fail the same positional criterion; never accept only total length or generated command text.
- [ ] Generate the source→target sample control map from exact rational coordinates using one declared global rounding rule. The authoritative plan retains every genuine slope change. Identity maps can copy/convert while retaining a receipt. Interior keyframes and a separately computed overall output/input sample ratio are required; no zero-distance or duplicate rounded sample pairs reach the native API. The controller's direct 3000-control R3 experiment lost its final marker despite exact length, while its R2 attempt ignored controls. Do not blindly forward all dense controls or hide those outcomes. A DSP-only control approximation may compact knots if an explicit versioned policy proves maximum interpolation error at every original knot of at most 5 ms, separately accounts for sample rounding, reports the actual bound and passes the same end-marker/pitch/position tests. Use exact Fraction comparisons for that proof; the exact fit map and video map never change. If the contract cannot be met, report the concrete failure to the controller rather than silently widening limits or dropping the tail.
- [ ] Implement the isolated native process against the pinned `rubberband-c.h`: declare every `argtypes`/`restype`, check allocation and engine 3, fixed pitch 1.0, offline mode, explicit channel policy and bounded block size. Set expected input length and global ratio before the map. Study the complete input in bounded blocks, rewind, process all input, drain/retrieve to terminal and release state in `finally`. Bound keyframes, u32 sample coordinates, output count, finite samples, bytes and time. No fallback to another engine on capability or processing failure.
- [ ] Preserve float values above unity. Do not reuse the CLI's sample clamp or gain retry. Record actual peak for 6C protection. Native process failure, unsupported library, timeout/cancel, malformed helper receipt, wrong output length, truncated source and nonfinite samples fail with bounded codes and no completed output. Parent deletes only its owned temporary paths.
- [ ] Test constant 1x, maximum picture factor 4, natural voice speed 1..2, silence, stereo center/mono compatibility, distinct channel markers, beginning/end markers and a continuous pitch fixture. Start with a measured onset/end tolerance of 60 ms for DSP and 1 sample for declared output length; tighten when supported, and report any requirement that cannot meet these criteria instead of silently widening tolerances.
- [ ] Exercise a real dense map within the full 1000-line/3001-piece bound, including one-millisecond changes and nonuniform gaps. Measure markers against the exact shared map. Use small generated duration/resolution; do not allocate multi-hour fixtures. Cancellation tests must run during both study and process. Commit GREEN and retain actual process receipts.

## Task 3: Fitted voices and target-specific source-preserving beds

- [ ] Write RED for natural voice speed 1.25 turning a 2.5-second marked voice into 2 seconds while preserving pitch and its final marker. Verify the source file/SHA remains unchanged. Speed 1 leaves the natural duration intact rather than stretching to fill a larger picture slot. Actual derived duration is measured separately from planned placement.
- [ ] Implement `fit_voice` through the verified offline primitive with constant time ratio `1/speed`. Preserve all input speech; no arbitrary `atrim` of an overlong result. A failed length/tail check is a visible error. Keep derived output metadata and actual samples separate from natural output/QC identities.
- [ ] Write RED for source duration 5 seconds, dialogue intervals [1,3] and [2,4], distinctive working-dialogue and instrumental markers. Merge intervals to [1,4] first. Outside the union use the working track; in the crossfade-free interior use the instrumental once. Bound `crossfade_ms` to 0..100 and to half each merged interval. Crossfades sit inside union boundaries with complementary linear weights; there is no repeated attenuation or crossfade at 2 or 3.
- [ ] Implement blockwise float background construction. Both input durations/sample counts must cover the same exact selected source window. No automatic normalization or clamping. Reject gaps/mismatched SHA/measurement instead of padding missing instrumental with invented silence. Empty dialogue union is a working-audio bed and does not prove a dub.
- [ ] Test ZH/JA incomplete-preview inputs with different included rows: each bed uses its own included original source spans, never the union of all target tracks, borrowed silence endpoint or unrelated excluded rows. Then retime each bed through the same plan as video/original comparison. Assert actual markers, no overlap notch and unchanged natural inputs. Commit GREEN.

## Task 4: One common video map with explicit frame policy

- [ ] Write RED using numbered/color source frames for the overlap map, including head, internal gaps and last source frame. Verify the common map points and monotonic source coverage from decoded output frames, not just duration/FFprobe. Separately test the ZH-only 5-second map, JA-only 6-second map and both-target 6-second map; both-target second-line onsets are 5 seconds.
- [ ] Compile a bounded balanced piecewise expression over source-relative timestamps, rather than a deep linear `if` chain or one filter branch per row. An exact plan of 3001 pieces must be supported without exceeding a declared 1 MiB filter/control-file limit. Generate numeric syntax only; no dialogue, source filename or caller expression enters the graph. Larger plans already reject at 6A's boundary.
- [ ] Use the actual common demuxer origin and absolute selection. Preserve delayed video/audio relation; do not substitute per-stream `STARTPTS` for the common clock. Document initial missing-picture policy and explicit tail-frame padding; the comparison audio must use the same source window. A source with no video in the selection fails visibly.
- [ ] Support a declared exact CFR output choice from 24,25,30,50,60,24000/1001,30000/1001,60000/1001. Normalize fractional/VFR sources explicitly, after mapped timestamps, on one global frame grid. Avoid per-partition rounding/concatenation drift. Fully decode the resulting video-only H.264/yuv420p MP4, record actual frame count/duration and any less-than-one-frame terminal padding. Preserve source aspect/pixels; odd-dimension padding and any dimension/byte/frame cap must be explicit and tested.
- [ ] Test MP4/Matroska nonzero origins, delayed audio, selected windows starting between frames, fractional rates and VFR; continuity/last marker and declared frame tolerances apply. Add actual dense-map execution with a tiny source and parser/control-file bound tests. Input hashes remain unchanged. No subtitles or alternate audio mux in this increment. Commit GREEN.

## Task 5: Verification, evidence and gates

- [ ] Run meaningful CPU tests with actual binaries/library and complete decodes. Missing runtime capabilities are reported, not skipped as a passing finishing gate. Test doubles are reserved for fault/budget boundaries and labelled accordingly. Record tool/library version, numerical tolerances, generated fixture SHA, command options, measurements and cancellation/failure behavior.
- [ ] Keep each runner's temporary directory owned and remove it after completion; failed-only pytest retention avoids disk accumulation. Never clean unrelated task files. Run focused suites, full backend after source/tests freeze, Ruff/format/compile/offline lock/diff checks, then commit evidence. Do not rerun a confirmed-live full process merely because a tool observation expired.
- [ ] Obtain fresh independent SPEC review and subsequent distinct QUALITY review. Original actor fixes findings with RED/GREEN and the same reviewer rechecks. Only after both pass may 6B2B bind these functions to owned source/bed/natural assets and prepared media publication.

This closes CPU primitives only. It does not claim current owned render admission, a mixed export, captions, cloud deployment, real cloned-voice quality, browser workbench or the paired-language/multirole acceptance. The original 6B2/6C and master 6–9 obligations remain intact.

The subsequent owned integration preparation is [6B2B boundaries](../specs/2026-11-01-owned-media-render-boundaries.md). It records actual fit/analysis/prepared-object source contracts, manifest identity, cache bounds and publication/recovery requirements; it is not implementation or permission to begin6B2B before this increment's two gates.
