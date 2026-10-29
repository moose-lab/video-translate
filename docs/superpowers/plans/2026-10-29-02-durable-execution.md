# Durable Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with test-driven-development. Execute continuously within the approved SaaS scope; steps use checkbox syntax.

**Goal:** Run actual media probing in a separate restartable worker, with private persistent run/attempt/event records, safe leases/retries/cancellation, remote-submission recovery and dependency-specific stale-result protection ready for cloud inference stages.

**Architecture:** Extend the existing SQLAlchemy/FastAPI foundation. PostgreSQL is the production queue; SQLite remains an explicit development/test adapter. Database transactions publish state plus events atomically. A handler registry defines supported stages and their exact input dependencies; this increment ships only a real CPU `probe` handler, never dummy cloud successes. Later increments register actual cloud handlers through the same interface.

**Tech Stack:** Existing Python 3.12, SQLAlchemy, Alembic, FastAPI and pytest lock; standard-library subprocess and FFprobe. No broker or inference packages are required for this increment.

## Existing interfaces

`create_app(settings)` owns `app.state.session_factory` and `.storage`; `get_db` supplies request sessions. `owned_project(db, workspace_id, project_id)` enforces workspace and active-project scope. `update_project` is revision CAS and joins the caller transaction. `Storage.put/open/delete` never exposes keys to clients. `APIError` is the safe API envelope. Persistent timestamps use `UTCDateTime` and `utcnow`.

Foundation must pass its independent spec and quality reviews before implementation begins. Do not change unrelated foundation behavior except for the explicit integration hooks below.

## File responsibilities

- `models/execution.py`: StageRun, RunAttempt, ProjectEvent and InputState records; explicit status constraints, indexes and unique keys.
- `execution/contracts.py`: bounded typed stage requests, run results and safe failure classes; no arbitrary serialized exception or request dump.
- `execution/inputs.py`: canonical JSON SHA-256, scoped input keys, snapshots, selective invalidation and freshness checks.
- `execution/events.py`: transactional per-project sequence allocation and whitelisted event metadata.
- `execution/registry.py`: stage definition and handler interfaces; input resolvers and explicit supported stages.
- `execution/service.py`: create/idempotency, claim/heartbeat, finish/fail/retry/cancel/recovery transactions.
- `execution/context.py`: lease-aware worker operations and remote submission/handle checkpoints.
- `execution/worker.py`: bounded handler dispatch loop, heartbeat thread, interrupt/cancel cooperation, command-line entry point.
- `media/probe.py`: bounded local materialization and real FFprobe, safe normalized metadata and limits.
- `routes/runs.py`, `routes/events.py`: protected run APIs, cursor polling and SSE.
- `alembic/versions/0002_durable_execution.py`: forward/backward migration; extend foundation schema without replacing migration0001.
- `tests/test_execution.py`, `tests/test_events.py`, `tests/test_worker.py`, `tests/test_probe.py`: state, process/restart, tenancy and actual media behavior.
- Modify `app.py`, `config.py`, model registration, project patch/source upload integration hooks, README and engineering evidence.

## Persistent contract

A StageRun has opaque ID, workspace/project, stage, scope key, optional target language/segment ID, immutable options, input project revision and dependency fingerprint/snapshot, output key, status, attempt counter, automatic-failure count, next-attempt time, current lease token/owner/expiry/heartbeat, cancellation timestamp, result/error, provider/model/request key/request ID/remote state and timestamps. Actual per-attempt history is separate; manual retry never destroys past attempts. JSON responses whitelist safe fields and omit lease tokens, storage paths, request keys, complete snapshots and credentials.

Statuses: `queued`, `running`, `retry_wait`, `succeeded`, `needs_review`, `failed`, `stale`, `cancelling`, `cancelled`. A separate current/stale marker may coexist with a still-running lease. `succeeded` means the real registered handler completed and its dependencies still match; it is never fabricated for missing handlers.

InputState has unique workspace/project/key and a deterministic fingerprint. A run snapshot contains exactly the named dependencies returned by its stage resolver. Keys are internal service data, never arbitrary public update input. Foundation maintains `source.video` (asset ID + SHA-256), `source.audio_track` and `source.language`; later domain services add per-segment, reference, translation, mix and subtitle keys. Selecting a different audio track does not invalidate video probe metadata. Every run publishes one known output key; making a result stale clears that key and recursively invalidates dependent runs. Unrelated keys/targets remain reusable. Global project revision is lineage, not the sole cache key.

Events use a per-project integer sequence whose allocation is serialized by an atomic Project counter update in the same transaction. This prevents a later-committed event receiving a lower cursor and disappearing on reconnect. Each event carries workspace/project/run/stage/segment/target/attempt/time and bounded safe facts, never raw private text or tokens. Polling and SSE are always workspace scoped and hide deleted projects.

## Task 1: Schema and explicit stage interface

- [ ] Add failing schema/contract tests before models. A run cannot exist outside its project/workspace; unique run idempotency keys and project event sequences are enforced; all datetime results are UTC. Exercise migration upgrade/downgrade and parity with Base metadata.
- [ ] Define immutable typed contracts:

```python
class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: str = Field(min_length=1, max_length=40)
    target_language: str | None = Field(default=None, max_length=40)
    segment_id: str | None = Field(default=None, max_length=36)
    options: dict = Field(default_factory=dict)

class RunRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledge_uncertain_submission: bool = False

@dataclass(frozen=True)
class StageDefinition:
    name: str
    validate_options: Callable[[dict], dict]
    resolve_inputs: Callable[[Session, Project, RunCreate], dict[str, str]]
    handle: Callable[["RunContext"], "StageResult"]
    publish: Callable[[Session, "StageRun", "StageResult"], None] | None = None
```

The registered stage validates options itself; probe accepts no options or target/segment scope. Unknown stages return422 `STAGE_UNAVAILABLE`. Do not queue nonfunctional future stages just to populate the UI.

The optional publisher is a narrow transaction hook for later domain rows (segments, translations and private artifact metadata). Invoke it only after lease and freshness checks inside the same completion transaction, before the success event. A stale/lost-lease handler must never publish domain rows on its own. No network or long media work belongs in that transaction; handlers prepare results first. Probe needs no domain publisher. Protect prepared but unpublished temporary output cleanup on failed publication.
- [ ] Implement execution models/migration and registry. Run `uv run pytest tests/test_execution.py -q`, observe RED then GREEN; record exact counts and commit.

## Task 2: Input dependencies, idempotency and transactional events

- [ ] Write tests proving deterministic dictionary-order-independent fingerprints, source-change invalidation, different-target reuse, recursive downstream invalidation, stale in-flight completion rejection, and no invalidation for an unrelated name change.
- [ ] Test idempotent run creation using the same `Idempotency-Key` and identical normalized request: same run, one queued event. Reusing the key with different inputs/request returns409. Missing source returns409; foreign/deleted project returns404. Keys are bounded and hashed or kept server-only.
- [ ] Implement `set_inputs(db, project, values)`, `capture_inputs(...)`, `is_current(...)`, and `append_event(...)` as caller-owned transactions. Run creation locks/serializes against input edits, captures current keys/revision, creates run and queued event, then commits once. Existing successful matching output may be reused only after freshness checking.
- [ ] Hook source upload and relevant project PATCH changes into input updates. Foundation upload still cleans objects on failed transaction. Initialize missing keys for existing projects from authoritative fields. Changing project name or unrelated target selection does not invalidate a probe.
- [ ] Event facts have an allowlisted typed schema (codes/counts/hash/IDs/provider/model/progress/current revision/duration). Reject or exclude credentials, arbitrary URLs and free-form exception details. Add recorded upload-completed/source-track-selected events, without falsely claiming upload-start if server has not received anything.
- [ ] Run targeted tests RED/GREEN and commit.

## Task 3: Atomic leases and real attempt history

- [ ] Write a two-independent-session concurrent claim test that yields exactly one winner for one eligible run. A fresh worker instance using the same DB resumes queue state. Test due-time ordering, deleted-project exclusion and expired/wrong lease denial for heartbeat/result/failure writes.

```python
def test_claim_has_one_owner(queue, two_workers):
    run = queue.create_probe()
    first, second = two_workers.claim_concurrently()
    assert sum(item is not None for item in (first, second)) == 1
    assert queue.reload(run.id).attempt == 1
```

- [ ] Implement claim using atomic guarded UPDATE/RETURNING (or PostgreSQL row locks with SKIP LOCKED and an equivalent correct SQLite CAS), never select-then-unconditional-update. Claim allocates a fresh unguessable lease token and one attempt row atomically. Heartbeat/completion predicates include run ID, token, running/cancelling status and nonexpired lease. Completion also verifies dependency freshness in the same transaction before publishing output input-key/result/events.
- [ ] Use one documented lock order for all transactions: project first, then its runs/inputs. Claim may select a candidate before taking the project lock, but must recheck eligibility with CAS after that lock. Do not take a run lock and then append an event that waits for a project lock while an input edit holds the project lock and waits for the run. PostgreSQL SKIP LOCKED can avoid busy projects; SQLite must perform its write serialization before reading the snapshot it will publish.
- [ ] Persist durations using actual timestamps; do not show made-up percent. Slow handlers can heartbeat independently. A lost-lease worker cannot publish even if its subprocess later exits successfully.
- [ ] Verify targeted and full foundation tests, commit.

## Task 4: Failure, retry, cancellation and uncertain remote work

- [ ] Test bounded exponential backoff for explicitly transient safe failures; credential/config/unsupported-language errors do not auto-retry. Manual retry is CSRF protected, retains attempt history and re-captures current inputs. Already-active retry returns409; failed/stale/review/cancelled runs can be explicitly retried under stage policy.
- [ ] Remote request state checkpoints are durable: `not_submitted → submitting → submitted → completed`; save provider/model and stable request key before call, save returned remote request ID immediately. `submitting` without a saved ID after crash/timeout becomes `needs_review` with `SUBMISSION_UNCERTAIN`, never an automatic duplicate submission. Explicit acknowledgement is required to retry this case.
- [ ] If an accepted remote ID exists, recovery dispatches the same handler in resume/poll mode with that ID; it cannot invoke a fresh submit. Transient polling failures retry the same remote job and preserve handle. Use test-only recording handlers to prove submit_count==1 across worker restarts; never label these as real model requests.
- [ ] Queued/retry-wait cancellation goes directly tocancelled. Running cancellation requests `cancelling`; only worker confirmation, confirmed remote cancellation or terminal remote completion/discard reaches cancelled. Never claim remote termination from a local request alone. Expired cancelling leases remain recoverable; uncertain remote cancellation is visible and not resubmitted.
- [ ] Lease recovery distinguishes safe local rerun, saved-handle resume and uncertain submission. Record attempt outcomes and recovery events; soft-deleted projects prevent publication and further external submit. Test every branch RED/GREEN and commit.

## Task 5: Actual probe handler and independent worker process

- [ ] Write tests with real tiny FFmpeg video+audio/multi-audio fixtures; fail before handler. Verify duration, codec, dimensions, original stream index, audio-track language/channel metadata, corrupt input rejection, no audio handling, bounded runtime and limits. Parsing must reject nonfinite durations and malformed oversized metadata. Do not trust declared upload MIME as probe success.
- [ ] `ProbeResult` exposes safe facts: duration_ms, video codec/dimensions/frame rate and audio tracks with both zero-based audio ordinal and original absolute stream index, language, codec/channels/sample rate/default. Project `source_track_index` is the audio ordinal (default0 means first audio, not video stream0); retain this explicit distinction in all later extraction. No local path or object key in results/events.
- [ ] Implement bounded materialization from `Storage.open` into an isolated temporary directory, `ffprobe` with protocol restrictions and a subprocess argument list, timeout/output bounds and cleanup on success/error/cancel. Remote inference is not part of this handler. Source media is untrusted: no shell interpolation, no network protocols via playlist input, enforce size/duration/pixel constraints. Limit metadata and process lifetime.
- [ ] Implement worker entry `uv run python -m videotranslate.execution.worker --once` and continuous loop with sensible poll/lease/heartbeat settings. `--once` claims at most one task, makes no task exit successfully if unavailable, and leaves a truthful state. SIGTERM stops claiming; current handler cooperatively cancels or releases safe work without clearing uncertain remote checkpoints.
- [ ] Start API/worker as independent processes in a test, queue through authenticated HTTP, exit/restart worker and verify persistent result/events. Use explicit dev paths and no AI runtimes. Run focused tests RED/GREEN and commit.

## Task 6: Protected run APIs and reconnectable events

- [ ] Implement stable API routes:

```text
POST /api/projects/{id}/runs                 -> 201 safe run JSON
GET  /api/projects/{id}/runs?limit=50&offset=0 -> {items,total}
GET  /api/runs/{id}                          -> safe run + attempt history
POST /api/runs/{id}/retry                    -> updated safe run
POST /api/runs/{id}/cancel                   -> updated safe run
GET  /api/projects/{id}/events?after=0&limit=100 -> {items,total,next_cursor}
GET  /api/projects/{id}/events/stream?after=0&follow=true -> text/event-stream
```

Limits max200; offset/cursors nonnegative. All mutations require CSRF; all reads and streams authorize project/workspace on every fresh fetch, including deletion/session expiration during stream. Unknown/foreign run IDs return404.
- [ ] Test reconnect with Last-Event-ID and after: if both supplied use maximum valid cursor; malformed header returns400. Each SSE message has `id`, stable `event` and JSONdata; connection includes bounded heartbeat comments. `follow=false` drains currently available rows then closes for deterministic clients/tests. Open no long-lived DB transaction while waiting.
- [ ] Test event concurrency/commit ordering, reconnect no duplicates/missing events, foreign/deleted denial, session expiry, safe error envelope, no lease/token/path leaks. Do not implement in-process-only event buffers or fake progress.
- [ ] Run API/event tests RED/GREEN, complete suite, commit.

## Task 7: Verification and handoff

- [ ] Document exact runtime/migration/worker commands and new settings in README/.env.example. Add official SQLAlchemy UPDATE/RETURNING and PostgreSQL locking source links to engineering sources.
- [ ] Run complete pytest, Ruff, compileall, migration upgrade/downgrade/parity and git diff checks. Use a live isolated PostgreSQL instance if available for claim/event concurrency/migration evidence, and label SQLite tests separately. Never touch an existing user database or listen publicly; shut down the temporary instance after testing.
- [ ] Record direct TDD, real worker/probe and restart/cancellation evidence in `docs/engineering/execution-verification.md`, plus unsupported/deferred cloud stages. Commit scoped code/tests/docs. Report public extension interfaces for the next cloud-provider increment.
- [ ] Controller independently reruns checks, performs spec review, resolves gaps, then separate quality review before advancing.

## Scope boundaries

This increment establishes execution infrastructure and a truthful real probe stage. Remote AI adapters, timeline/cast/translation editors, fitting/mixing/exports and frontend remain in subsequent approved increments. Completing probe does not complete the SaaS or either real EN→ZH/JA integration test. Unknown stages fail explicitly until registered with real handlers.

Crash-time reconciliation of object uploads can safely delete only definitely owned unreferenced objects with an age/grace check and bounded scan. If storage does not support listing, record reconciliation as a deployment capability requirement rather than pretending immediate deletion is atomic with the database. A failed explicit upload's cleanup remains covered by foundation tests.
