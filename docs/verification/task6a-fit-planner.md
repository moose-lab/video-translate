# Task 6A: pure shared fit planner verification

Date: 2026-10-31. Scope: bounded timing arithmetic only. Independent SPEC and
QUALITY review are controller-owned and were not issued by this implementation.

## Implemented contract

`media/fit_types.py` defines the frozen public values and bounded error codes.
`media/fit_plan.py` validates exact integer/Fraction/key/container types, orders
immutable inputs, borrows only available same-role/same-target silence, and
constructs one continuous shared source-to-output map. Smart Fit applies the
maximum active picture factor once, rounded upward to the 1 ppm grid or the
exact configured cap. Fixed picture remains identity. Preroll, gaps and tail are
retained. Caption and actual voice endpoints are separate.

Insufficient residual audio speed produces an inspectable `LINE_FIT_LIMIT` with
null speed/voice end; excess total output produces `OUTPUT_DURATION_LIMIT`.
`validate_plan` checks exact declared types and map structure before rebuilding
all derived values. `plan_json` validates first and explicitly projects the
versioned `shared_fit_v1` policy, with rational numerator/denominator objects.

No existing production module was edited. In particular, demux-origin
`media/timing.py`, routes, schema, providers, inference and protected preview
were untouched. No dependency was added.

## Observed RED / GREEN

Full command/stdout/exit records are private mode-0600 files outside Git under
`outputs/.runtime/task6a-fit-planner/`. The runner supplies
`PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src:tests`, an owned
`TemporaryDirectory` pytest `--basetemp`, and
`-o tmp_path_retention_policy=failed`. It cleans only its own temporary directory.

All pytest entries use `.venv/bin/python3.12 -m pytest -q --tb=short`.

| Log | Tests / observation | Exit |
| --- | --- | --- |
| `01-scaffolding.log` | Missing module collection error; excluded from feature RED | 2 |
| `02-fixed-red.log` | Two numeric fixed cases fail on explicit unimplemented planner | 1 |
| `03-fixed-expanded-red.log` | Four fixed tests fail; borrowing, tail/role/target occupancy and short voice | 1 |
| `04-fixed-green.log` | Same four fixed tests pass | 0 |
| `05-fixed-precommit.log` | Four pass after formatting/lint corrections | 0 |
| `06-smart-red.log` | Six numeric assertion failures, four fixed passes | 1 |
| `07-generated-red.log` | Seven assertion failures including generated combinations, four passes | 1 |
| `08-smart-green.log` | Eleven planner tests pass | 0 |
| `09-contract-red.log` | 92 fail, one pass: missing strict input/verification/JSON behavior | 1 |
| `10-input-green.log` | 65 pass, one fails due to an accidental edit in Fraction arguments; not feature evidence | 1 |
| `11-input-green.log` | 77 pass, 27 deselected after correcting that edit | 0 |
| `12-verify-green.log` | 102 pass, two JSON/scale cases deselected | 0 |
| `13-contract-green.log` | All 104 new tests pass | 0 |
| `14-focused-regression.log` | All 135 new and focused existing tests pass in 24.48 s | 0 |

The initial import error and accidental edit are explicitly not counted as
feature RED. The fixed, smart, input, tamper and JSON cases existed before their
corresponding production behavior. Final self-review added two tests for Smart
JSON/interpolation and malformed endpoints/null masquerades, without production
changes.

Numeric expectations include the fixed 500 ms borrow, unresolved 5/4 speed under
6/5 cap, explicit 5/4 acceptance, Smart golden endpoints
`0,1500,3500,5500,6500`, separate and combined ZH/JA maps, exact 4/3 cap with
9/8 audio speed, 64 generated overlap combinations, and awkward relative-prime
intervals. A 1000-line case checks bounded map/JSON size, exact output duration,
immutable caller data and input-reversal equality. No timing benchmark is
claimed from the test runtime.

## Final verification

Effective focused command (plus the owned `--basetemp` and retention option):

```sh
PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest -q --tb=short tests/test_fit_contracts.py tests/test_fit_plan.py tests/test_probe.py tests/test_multistem_audio.py tests/test_analysis_media.py tests/test_whisper_timing_quantization.py
```

Final focused result: **137 passed in 24.11 s**, exit 0
(`20-focused-final.log`), including 106 new planner/contract cases.

Static commands and observed results:

```text
.venv/bin/ruff check src tests
All checks passed! (exit 0; 21-final-ruff.log)
.venv/bin/ruff format --check src tests
145 files already formatted (exit 0; 22-final-format.log)
.venv/bin/python3.12 -m compileall -q src tests
exit 0 (23-final-compile.log)
uv lock --check --offline
Resolved 75 packages in 0.61ms (exit 0; 24-final-lock.log)
git diff --check
exit 0 (25-final-diff.log)
```

No frontend changed, so no frontend check was run. The controller-approved
focused regression scope was used instead of repeating the prior 748-test
full integration suite solely for these unregistered pure modules.

## Remaining mandatory boundaries

Feasible arithmetic is neither accepted audio nor dub readiness. This task
contains no measured audio retime, pitch, background, gain, peak, mux, frame,
caption-render, cloud export, listening or acceptance proof. Natural outputs
remain unchanged. Later 6B must capture actual selection-relative and absolute
extraction coordinates, audio/review identities and guarded persistent commands.
Later 6C must render and verify the actual media, captions, mix/peak handling,
private export and recovery behavior. Neither increment is completed by this
planner or its numerical tests.

## Controller closure: independent gates

Independent SPEC passed at`53182a6`: fresh137 focused tests in24.25s, plus240 deterministic mixed-mode cases against an independent per-millisecond occupancy/integration oracle and66 strict numeric-substitution cases. A distinct QUALITY reviewer then passed: fresh137 in23.01s,120 metamorphic families and maximum1000-line/3001-piece stress probes. No Critical/Important/Minor issue remained. The controller opened both reports in parent`outputs/.runtime/task6a-fit-{spec,quality}-review.md`; retained evidence stays private outsideGit.

The valid quality stress JSON measured1,265,679bytes; future request/storage limits must not assume every valid plan fits1MiB. Its observed build0.960s and validation/JSON0.976s are local measurements, not a latency promise.6B1 therefore uses the existing durable Worker to compute/validate maps outside SQL, with explicit2MiB limits/headroom and owned publication guards.6A arithmetic gates are closed; actual fitting, background/mix/caption/media and live product acceptance remain open.
