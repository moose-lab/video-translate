# Task 4C — durable target translation

This note covers the backend translation increment only. All provider calls in its tests use recorded contract doubles. No live inference, protected preview access, real credential migration, push, deployment, synthesis, measured audio fitting or final-video acceptance was performed by this implementation stream.

## Implemented contract

- The existing plain `hf_router.translate()` contract remains intact. `structured_chat()` performs exactly one remote chat POST, quotes source/context/glossary/prior phases as data, requires canonical explicit targets, and validates exact IDs, coverage, uniqueness, types, nonempty bounded text, whole response size and real optional provider metadata. Refinements require the exact prior draft/critique. Supplied and generated terminology have an explicit bounded union; supplied terms win.
- An owned immutable `TranslationCommand` captures active selection/transcript/target identity, actual source text, source proofs, requested row CAS/lock/approval, supplied context/glossary/mode and immutable provider connection settings/revision. `TranslationPhase` records a separate bounded operation/run per context, batch draft, critique, rewrite and optional shortening suggestion. Phase IDs form explicit scope suffixes; batch runs do not claim that a phase UUID is a source segment ID. Generic run creation cannot bypass the command boundary.
- Fast uses one draft call per deterministic batch (at most 20 rows / 48,000 serialized source bytes). Cinematic uses one bounded whole-source context extraction, then separate draft, critique and rewrite operations per batch. Autofit adds declared estimates and a separate shorter-suggestion operation only for a known estimated overrun. Oversized whole context is rejected before submission; no prefix is described as whole-video context.
- Generated context has its own linked immutable revision and ordered source-ID coverage. It never replaces the supplied context pointer or updates its own inference dependency. Manual target saves, lock/approval changes, source corrections, source replacement and newer human context suppress obsolete publication. Unrelated Fast rows and other target tracks remain independent.
- Each synchronous result is privately checkpointed through the existing generation-bound Operations lifecycle before domain publication. Matching paid success is validated independently of editor/publication status. Default replay retains the original command after own publication or rejected publication; an explicit guarded forced review can reuse every successful phase without a new POST. Invalid payloads, wrong generation, foreign lineage, wrong target and unsafe public facts cannot become reusable success. Unknown submissions require explicit existing retry acknowledgement for overlapping selected work or an actually duplicated shared context. A disjoint Fast command can proceed, including beside an unresolved context call for different selected rows; no blanket target lock is used.
- Direct draft and rewrite keep distinct provenance and parent history even when wording is identical. A manual same-wording save after a cloud revision also creates its own CAS revision. No phase auto-approves text. Partial failure leaves current valid wording visible and reports an incomplete phase with an isolated retry action.
- Shortening stays a suggestion until guarded explicit apply. Its editor guards are separate from inference identity; its immutable request includes source/target/context/current meaning and timing slots. Slot changes stale the suggestion while leaving current meaning wording intact. Estimates are explicitly heuristic, carry `estimated_language_rate_v1` or `unknown`, and never claim measured audio or guaranteed fit. Unknown catalog language rates have no English fallback.
- `0008_translation_operations` is frozen and self-contained. Populated upgrade/down/up, metadata parity and owned foreign-key rejection are exercised on SQLite and isolated real PostgreSQL. Existing clean-schema inventory and historical-metadata tests were extended for the new head without weakening their credential-preservation or prior-revision checks.

## RED → GREEN evidence

Meaningful failing tests preceded implementation of the structured client, guarded workflow, suggestion apply, whole-context/batch limits, current review reporting, known-unsupported capability rejection, immutable connection guards, credential-removal preflight, separate suggestion editor/cache identity, explicit batch scopes, foreign phase lineage, unsafe cached facts, equal-wording phase history and HTTP cleanup. The first client RED failed on the absent `structured_chat`; its initial GREEN plus prior adapters passed 56 tests. Later client limits passed 60 client/adapter tests. Recorded runtime tests then covered all three modes and restart after each successful private phase.

The first full backend pass reported 476 passed / 4 failures. All four were preexisting clean-schema or historical-metadata assertions that did not yet account for the two new translation tables; the assertions were updated to the appropriate schema revision. An intermediate broad run was stopped after further self-review fixes so the final evidence would use a frozen tree.

Focused evidence includes deterministic selected-ID batches with a failed second batch and isolated acknowledged retry; independent Chinese/Japanese/RTL/catalog variants; whole-context coverage and overflow; lock/manual/source/context races; default and forced paid-cache reuse; invalid cache/generation/lineage; uncertain submission; explicit suggestion apply; timing-only suggestion staleness; original/rewrite/history provenance; and all three modes running against isolated real PostgreSQL with recorded HTTP.

## Verification

Core full-backend result: **487 passed in 273.42 seconds**, with isolated PostgreSQL enabled and no skips. The final uncertainty-scope refinement then passed all **60 translation client/runtime/migration tests in 45.34 seconds**, including real PostgreSQL and the new disjoint-Fast, overlapping-row, other-target and duplicate-context regressions. The combined full suite will be repeated after the separately requested narrow Whisper timing prerequisite.

Commands use the project Python environment with `--frozen --extra dev`; pytest owns a `TemporaryDirectory` under `/tmp` and removes only that directory. Real PostgreSQL tests use the explicit local admin URL and create/drop uniquely named databases. Frontend commands prepend the bundled Node 24 directory to PATH.

- `PYTHONPATH=src VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres uv run --frozen --extra dev python` running `pytest -q --basetemp=<own TemporaryDirectory>`.
- `uv run --frozen --extra dev ruff check src tests alembic`.
- `uv run --frozen --extra dev ruff format --check src tests alembic`.
- `PYTHONPATH=src uv run --frozen --extra dev python -m compileall -q src tests`.
- `uv lock --check` and `git diff --check`.
- From `web/`, bundled Node 24: `pnpm test`, `pnpm typecheck`, `pnpm build`.

Frontend verification already completed: 34 tests passed; typecheck and build passed. Final Ruff check, formatting (114 files), compilation, dependency-lock and diff checks passed. Independent SPEC then QUALITY review remains required; this note does not self-approve either gate.

## Separate Whisper timing prerequisite

The controller-provided sanitized wire record (`hf-source-timing-wire.json`) isolates a valid last source row at 57.06–59.52 s against a 59.510 s selection. The official Whisper tokenizer timestamp quantum is 0.02 s. This repair grants at most 20 ms only to `hf_asr` with immutable model `openai/whisper-large-v3`; unknown/no model and other providers retain strict rejection. The existing NVIDIA 50 ms allowance remains separate, with exact decimal-millisecond comparisons at both declared limits. No numeric-speaker, raw-response, retry-taxonomy or schema contract is changed.

`working_timings()` remains compatible with existing three-argument callers. The fresh handler, publisher and prepared-cache validation pass `operation.model`. Only working end milliseconds are bounded; the existing `provider_end_clipped` flag makes this visible. Raw source seconds and text remain unchanged in the private checkpoint and immutable transcript originals.

RED: all 11 new tests failed before the model-aware rule; the actual-shaped registered handler reproduced `INVALID_MEDIA`. GREEN: 11 passed in 6.21 seconds. Evidence includes exact 20 ms and >20 ms boundaries, unknown/no model, other provider, existing NVIDIA boundaries, actual 59.510→59.520 data, real CPU preparation of a 59.510 s selection, private success before simulated restart, publication of the explicit flag, immutable original seconds/text, unknown-model cache rejection and acknowledged local cache review without another provider POST.

Combined full verification after this source repair: **501 passed in 285.22 seconds**, isolated PostgreSQL enabled, no skips. Frontend again passed **34 tests**, typecheck and build. Ruff, formatting (115 files), compilation, dependency-lock and diff checks passed. A subsequent small translation-enqueue concurrency follow-up is documented separately below; it does not alter this model-specific source repair. The repair is a separate scoped commit from core 4C.

## Translation enqueue and obsolete uncertainty follow-up

Queued/running/retry-wait/cancelling translation work now reserves overlapping selected rows and an actually identical shared context request. Conflicts return `RUN_ACTIVE`; only an inactive run with an unresolved submission returns `SUBMISSION_UNCERTAIN`. Disjoint Fast rows remain independent, and exact command replay retains its existing identity. Incomplete command views expose `acknowledge_uncertain_submission` when acknowledgement is required.

If source text, supplied context or glossary changed after a lost synchronous response, an explicit uncertainty acknowledgement can retire the obsolete run locally. This clears only its current-generation pointer, marks the run stale and records `run.uncertainty_acknowledged`; the old private operation remains `submitting` with its original generation and immutable captured request for reconciliation. The acknowledgement issues zero provider POSTs. A fresh guarded command can then use the changed inputs. Manual target-only changes retain the ordinary acknowledged retry behavior and do not retire that history.

After the machine restart, the inherited follow-up diff was preserved and reviewed. Source/context/glossary retirement regressions were expanded. RED was reproduced against the committed pre-follow-up production files in an isolated temporary source copy, leaving the working implementation intact: **6 expected failures in 5.52 seconds** covered queued overlap, live-running conflict classification, uncertainty action and obsolete source/context/glossary acknowledgement. An initial focused working-tree run passed **49 tests with 1 PostgreSQL skip** before the opt-in database environment was supplied; this is not the final result.

The frozen implementation and tests then passed the complete backend suite: **508 passed in 296.02 seconds**, isolated real PostgreSQL enabled, **no skips**. This includes the added workspace/project ownership checks and frozen migration foreign-key rejection on SQLite and PostgreSQL. The uncompleted pre-restart broad run is not counted as evidence.

Actual verification commands in this follow-up:

- Python is the existing `.venv/bin/python` **3.12.9**; `.venv3.12` does not exist in this checkout. `PYTHONPATH=src VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres PATH=/opt/homebrew/bin:$PATH .venv/bin/python` invoked `pytest -q --basetemp=<own TemporaryDirectory>`; the owned temporary directory was removed on completion.
- PostgreSQL **14.18** was initialized under the already ignored `var/task4c-postgres/data` with the test-only `vt_test` owner and bound to `127.0.0.1:53227`, with Unix sockets disabled because the checkout path exceeds the platform socket-path bound. Tests created/dropped their own uniquely named databases. No existing cluster was changed.
- `.venv/bin/ruff check src tests alembic`, `.venv/bin/ruff format --check src tests alembic` (**115 files**), `PYTHONPATH=src .venv/bin/python -m compileall -q src tests`, `uv lock --check` and `git diff --check` passed.
- Bundled Node **v24.22.1** with `/opt/homebrew/bin/pnpm` **9.12.2**, from `web/`: `pnpm test` (**34 passed in 3.24 seconds**), `pnpm typecheck` and `pnpm build` passed. The initially selected bundled pnpm's automatic install preflight aborted without a TTY; the existing Homebrew pnpm ran the installed dependencies successfully without tracked dependency changes.

No real provider calls, protected preview changes, local models, push or deployment were performed. Independent SPEC and QUALITY gates remain the controller's next steps.

## Independent review closure

SPEC PASS and QUALITY PASS cover core4f7f211 plus follow-upbdb2e8d. Each reviewer independently ran67 focused tests with isolated real PostgreSQL and no skips. SPEC added3 independent context/cache/Arabic unknown-estimate probes. QUALITY added3 actual-PG concurrent enqueue/publication probes, all passed. No production changes were required by either review. Current later commits through8b90981 are documentation only. This closes the backend translation increment, not live HF target translation, synthesis, final audio/video acceptance or deployment.
