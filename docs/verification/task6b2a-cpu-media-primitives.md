# Task 6B2A — actual CPU media primitives

Implementation candidate: `4522da6b92eb7a437947f6a9fba60d8c23f895ed`; initial float primitive GREEN: `1a0afc7`. This increment implements local, measured CPU operations only. It does not establish owned render admission, export/mixing/captions/mux, a provider result, cloned-voice quality, browser acceptance, publishing or deployment. Tasks 6B2B/6C and master 7–9 remain open. Protected runtime, inference, credentials, source/cast/QC domain, routes, schema, worker and object storage were not changed.

## Scope and receipts

Seven finishing modules implement strict limits/types, block float I/O/supervision, isolated offline Rubber Band, fitted voice/common-map audio, target-specific beds and common-map video. Public signatures accept local paths, validated immutable `AudioFile`/`FitPlan`, explicit `RenderLimits` and cancellation/lease `check()`. `retime_audio` and `retime_video` revalidate the exact plan and reject infeasible plans. Source map coordinates remain selection relative; video retains absolute source-window coordinates separately.

Audio results are `FinishedAudio`, a frozen `AudioFile` subclass. Callers obtain bounded structured facts from `result.metadata()["receipt"]`, or parse `result.receipt_json`; `sample_count` and `peak` are measured separately from rounded `duration_ms`. `VideoFile` provides the same receipt access plus measured count/dimensions/codec/container/exact rational frame rate. `metadata()` excludes local paths. Receipts use JSON rational pairs `[numerator, denominator]`, finite numbers and a 65,536-byte limit. There is no natural-voice/QC identity mutation.

Audio facts include the versioned DSP/bed policy, rational planned endpoint, actual samples, peak, zero padding, endpoint/sample rounding, source hashes and (for DSP) original knot count, actual control count and exact original/rounded interpolation-error bounds. Video facts include exact planned endpoint, actual frames, exact frame rate, rational terminal frame padding, absolute selection, common origin, first/tail picture policy, odd pixel padding, control-file size and source SHA.

## Resource and media policy

`RenderLimits` accepts positive actual `int` values only (including rejection of bool/float/string/huge integers). Explicit maxima are 128 GiB per materialized output, 512 GiB aggregate owned temporary files, 86,400 wall seconds, and 3,456,000 video frames (16 hours at 60 fps). These arithmetic ceilings accommodate the planner's 4-hour source/16-hour output domain; they do not promise every configured budget can render its maximum. Tests use 8 MiB output/32 MiB temporary/30 seconds/10,000 frames.

Each operation owns a `TemporaryDirectory` under its destination's filesystem, checks `check()` and the shared operation deadline during block I/O/proof/subprocess polling, supervises aggregate owned temporary bytes plus output bytes, preflights known raw/WAV writes, and kills/reaps its process on every exception. Only owned temporary names are removed. Publication uses an exclusive hard link, so an unrelated destination appearing during rendering is not replaced. No shell or untrusted filter text is used. The legacy `audio.py` 64 MiB defaults remain unchanged; explicit finishing budgets are passed for final validation.

Internal audio is explicit interleaved little-endian IEEE float32, 48,000 Hz, two channels, eight bytes per frame, streamed in 4096-frame blocks with stdlib `array`. Mono explicitly duplicates at unity; stereo explicitly retains both channels at unity. Unsupported layouts/channels fail. Source byte size and SHA are checked before use, probe duration/sample-rate/channel proof is checked, partial/empty/corrupt/nonfinite PCM is rejected, and final float WAV is fully decoded, sample/hash compared and hashed before publication. There is no clamp, gain retry, loudness normalizer or invented instrumental silence. WAV uses RF64 automatically when necessary.

The native helper uses the installed Rubber Band 4.0.0 C API and checks engine 3/allocation. Every used symbol declares both `argtypes` and `restype` against the pinned official `rubberband-c.h` API 3. Offline mode, fixed pitch 1.0, stereo channels together, single-thread processing and 4096-frame blocks are explicit. Expected input duration and overall rounded sample ratio precede the interior-only map. The complete source is studied, rewound, processed and drained to terminal; the state is deleted in `finally`. Coordinates, local/overall dilation, keys, sample counts, finite output, bytes and execution time are bounded. No R2/CLI/model fallback exists. `ctypes.util.find_library` does not find Homebrew's library on this host; the explicit trusted `/opt/homebrew/lib/librubberband.dylib` path resolves the same R3 capability.

`rdp-exact-knot-4ms-v1` is a **DSP-only** exact-Fraction vertical-error RDP policy. A piecewise-linear difference reaches its extrema at original knots, so checking every original knot proves the full interpolation error. The pre-round bound is at most 192 samples (4 ms); rounded controls are independently proved at most 240 samples (5 ms). Sample coordinates/endpoints use global nearest/ties-even rounding, whose signed endpoint error is recorded. Duplicate/zero-distance rounded controls do not reach native code. Genuine authoritative `FitPlan`/video pieces are never rewritten. Dense controls are not blindly forwarded.

Background construction merges included original source intervals first, replaces once, and uses complementary linear fades inside merged edges only. Fades must be 0–100 ms and at most half every merged interval. Both inputs must cover the exact selected sample window. An empty union produces a working-audio bed, not evidence of a dub. The ZH and JA test intervals are passed independently; unrelated/excluded rows and borrowed endpoints do not enter a target's union.

Video uses numeric balanced `if` branches (logarithmic depth, total filter/control cap 1 MiB), common `-copyts -start_at_zero` demuxer timing and absolute trim followed by the exact map. There is one post-map CFR grid, not per-piece concatenation. Allowed rates are 24/25/30/50/60, 24000/1001, 30000/1001 and 60000/1001. Arrival timestamps round down after mapping in 1 µs ticks; `fps:eof_action=pass` retains the final fractional cell. The endpoint is `ceil(planned_seconds × rate)` frames, with strictly less than one frame of endpoint padding. The first selected picture is cloned backwards to grid zero when needed; no picture anywhere in the selection fails. The last selected picture is held through the endpoint. Odd dimensions receive one black pixel on the right/bottom as needed, without resizing source pixels; input dimensions are bounded at 8192 each/33,554,432 pixels. Output is video-only H.264/yuv420p MP4, fully counted and decoded.

## Observed RED → GREEN

All initial media behavior tests were observed failing before their implementation; missing imports were not treated as sufficient RED.

| Behavior | Actual RED | Final GREEN |
| --- | --- | --- |
| Float normalization | Callable stub returned `None`; required materialized measured frames assertion failed; mono and budget/cancel cases failed | Above-unity stereo 1.5 retained, 0.6 mono duplicated at unity, exact bytes/count/SHA, corruption/nonfinite/type/budget/cancel checks |
| Offline warp | Four-second marked source returned `None`, actual DSP output assertion failed | 312,000 frames, all five markers including tail, fixed pitch and unclipped headroom |
| Voice/common-map audio | Derived PCM/common-map output assertions failed on stubs | 2.5 seconds / 1.25 = 96,000 samples; speed 1 retains 120,000; comparison uses shared map |
| Background | Required actual bed assertion failed, short-input case did not raise | Union [1,4] seconds replaces once; overlap interiors have no extra notch; exact target-specific source spans |
| Video | Actual decoded retimed video assertion failed on stub | Real decoded color/picture/clock/grid/offset/VFR/dense-plan tests |
| Corrupt audio proof | Changing proven duration 100 ms→1 ms was incorrectly accepted | Reprobe mismatch rejects before resampling |
| Dense proof cancellation | Callable accepted `check` but did not raise | Periodic cancellation/deadline checks during exact control proof |
| Unbounded local dilation | Million-fold single-sample map incorrectly accepted | Local dilation must be between 1/2 and 4 before native work |
| Missing native output | Successful-exit fault double with valid receipt leaked `FileNotFoundError` | Bounded `INVALID_MEDIA`, no published file, owned cleanup |
| Between-frame last picture | For 1010..3010 ms selection, MP4/MKV offsets 0/5 selected first source frame31 but dropped final source frame90, showing89 instead | Deliberate floor-arrival/EOF-pass policy retains source31 and90, exact60 output frames; all eight rates still meet ceiling endpoints |

The between-frame RED was discovered by replacing weak two-step-red IDs with widely separated 125-color RGB codes. Final tests classify output against **actually decoded source** centroids (squared RGB distance <144; code spacing50), giving no temporal allowance for color classification. Separately, source actual rational PTS are mapped to the global output grid and every output picture is checked within one grid cell for timestamp rescaling/rounding. At the golden integer knots the decoded source choices are 0,30,60,91 and119 (first/1.5/3.5/5.5/final); frame91 at5.5 is the explicitly measured one-cell rounding allowance, not an unmeasured codec-identification allowance. Intermediate/source sampling and frame selection are not sample-exact DSP claims.

## Numerical measurements

Installed FFmpeg/ffprobe: **7.1.1**; Rubber Band: **4.0.0**, R3. Generated fixtures use no model weights, Torch, Transformers, ASR/TTS, database or network. Official C API source pin and licensing context are recorded in [retiming-engine-investigation.md](../engineering/retiming-engine-investigation.md).

Golden source float WAV SHA-256: `43f0cc07ad4b48b9b168e78bd361aa09f784be7a333fd898e8a4931c69083e80`. It contains distinguishable bursts at 400/600/800/1000/1200 Hz in the left channel and corresponding frequencies +100 Hz in the right. Output WAV SHA: `2478a2fafe7a1df602cde118d390931197fc1a3ca49c33c472842ca1de8163b7`. Output peak **2.2891926765** is retained; output count **312,000**, duration6500 ms, padding0. Whole-window tone detection uses 10 ms windows; acceptance is <=60 ms per onset/end and <=1 sample declared length (observed exact counts).

| Frequency | Exact mapped interval (s) | Measured interval (s) | Max onset/end error |
| --- | --- | --- | --- |
| 400 | 0.015–0.225 | 0.01–0.23 | 5 ms |
| 600 | 1.275–1.485 | 1.27–1.49 | 5 ms |
| 800 | 3.20–3.48 | 3.16–3.44 | 40 ms |
| 1000 | 5.20–5.48 | 5.16–5.44 | 40 ms |
| 1200 | 6.35–6.49 | 6.35–6.49 | 0 ms |

The exact golden map retains its five original knots; lossless equal-slope coalescing needs only two interior native controls and has zero interpolation/rounding error. Identity, 4x picture expansion, 0.5x output ratio/voice speed2, continuous 440 Hz pitch, center mono/stereo coherence, distinct channels, silence, natural speed1/1.25, start/tail markers, native-pass cancellation and the original dense counterexample are exercised.

The naive retained dynamic `asetnsamples/asendcmd/atempo` pipeline is executed as a negative fixture and fails the **same <=60 ms tail-position criterion**, not merely total duration. The original alternating 3000 one-millisecond control counterexample and a real 1000-line/3001-piece validated plan with one-millisecond changes and nonuniform gaps both retain all five markers against the exact plan under the independently bounded DSP policy. The alternating fixture produces264,000 samples with one interior DSP control, exact0.5 ms proof bound and observed maximum10 ms marker error; final marker5.36–5.49 seconds. The nonuniform-gap1000-line/3001-piece plan produces288,000 samples with one interior control, exact error bound `191808/3499` samples (about1.142040583 ms), observed maximum20 ms marker error and tail5.87–5.99 seconds. Their receipts and measured marker intervals are retained privately; no tolerance was widened and no tail was trimmed.

Natural 2.5-second voice at speed5/4 produces **96,000 samples**, 2000 ms, peak1.6410589, with source SHA unchanged. Five-second background produces **240,000 samples**, peak1.4, dialogue union1000..4000 ms, and complementary 100 ms inside fades. Golden video source SHA: `8d165bc98a702b94e230d54072c697093da28cf82f8dfbcea90830efcb0dc12e`; output SHA: `f88580dc754de0c9bd43f3705f788782255c5b62cc27138f65657e46d4326f99`, **195 frames at30/1**, 32×32, 6500 ms, endpoint padding0, filter473 bytes. Tests separately execute a 3001-piece expression and all eight CFR choices with fractional/VFR input, MP4/Matroska nonzero origins, delayed-video/common-audio clock, between-frame selection and odd padding. ZH-only/JA-only/both-target maps produce5/6/6 seconds and second-line source onsets4/5/5 seconds.

## Commands and evidence

Source/tests were frozen before the one full backend run. Private evidence is under ignored `var/task6b2a/`; logs/JSON are mode600. `check.py` records exact argv/exit/stdout and owns a `TemporaryDirectory` pytest basetemp with failed-only retention; it removes only that owned directory. `measurements.json` contains actual FFmpeg/helper argv, installed binary/library details and SHA, fixture/output hashes, bounded primitive receipts and numerical marker positions. `dense-measurements.json` retains both dense-map receipts and original/exact marker comparisons. `tail-red-green.json`/`.log` independently reproduce the legacy-up and final-floor/EOF-pass graph with actual FFmpeg for all three offset/container cases, retaining exact argv, hashes and decoded first/final frame IDs without changing frozen source/tests. No private customer source or credentials are in this evidence.

Historical `focused-pre-tail.log` records69 passing tests in48.02s **before** the stricter between-frame tail assertion; it is not the final gate. The observed three tail failures (tool command result `d086f9`, pytest1010..3010 cases) and subsequent floor-only four endpoint-count failures (`a655ff`) remain part of the RED/GREEN account above. The final policy adds explicit EOF-pass behavior and was verified by all17 real video cases passing in17.04s. Final `focused-post-tail.log`: **71 passed in48.31s**, exit0.

```text
PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src:tests .venv/bin/python3.12 var/task6b2a/check.py focused-post-tail tests/test_float_audio.py tests/test_offline_warp.py tests/test_fit_audio.py tests/test_background.py tests/test_fit_video.py -q
VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src:tests .venv/bin/python3.12 var/task6b2a/check.py full-backend -q --tb=short
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/python3.12 -m compileall -q src tests
uv lock --check --offline
git diff --check
```

Static checks passed: Ruff, all172 Python files formatted, compilation, offline lock75 packages, diff whitespace. Actual PostgreSQL uses only fixture-owned databases under the opt-in admin URL; protected retained runtime is not a test database. Full backend process handle `91019` was started once at the frozen candidate and collected to terminal exit0: **1021 passed in950.17s (15m50s)**, with the actual PostgreSQL opt-in and no skips. There was no duplicated full run and no source/test change after freeze. `full-backend.log` retains its exact argv and result. Independent SPEC followed by distinct QUALITY remain external gates; this implementation actor does not issue either gate.
