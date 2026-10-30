# Owned fit settings and plan capture implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development and test-driven-development. Execute with one fresh implementer only after6A independent SPEC and QUALITY both pass. Then independent SPEC followed by distinct QUALITY for this increment. Continuous construction is already authorized; do not request another execution choice. Steps use checkbox syntax.

**Goal:** Capture an immutable, workspace-owned shared fit plan from exact current source/target/audio/review proofs, expose editable versioned fit settings and bounded history, and make complete dubbing, incomplete preview and original-only intent unambiguous.

**Architecture:** Project-locked APIs resolve current domain records, verify explicit client CAS proofs and enqueue an existing durable Worker stage. The Worker computes/validates the gated pure6A plan outside SQL, checkpoints private JSON through existing Operations, then publishes an owned result under short current-input guards. Later6B2 commands consume these plans to render actual media; this increment performs no storage/media/network I/O and never computes a full plan inside a publication transaction.

**Tech Stack:** Existing Python3.12/FastAPI/Pydantic2/SQLAlchemy2/Alembic/SQLite/PostgreSQL, Worker/PrivateOperation and6A Fraction planner. No new dependency, remote provider, local model, FFmpeg execution or prepared file object in6B1.

## Actual integration points and boundaries

- `media/fit_types.py` defines `FitSettings`, `FitLine`, `FitPlan`; `media/fit_plan.py` supplies `build_plan`, `validate_plan`, `plan_json` and `map_time`. Stored policy is`shared_fit_v1`; rational JSON uses exact numerator/denominator pairs. Arithmetic feasibility is separate from current audio readiness.
- `dubbing/source.py`: `active_source`, `current_selection`, `source_state` and `selection_current` enforce source selection/transcript lineage. Source line times are selection-relative; retain the absolute selected window as well.
- `dubbing/segments.py`: `active_segments_query` and `active_segment`; actual `SegmentRevision` supplies text fingerprint, times and speaker ID. Borrow grouping uses speaker identity, never its display label. An unknown role staysnull.
- `dubbing/translations.py`: `track_for`, `translation_state`; use the owned canonical tag and exact current translation row, not a global project revision.
- `dubbing/synthesis.py`/`synthesis_outputs.py`: current audio selection and immutable `NaturalOutput`, including actual measured duration and proof. `dubbing/voice_qc.py`: `current_proof`, `output_assessment` and immutable listening/QC evidence. Ordinary planning requires current usable accepted audio, not a good CER alone.
- `models/synthesis.py`: `NaturalOutput` has a cell unique key `(id,track_id,segment_id,project_id,workspace_id)`. `AudioSelectionVersion` has a family key including `selection_id`; capture the root ID if a composite FK targets that version. `TranslationRevision` has a cell key with segment before track. Respect actual column orders.
- Existing `Owned`, `owner_constraints`, `owned_fk`, project-first locks, `changed` events, `BoundedDubbingRoute`, identity/CSRF and pagination are the service patterns. Settings/API operations cannot perform provider calls, storage reads, full decode or a second media lifecycle.

The approved [finishing boundary](../specs/2026-10-30-media-finishing-boundaries.md), [numeric fixtures](../../engineering/media-finishing-numeric-fixtures.md), [6A plan](2026-10-31-06a-shared-fit-planner.md) and remaining product obligations persist.6B1 is a useful guarded API/domain increment, not finished fitting, mixing or export.6B2 owns actual retimed video/comparison audio, derived line voices and target-specific background beds;6C owns gains/peak protection, preview/mux/captions/exports. No subsequent implementation starts before this increment's two gates.

## Files

- Create `models/finishing.py`: owned fit settings root/version, immutable plan command/line records and separately published immutable plan result (five tables).
- Create frozen additive `alembic/versions/0011_fit_plans.py`; modify only `models/__init__.py` for imports. Never import runtime metadata from the migration or modify frozen0010/earlier migrations.
- Create `dubbing/fit_contracts.py`: bounded strict rational/settings/selected-row command DTOs.
- Create `dubbing/fit_settings.py`: default/current settings and CAS history.
- Create `dubbing/fit_plans.py`: command capture/idempotency, exact currentness/eligibility, bounded summary/detail/history.
- Create `dubbing/fit_execution.py`: command-only `plan_fit` options/input scope, Worker handler, private JSON checkpoint/strict restart validation, short result publisher and currentness guard. Register the real stage in `execution/registry.py`.
- Create `dubbing/fit_snapshot.py` if strict stored-plan decoding/current snapshot checks would otherwise obscure the command service. Keep responsibility focused; do not add an unused abstraction.
- Create `routes/finishing.py`; register in `app.py`. Do not add a render/export stage yet.
- Create `tests/test_fit_settings.py`, `test_fit_plans.py`, `test_fit_plan_migration.py`, `test_fit_plan_postgresql.py`; update exact schema-head inventories only where required.
- Create `docs/verification/task6b1-owned-fit-plans.md` with actual evidence.

## Task1: Versioned exact fit settings

- [ ] Write RED for default revision0 reads with no DB mutation, authenticated project ownership, strict rational DTOs and CSRF/CAS writes. Representative request and expected normalization:

```python
payload = {
    "revision": 0,
    "settings": {
        "mode": "smart",
        "max_audio_speed": {"numerator": 6, "denominator": 5},
        "max_picture_factor": {"numerator": 2, "denominator": 1},
        "max_borrow_ms": 500,
        "max_output_duration_ms": 57_600_000,
    },
}
# PUT /api/projects/{p}/fit-settings -> revision1, immutable version/actor.
# A second write carrying revision0 ->409; GET returns saved exact rationals.
```

- [ ] Implement strict `Rate` with positive actual integer numerator≤4,000,000 and denominator≤1,000,000, canonicalized through Fraction; `FitSettingsBody` has the exact6A fields/ranges and no extras. Reject float/bool/numeric strings/nonfinite before conversion. `FitSettingsPut` contains revision≥0 and settings. Project defaults can be edited before source upload; no source guard is needed merely to change these project settings.
- [ ] Implement owned `FitSettingsState`/`FitSettingsVersion`, with immutable actor/parent/revision/settings/policy history and composite root/current/parent family FKs. First explicit save creates revision1 even when choosing defaults. Later canonical no-op saves may return the existing version without staling plans; document/test that choice. Real changes increment revision. Read default revision0 without inserting a root. Bound history100 and offset; retain old versions.
- [ ] Settings edits affect fit-currentness only. Do not change translations, references, natural outputs, independent QC, provider revisions or their input keys. Gain/subtitle settings do not belong here. Commit the coherent GREEN slice.

## Task2: Owned immutable plans and current selected-row guards

- [ ] Add strict command DTOs using existing `SourceGuard` and row proof names. The following is the public shape; declare all nested models with existing strict bases and bounded IDs/fingerprints/revisions:

```python
class FitRow(Strict):
    id: ID
    expected_source_text_fingerprint: Fingerprint
    translation_revision: ZeroRevision
    selection_revision: ZeroRevision  # natural-audio selection, not root source
    output_id: ID | None
    review_revision: ZeroRevision
    qc_evidence_fingerprint: Fingerprint | None


class FitTrack(Strict):
    tag: str  # resolve then retain the owned canonical catalog tag
    segments: list[FitRow]  #1..1000, global command total<=1000


class FitPlanCreate(SourceGuard):
    settings_revision: ZeroRevision
    purpose: Literal["dub", "incomplete_preview", "original_only"]
    tracks: list[FitTrack]  #0..16; distinct owned canonical targets
```

Apply actual Pydantic length/range/tag validators rather than leaving comments as implementation. Envelope≤4MiB through `BoundedDubbingRoute`; all selected rows across all tracks≤1000; duplicates/aliases resolving to the same target or cell are invalid before partial writes. Original-only requires zero tracks; dub/preview require at least one track and current active transcript. Root selection guard remains required for all purposes. Target source IDs must be currently active, not foreign or historical.

- [ ] RED: capture two targets sharing one actual source and two roles; retain source selection+absolute window, transcript, exact fit settings/policy, canonical target/cell IDs, current source revision/text fingerprint/times/role, translation revision, selected audio root/version/output/SHA/measurement, and listening/evidence guards. Changing a source span, role assignment, selected output, expected wording, settings or a submitted guard before admission must409 without creating partial records. A speaker display-name change alone must not alter the planner role identity.
- [ ] Implement immutable `FitPlanCommand`, `FitPlanLine` and `FitPlanResult` with composite owner/cell FKs for command/run/source/track/segment/source revision/current translation/audio root/version/natural output as applicable. Store every explicitly selected row, including visibly excluded preview rows, with `included` and bounded issue codes. Normal/current selection pointers are never overwritten. All user-supplied IDs/proofs are checked before enqueueing. Record precise command fingerprint and immutable actor; identical admitted command may reuse the existing record/run without duplicating history/events, returning an explicit reuse indication. Clock order must not choose an active plan implicitly; endpoints use explicit owned command IDs. Use durable event admission for meaningful history ordering. Follow existing command/run creation patterns when assigning a nullable run link before the surrounding transaction commits.
- [ ] Capture bounded plain primitive6A inputs only for included current valid natural audio, with track ID/segment ID/role ID and measured duration. Enqueue one `plan_fit` run with command ID, distinct command scope and guarded-command access. Direct arbitrary stage creation is denied. Input capture must not call `build_plan`, `validate_plan`, `plan_json`, storage, media validation or network. Result computation/publication belongs toTask4. Bound the captured snapshot to2MiB separately from its computed plan; reject excess explicitly rather than truncating.
- [ ] Commit after the complete capture/ownership/CAS tests are GREEN.

## Task3: Distinguish dub, preview, original-only and feasibility

- [ ] For `dub`, require each selected target's exact entire current active source-row set, with current valid selected natural audio and `output_assessment.ready` for every row. Reject missing/stale/corrupt/unvalidated/foreign audio, unavailable current wording and listening/issue acknowledgements that are not current. A single accepted row or passing automatic match cannot authorize the whole target. Use visible bounded issue counts/details; no historical-output fallback.
- [ ] For `incomplete_preview`, an explicit subset is allowed. Preserve every requested cell and current selection proof. Fresh valid selected natural audio may be included while waiting for listening/QC acceptance, visibly retaining those issues. Missing/hard-stale/invalid audio is excluded and identified, never played under its old ID. This purpose remains permanently labelled incomplete preview even if all requested rows happen to be ready; a future ordinary render needs a fresh `dub` command. Foreign/cross-cell supplied IDs still reject, rather than becoming a benign omission.
- [ ] For `original_only`, require no target/voice claims. An existing current source selection is enough; transcript may benull. The empty6A plan is an identity map. Expose `dub_ready=false`, never infer that feasibility proves a dub.
- [ ] A natural-length fit failure produces an inspectable plan with `timeline_feasible=false`, exact6A line issues/null fitted endpoints and `render_eligible=false`. It does not truncate the voice, change target words/controls, enqueue shortening or enqueue rendering. Preserve source/target/caption versus actual voice endpoint policies from6A. Ordinary missing readiness is a guarded command error; numerical infeasibility after valid input capture is a stored review result.
- [ ] Test partial preview with different included rows for ZH/JA. Persist per-target included segment IDs, because later background replacement masks must use each target's actual voiced-row union; a union across all targets would remove original dialogue where one target lacks a voice. This task stores those facts but does not create beds.
- [ ] Test every branch with actual validated CPU natural-audio fixture provenance from existing synthesis/QC helpers; recording providers remain test-only. No fake listening acceptance without exercising the guarded manual-review route/service. Commit GREEN.

## Task4: Currentness, strict stored-plan verification and reads

- [ ] Implement `current_plan_state(db,project,record)` that rechecks active source/transcript/selected cell/settings proofs and current ordinary readiness separately from stored arithmetic feasibility. Pending work has no completed map/feasibility and cannot be labelled accepted/rendered. An old complete record may remain historical when source/target/selection/settings/review proof changes; never silently update it. Explicitly report captured purpose, current/stale, timeline feasibility, audio eligibility and issue codes as separate fields. Conservative re-planning after a review-proof revision is acceptable and cheap; it must preserve natural audio and paid QC. Gain/subtitle/display-name edits must not invalidate timing content.
- [ ] Implement the existing Worker/Operations lifecycle for computation. Under short SQL capture plain owned command inputs; outside SQL call `build_plan` and `plan_json`, bounded to2MiB with existing private-operation envelope headroom. Existing6A quality stress reached1,265,679bytes: do not impose a1MiB assumption. Check cancellation/lease before and after bounded calculation. Prepare `provider=cpu,model=shared_fit_v1`, cache the complete validated canonical result before publication and emit safe counts/IDs/planned rational duration only. No media object reservation is needed for JSON. A calculation with fit-limit issues is a successfully computed review result, not fabricated render success.
- [ ] Add strict owned stored-plan decoding before cache reuse/detail/render handoff: parse the canonical exact6A schema with bounded strict numeric types, reconstruct declared dataclasses and run `validate_plan` outside SQL. Verify included cell keys/measurement/times/durations match immutable owned line records and captured settings/source duration; an internally consistent but unrelated/tampered JSON plan is not sufficient. Unknown policy, missing/extra/duplicate line, float/bool coercion, changed origin/output/source hashes and corrupt provenance are visible invalid-plan issues, never a paid fallback. No general parser framework. Cache checks pin the actual producing command/run/current operation/generation, model/policy/input and payload fingerprints. The short publisher compares the already validated payload/fingerprint to its prepared operation and captured command, checks current guards, and inserts the result once; it does not rebuild a full map, read storage or decode media inside SQL.
- [ ] Fault-injection RED/GREEN: cancellation/lease loss during calculation, success cached then publisher failure, source/target/selection/settings/manual-review edit before publication, restart from prepared JSON and duplicate command. Valid prepared success must be recoverable without another remote call (there are none), without altering natural audio/QC and without overriding current manual state. Damaged cache fails visibly, never publishes a forged map. Preserve existing execution defaults and do not create another job/lock/receipt lifecycle.
- [ ] Implement project routes:

```text
GET  /api/projects/{p}/fit-settings
PUT  /api/projects/{p}/fit-settings
POST /api/projects/{p}/fit-plans                 202; command/run capture/reuse
GET  /api/projects/{p}/fit-plans                 summary list, limit<=100
GET  /api/projects/{p}/fit-plans/{plan_id}       owned detail and lines limit<=100
```

Full common-map coordinates are bounded independently by6A's1000lines/partitions and the serialized byte limit; they may be returned with detail. Paginate per-row proofs/issues/history, and do not return100full large plan JSONs in a list query. Summaries should avoid loading all JSON payloads solely to list IDs/counts. No server storage paths/provider URLs/secrets/raw dialogue in events or error details. Authorized line/history information remains project scoped.

Summary projection clarification: do not perform100plans×1000row freshness scans merely to list history. Summaries may expose stored run/status/count/admission and captured mathematical feasibility/duration, but explicitly mark currentness, stored-plan integrity and audio eligibility as`not_assessed` (or nullable with an explicit assessment marker). Never infer current/render-eligible/accepted from stored success alone. Detail and publication are authoritative full checks. Test both the lightweight query and stale/invalid detailed result; the future workbench fetches detail before offering a render action.

- [ ] Record real `finishing.settings_changed`/`finishing.plan_queued`/`finishing.plan_published` events with IDs/purpose/counts/computed feasibility/current issue codes only, plus existing Worker events. No predicted render progress or model use; planned output duration must not be named a measurement. Test cursor replay and duplicate-command event behavior, CSRF, cross-project/workspace, aliases, invalid/paginated detail and unchanged natural/QC rows. Commit GREEN.

## Task5: Frozen schema, actual PostgreSQL and final gates

- [ ] Demonstrate populated0010→0011 upgrade/down/up and metadata parity on SQLite and isolated actual PostgreSQL, preserving old row values. New migration must be frozen/self-contained. Composite ownership probes must update only one foreign owner/cell column or otherwise avoid a unique-key failure masquerading as an FK rejection. Use fresh metadata clones if exercising PostgreSQL `AddConstraint`; do not contaminate existing shared SQLite metadata or weaken old assertions.
- [ ] Test competing settings/CAS, duplicate plan capture and actual Worker result publication with PostgreSQL project locks, without I/O or full-plan CPU computation/validation spanning a transaction. Use bounded inputs and ordinary DB work. Query only owned fixture DBs; keep shared test server alive.
- [ ] Run focused new tests and affected source/translation/synthesis/QC/schema suites. Then freeze source/tests and run one full backend suite with the actual PostgreSQL opt-in. Use owned TemporaryDirectory basetemp and failed-only retention; clean only owned directories. Retain the original full handle until completion; an observation timeout is not a reason to restart it.
- [ ] Run Ruff/format, compileall, offline locked dependency check and whitespace checks. No frontend files means no frontend checks. Record exact RED/GREEN/final commands/stdout/exit with mode600 logs outsideGit, and distinguish pure/domain proof from actual rendering/model/listening/export/deployment acceptance.
- [ ] Self-review, exact scoped commit, clean DONE handoff. Controller dispatches independent SPEC, original actor fixes any findings and same SPEC re-reviews, then distinct QUALITY. No6B2 implementation, protected preview upgrade, actual model call, local model download, push or deployment occurs inside this task.
