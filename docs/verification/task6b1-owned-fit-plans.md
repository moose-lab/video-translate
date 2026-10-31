# Task 6B1: owned fit settings and CPU plan capture

Verification chronology: the first implementation and its 925-test recovery pass below describe frozen source `7934bcd`. Independent SPEC subsequently found S1–S3; that pass is historical baseline evidence, not verification of the corrections. The final section records the corrected source and its separate evidence. Independent SPEC re-review and then distinct QUALITY remain mandatory.

This increment adds project-owned fit defaults/history, guarded immutable plan commands and per-cell capture, and durable CPU `plan_fit` results. It does not render, retime, mix, create background beds, shorten text, enqueue a model, export, or alter the protected preview. Mathematical feasibility, current input proofs, audio acceptance and the captured purpose remain separate facts.

## Contract and ownership

Five additive tables retain settings roots/versions, commands, every requested cell (including excluded preview cells), and separately published results. Owner, source revision/segment, translation cell, audio root/version/cell and result command/run family relationships use composite foreign keys. Migration `0011_fit_plans` is self-contained, with no mutable model imports and no changes to frozen earlier migrations.

`GET/PUT /api/projects/{id}/fit-settings` works before upload. Default revision 0 reads insert nothing; the first explicit save always creates version 1. Later canonical no-ops reuse the same version without an event or invalidation. Real settings saves use project-locked CAS and only update the `finishing.fit_settings` dependency facet. Values are strict bounded integers and exact canonical rational pairs; extra fields and float/bool/string coercions are rejected. History and route pagination are bounded to 100.

`POST /fit-plans` requires current source selection/transcript, settings revision and exact per-cell target/audio/review proofs. The required additive `expected_source_revision_id` reuses the existing authorized source row's `revision_id`; it closes timing and role-assignment CAS independently of source wording. Display-name edits leave that identity unchanged. Canonical aliases and duplicate cells reject before capture writes. Requests allow at most 16 targets and 1000 total cells, with the existing 4 MiB streaming envelope bound and a separate 2 MiB captured snapshot bound.

A `dub` command requires each selected target's entire active source-row set and current accepted usable natural audio for every row. `incomplete_preview` permanently retains that purpose and permits explicit subsets; current valid natural audio waiting for listening can be included, while missing or invalid/stale audio is visibly excluded. Supplied foreign/cross-cell output IDs reject. Each target stores its own included source IDs for a future bed mask. `original_only` has zero target claims and an identity map, and never becomes dub-ready.

Currentness checks source asset/hash/selection/absolute window/transcript, settings, actual source revision/times/role, target revision/wording, audio selection/output/hash/measurement and listening/QC proof. The immutable common map uses selection-relative coordinates. It is never replaced with a historical output or silently promoted after a review edit. `audio_eligible` assesses captured requested cells independently of purpose; only a current `dub` can be `dub_ready` or `render_eligible`. Infeasible timing remains a successfully computed review result with 6A issues and null fitted voice endpoints.

List queries project summary columns only. They label currentness, plan validation and audio eligibility `not_assessed`/null and expose stored feasibility/duration under `captured_result`. Detail performs authoritative proof checks and strict map validation; listing 100 records never loads their full maps or captured cell histories. Detail/history rows paginate separately from the bounded full common map.

## Durable computation and shared changes

`plan_fit` is command-only and scoped by immutable command ID. Capture stores bounded plain inputs, then admits one existing Worker run. The handler prepares `provider=cpu, model=shared_fit_v1`, computes/serializes/strictly validates outside SQL, checks lease/cancellation before and after work, and checkpoints validated JSON through existing Operations. A short publisher compares the validated payload/fingerprint to the current producing operation/generation/input/command and rechecks current guards; it inserts one result without rebuilding or validating the map inside SQL. No PreparedObject, new job lifecycle, storage read/write or network call is used.

The stored decoder checks exact field sets and actual scalar types, reconstructs 6A dataclasses, runs `validate_plan`, and matches all included cell keys, roles, source times, measured natural durations, settings and source duration to immutable owned capture. Command hashes cover source/output hashes and measurement/listening provenance. Cache checks bind command, run, current operation, generation, provider/model/policy, inputs and payload hashes. Missing, damaged or wrong-origin caches fail visibly rather than being repaired through inference. Detail also rejects contradictory result summary metadata.

Two small shared extensions are required:

- `Operations.cache` keeps its 2 MiB default for every existing stage. A strict integer override allows at most 64 KiB of envelope headroom, and a larger-than-default request is accepted only for `plan_fit`. The computed map itself remains capped at 2 MiB separately.
- Event facts accept only explicit bounded fit purpose, counts, boolean feasibility, two declared issue codes and canonical bounded rational planned duration. Existing fact types and limits remain unchanged. Events retain command/run IDs, causal admission order and safe counts; they contain no dialogue, server path, provider URL or secret.

## Evidence and verification

Private evidence is in parent `outputs/.runtime/fit6b1/` with mode-600 logs, outside Git. Later commands use `check.py LABEL ...`, which records the exact subprocess argv/stdout/exit and creates its own `TemporaryDirectory` basetemp with `-o tmp_path_retention_policy=failed`. It removes only that owned directory. Environment: `PATH=/opt/homebrew/bin:$PATH`, `PYTHONPATH=src:tests`, `.venv/bin/python3.12`; actual PostgreSQL runs opt in with `VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres` and create/drop only their own fixture databases.

Observed feature REDs include missing settings/plan endpoints (404), wrong producing operation accepted on detail, unsafe/unbounded shared fit facts/headroom, absent explicit list assessment markers, empty damaged checkpoint classified as generic failure, corrupted capture inclusion column accepted, absent exact source revision DTO proof, missing result command/run family FK, contradictory stored result summaries, and preview audio eligibility conflated with purpose. Each has a retained named RED log and a subsequent focused GREEN run. Assertions/import/fixture setup mistakes do not count as feature RED.

Harness disclosures: an early command omitted its workdir and read no files; corrected immediately. The first two-target fixture expected a `segment` wrapper on PATCH, while the existing route returns the row directly; the retained `target-stress.log` shows the KeyError and the corrected rerun passed. One early run had **15 passed, 3 setup errors** from SQLite disk I/O/ENOSPC and temporary-directory creation, not product assertions. Its original output is in the tool transcript; its `initial-green.log` name was later reused by the successful owned-temp run, so that original stdout file is not retained. Only the original implementation actor's verified completed pytest-37/38/39 directories were removed. Subsequent runs all use isolated owned basetemp and failed-only retention.

Completed focused evidence before final freeze:

- Initial settings RED then 8 GREEN; initial capture/purpose/CAS plus strict operation provenance reached 18 GREEN.
- SQLite and actual PostgreSQL populated 0010→0011→0010→0011 roundtrip, frozen metadata parity and single-column family/owner FK probes passed (2 tests).
- Actual SQLite/PostgreSQL competing settings saves, duplicate command capture, accepted natural fixture publication, command events/cursor replay and ownership probes passed; the later run-family FK regression additionally exercised one-column run replacement.
- Worker fault matrix covers prepared success then publication loss/restart, damaged/missing cache, settings/listening/target/source/audio selection edits during computation, cancellation and lease loss. SQLAlchemy transaction observers assert full build and strict validation execute with no live SQL transaction.
- A generated valid 1000-line/3001-piece map is **1,309,025 bytes** under the same JSON sizing function. Strict validation accepts it above 1 MiB; the explicit 2 MiB policy is independently tested. No large fixture is checked in.
- Ruff check/format, compileall, offline `uv lock --check --offline` and `git diff --check` passed; final results are appended after the frozen full backend run.

Pre-freeze expanded focused command completed **272 passed in 321.01s** with PostgreSQL opted in. The final new-suite run completed **71 passed in 74.21s** with PostgreSQL opted in; the latest defensive detail checks completed **7 passed in 9.00s** and the stronger populated-new-settings downgrade/upgrade roundtrip completed **2 passed in 2.79s**.

Source/tests are committed and frozen at `7934bcd` (preceded by the settings slice `4137fff`). The original full invocation was:

```sh
VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres .venv/bin/python3.12 ../.runtime/fit6b1/check.py full-backend -q
```

`check.py` deliberately inherits that environment unchanged; the command prefix is part of the original tool invocation, rather than a later edited log header. Original tool session handle: `94304`, runner PID `5364`, pytest PID `5386`, owned basetemp `/var/folders/sr/7sz78lvn5kxd436pgp4mkh1w0000gn/T/vt-fit6b1-wzez5n6t/tests`. That actor and both processes disappeared, and the original session later returned `Unknown process id`. `full-backend.log` ends at 70% plus 12 dots with no terminal exit or pytest summary. It is preserved untouched as interrupted evidence, **not a passing full run**.

## Recovery and final frozen verification

One replacement implementation actor performed the recovery on 2026-10-31 without changing production, tests, migrations or dependencies. The existing isolated PostgreSQL data directory was restored by the controller at the required port before this run. A read-only SQL query confirmed actual **PostgreSQL 14.18**, user `vt_test`, server `127.0.0.1:53227`. The recovery actor did not stop, change or migrate that server. All actual PostgreSQL tests used the same explicit admin URL above, creating and dropping only their own fixture databases.

The replacement full invocation was:

```sh
VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres .venv/bin/python3.12 ../.runtime/fit6b1/check.py full-backend-recovery-20261031 -q
```

Its original session `62884` was retained through terminal completion: runner PID `7084`, pytest PID `7103`, owned basetemp `/var/folders/sr/7sz78lvn5kxd436pgp4mkh1w0000gn/T/vt-fit6b1-6ydfutoa/tests`. Observation timeouts did not trigger any restart. `full-backend-recovery-20261031.log` records **925 passed in 879.39s (0:14:39), EXIT: 0**, with **no skips or failures**. `recovery-environment-20261031.log` separately records the frozen source SHA, exact selected environment, handles and hash/size of the untouched interrupted log. The wrapper removed only its own temporary directory on completion. Available disk stayed around 1.8–1.9 GiB; the recovery actor deleted no unrelated fixtures or files.

Fresh post-full static checks all exited 0, with separate mode-600 logs:

| Command | Observed result | Log |
| --- | --- | --- |
| `.venv/bin/ruff check src tests alembic` | All checks passed | `recovery-ruff-20261031.log` |
| `.venv/bin/ruff format --check src tests alembic` | 168 files already formatted | `recovery-format-20261031.log` |
| `.venv/bin/python3.12 -m compileall -q src tests alembic` | Passed | `recovery-compile-20261031.log` |
| `uv lock --check --offline` | Unchanged 75-package lock resolved | `recovery-lock-20261031.log` |
| `git diff --check` | Passed | `recovery-diff-20261031.log` |
| `git diff --exit-code 7934bcd26d6f9151c6a285dd6487bf425dea525f -- src tests alembic pyproject.toml uv.lock` | Empty, proving the tested trees stayed frozen across controller documentation commits | `recovery-frozen-tree-20261031.log` |

Recovery self-review checked strict DTOs and canonical settings/no-op history; source revision, target/audio/listening CAS and preview-purpose separation; the five additive tables and family FKs; command-only admission and bounded summary projection; capture/provenance hashes; exact stored-plan decoding against immutable rows; lease/cancel checks; computation/validation outside SQL and short guarded publication; prepared-success restart and invalid-cache behavior; default Operations cache compatibility and safe event facts. The corresponding strict-input, ownership, schema, actual SQLite/PostgreSQL race, mutation, transaction-observer, recovery and 1000-line stress cases are in the terminal full pass. No production defect was found in this self-review, and no source/test change was needed. This is implementation self-review, not independent SPEC or QUALITY approval.

No frontend files changed, so frontend checks are outside this increment. Only this verification document is committed for the recovery closure; private logs remain outside Git.

This is CPU/domain/schema evidence only. Actual transformed audio/video, background treatment, peak handling, captions, export, real listening acceptance, live inference and SaaS deployment remain separate later acceptance work. Independent SPEC, then distinct QUALITY, must both pass before 6B2 begins.

## Independent SPEC corrections S1–S3

The controller read `outputs/.runtime/fit6b1-spec/review.md` and assigned its three findings to the same replacement implementation actor. Corrected source/tests are committed and frozen at `a6d71b76530974fd3165c7b2386901d610aa82c0`.

- **S1:** Authoritative detail now validates actual boolean feasibility, exact canonical rational summary keys/integer values, and typed agreement of duration/issues with the strictly validated result map. Invalid summaries clear the plan, feasibility and duration, disable rendering and add `FIT_PLAN_INVALID`. Summary lists still read only summary columns and retain all `not_assessed` markers; malformed rational summary scalars are suppressed rather than exposed.
- **S2:** A cohesive private `fit_checkpoint.py` contract is shared by detail, recovery and the short publisher. Exact checkpoint/binding/fact keys and bounded canonical JSON fingerprints distinguish nested bool/int/float values. It hashes the actual cached plan against that checkpoint's own stored fingerprint, then matches the producing plan to the validated owned result. Canonical public facts are derived from immutable captured rows and the validated map. Origin checks bind the current command/run/operation/generation/input/provider/model/policy and exact request. Detail and recovery perform full decode/arithmetic and these integrity checks after SQL closes; publication checks only the bounded prepared metadata, typed hashes and already validated handler result. The strict decoder's final canonical projection comparison also uses a fingerprint rather than Python numeric equality. No unrelated map can pass the immutable capture comparison.
- **S3:** The migration test now uses a non-current version with a disjoint revision for single-column family/owner mutations. This avoids both `(settings_id, revision)` unique collisions and incidental incoming current-head references. PostgreSQL checks SQLSTATE `23503` and the intended named root/owner/parent/current FK; SQLite checks the actual foreign-key failure message. Populated upgrade/down/upgrade and fresh metadata parity remain intact. No migration or schema change was required; frozen `0011` and every earlier migration are unchanged.

All correction logs are private mode-600 files under `outputs/.runtime/fit6b1-corrections/`. The copied runner keeps the same explicit Python/PATH/PYTHONPATH, actual PostgreSQL admin opt-in, owned `TemporaryDirectory` and failed-only retention policy. It removes only its own basetemp. Unchanged independent probe files remain under `fit6b1-spec/`.

Observed correction evidence:

| Log | Terminal observation | Exit |
| --- | --- | --- |
| `independent-red.log` | Original five ready-dub integrity probes plus both masked migration probes: **7 failed in 16.32s** | 1 |
| `tracked-red.log` | Initial tracked matrix: **13 failed, 2 passed in 32.91s**; later strengthened numeric JSON injections use forced SQL UPDATE so ORM equality cannot suppress a mutation | 1 |
| `migration-classification-red.log` | Newly explicit FK assertions expose SQLite UNIQUE / PostgreSQL `23505`: **2 failed in 2.44s** | 1 |
| `initial-green.log` | **22 passed, 2 failed in 47.23s**; the remaining failures were an incorrect test expectation naming the root FK instead of the actual project-owner FK for a workspace mutation, corrected without production changes | 1 |
| `migration-green.log` | Both tracked backends and unchanged independent error-cause instrumentation: **4 passed in 5.43s** | 0 |
| `affected-green.log` | New 18-case tracked matrix, existing 71 fit cases, original seven independent findings and 13 exploratory independent cases: **109 passed in 147.84s**, no skips, actual PostgreSQL enabled | 0 |

The 18 tracked regressions include forced persisted float/bool/extra summary metadata; unknown checkpoint/binding/fact fields; cached numeric corruption with both unchanged and recomputed hashes; contradicting and equal-valued malformed public facts; prepared-success restart; and edits after handler validation but before short publication. Existing SQL transaction observers, duplicate-command reuse, actual SQLite/PostgreSQL races, unrelated-plan rejection, input mutations and 1000-line stress tests remain in the affected pass.

The sole corrected full invocation is:

```sh
VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres .venv/bin/python3.12 ../.runtime/fit6b1-corrections/check.py corrected-full-backend-20261031 -q --tb=short
```

Original tool session `83987`, runner PID `18678`, pytest PID `18697`, owned basetemp `/var/folders/sr/7sz78lvn5kxd436pgp4mkh1w0000gn/T/vt-fit6b1-pb8r_ynq/tests`. `corrected-full-environment-20261031.log` records frozen HEAD and selected environment. A fresh read-only SQL query reconfirmed actual PostgreSQL 14.18 / `vt_test` / `127.0.0.1:53227`. The original session was observed through terminal completion: **943 passed in 919.80s (0:15:19), EXIT: 0, no skips or failures**, retained in `corrected-full-backend-20261031.log`. This is the corrected full result; the prior 925 pass remains historical. No observation timeout triggered a restart. The runner removed only its own basetemp.

Fresh post-full checks all exited 0:

| Command | Observed result | Correction log |
| --- | --- | --- |
| `.venv/bin/ruff check src tests alembic` | All checks passed | `final-ruff.log` |
| `.venv/bin/ruff format --check src tests alembic` | 170 files already formatted | `final-format.log` |
| `.venv/bin/python3.12 -m compileall -q src tests alembic` | Passed | `final-compile.log` |
| `uv lock --check --offline` | Unchanged 75-package lock resolved | `final-lock.log` |
| `git diff --check` | Passed | `final-diff.log` |
| `git diff --exit-code a6d71b76530974fd3165c7b2386901d610aa82c0 -- src tests alembic pyproject.toml uv.lock` | Empty: corrected tested trees remained frozen | `final-frozen-tree.log` |
| `git diff --exit-code 7934bcd26d6f9151c6a285dd6487bf425dea525f -- alembic pyproject.toml uv.lock src/videotranslate/execution/prepared.py src/videotranslate/execution/events.py` | Empty: migrations, dependencies and shared cache/event contracts stayed unchanged | `final-frozen-schema-shared.log` |

Correction self-review found the shared contract preserves the off-SQL arithmetic boundary, bounded summary-only lists, immutable capture matching, guarded publication and unchanged default Operations cache. No dependencies, migration, provider request shape, protected preview or frontend changed. This remains implementation evidence for the same independent SPEC reviewer, without self-issued SPEC/QUALITY approval or 6B2 implementation.
