# Owned media rendering from an exact fit result Implementation Plan

> **2026-11-01 user steering supersedes the delivery sequence below:** develop in agile usable vertical slices, stop long-plan expansion and repeated whole-backend checks for small changes. This detailed document is contract/reference backlog, not eleven mandatory pre-demo stages. The next actor should deliver the smallest real owned render→mix/caption/export loop, reuse existing persistence where sufficient, and validate the affected behavior; internal tables/module layout may be simplified without dropping ownership, exact map/input proofs, safe recovery, resource bounds or the complete final scope. Full regression belongs at an integration milestone. Do not claim unimplemented hardening or media acceptance as complete.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development and superpowers:test-driven-development. The controller assigns one implementer, then independent SPEC and distinct QUALITY; no parallel implementers. Steps use checkbox (`- [ ]`) syntax. Continuous construction is already authorized, but execution of this plan requires both final 6B2A gates to pass. Do not ask for another execution choice.

**Goal:** Render and privately publish measured source picture, original comparison audio, fitted line voices and target-specific background beds from one exact current owned fit result, with recoverable prepared success and unchanged natural/QC history.

**Architecture:** A guarded API captures an immutable owned derivation and queues one command-only `render_fit` stage in the existing Worker. Full parent-map/evidence validation and all storage/CPU/decode work occur outside SQL; project-locked admission and publication compare current proofs and insert owned rows atomically. A command-local `RenderActivity` wrapper adds throttled compact head checks and aggregate resource supervision without changing RunContext, StageDefinition or remote-stage contracts.

**Tech Stack:** Existing Python 3.12, FastAPI/Pydantic 2, SQLAlchemy 2/Alembic, SQLite/PostgreSQL, private Storage, Worker/Operations/PreparedObject, gated FFmpeg/ffprobe and Rubber Band CPU primitives. No new dependency, model runtime, provider request, object store or job state machine.

---

## Execution prerequisite and scope

At drafting, 6B2A candidate `4522da6b92eb7a437947f6a9fba60d8c23f895ed` and its evidence update were **not** approved to unblock this plan: SPEC requested repairs to aggregate stdout accounting, cancellation after actual completed native blocks with process reap, shared-map target-bed composition, and the failure matrix. The original 6B2A actor owns those fixes. Historical full-suite results in `docs/verification/task6b2a-cpu-media-primitives.md` do not override pending independent gates.

- [ ] Controller records final 6B2A implementation/evidence commit identities and actual SPEC PASS plus distinct QUALITY PASS before assigning implementation here. Re-read its final verification document and public primitive signatures/receipts. If a repaired public contract differs from the signatures below, update this plan before implementation; do not silently adapt around an ungated primitive.
- [ ] Keep this increment restricted to 6B2B. No mix/gains/limiter, caption generation/burn, final mux/export, UI work, protected preview/schema upgrade, real remote inference, upload to a publishing service, push or deployment. 6C and master 7–9, live remote cloned voices, paired-language original-versus-translated delivery and final notification remain required later.

Authoritative inputs: `docs/superpowers/specs/2026-11-01-owned-media-render-boundaries.md`, `docs/superpowers/specs/2026-10-30-media-finishing-boundaries.md`, `docs/engineering/media-finishing-numeric-fixtures.md`, gated 6B1 and final 6B2A verification. The controller already inspected the pinned upstream VoiceStudio export guide through Agent Reach/GitHub at commit `5abc33602d17b81805731717b2a117857a98751c`, `docs/dubbing/export.md`, SHA-256 `43efdff229de391f174ad4e06ab6dacefba4aa198f1c78e2c5189629630dceff`; no new broad research is needed. This is independent SaaS code, not upstream implementation or proof of a delivered dub.

## File map and fixed boundaries

Paths below are relative to the repository root `outputs/video-translate`.

| File | Responsibility |
| --- | --- |
| Create `src/videotranslate/dubbing/render_contracts.py` | Strict public request/options and bounded internal capture/manifest DTOs; code-owned policies and semantic keys. |
| Create `src/videotranslate/dubbing/render_capture.py` | Load owned plain parent/input proofs, pure complete validation, exact compact current-head projection. No media execution or commits. |
| Create `src/videotranslate/dubbing/render_commands.py` | Atomic command admission/idempotency and authoritative detail/summary/artifact pagination. |
| Create `src/videotranslate/dubbing/render_checkpoint.py` | Exact operation/manifest/receipt bindings, compact cache and validated result contract. No SQL or native work. |
| Create `src/videotranslate/dubbing/render_activity.py` | Command-local polling, forced checks, one deadline and owned temporary/frame/byte accounting. |
| Create `src/videotranslate/dubbing/render_execution.py` | Four-stage CPU graph, input materialization/recovery verification, prepared writes and short publisher. |
| Modify `src/videotranslate/models/finishing.py` | Exactly four render relations described below and parent supporting unique keys. |
| Modify `src/videotranslate/models/analysis.py`, `models/synthesis.py`, `models/dubbing.py` only for required supporting unique keys | Enable precise producer/asset/selection/output family FKs; do not change old field semantics. |
| Create `alembic/versions/0012_fit_renders.py` | Frozen additive schema, supporting keys and downgrade; never edit 0011 or earlier. |
| Modify `src/videotranslate/execution/prepared.py` | Narrow typed-file store and object-ID publisher, preserving legacy wrappers and exact legacy metadata. |
| Modify `src/videotranslate/execution/registry.py` | Register `render_fit`; no generic active hook or changes to existing registrations. |
| Modify `src/videotranslate/config.py` | Explicit administrator capacity settings, captured into commands. |
| Modify `src/videotranslate/dubbing/analysis.py` | Add optional materialization check callback with unchanged default behavior for existing callers. |
| Modify `src/videotranslate/routes/finishing.py`, `dubbing/fit_plans.py` | Render endpoints and two additive parent-result detail fields only. |
| Create `tests/render_helpers.py` | Small real media, valid test-provider lineage and ready owned parent fixtures, isolated from production. |
| Create `tests/test_render_contracts.py`, `test_render_admission.py`, `test_render_activity.py`, `test_render_prepared.py`, `test_render_execution.py`, `test_render_recovery.py`, `test_render_api.py`, `test_render_migration.py`, `test_render_postgresql.py` | Contract/domain, real graph, lifecycle, SQL-boundary and migration evidence. |
| Modify `tests/test_fit_plans.py`, `tests/test_config.py` | Additive parent-detail compatibility and capacity configuration regressions. |
| Create `docs/verification/task6b2b-owned-media-render.md` | Actual RED/GREEN, media/transaction/resource/recovery/migration/final evidence. |

Do not add another cache table, mutable export project state, generic graph executor, per-line kind vocabulary, or a runtime metadata import in a frozen migration. `models/__init__.py` already imports finishing; no new registration is necessary if the four classes stay there. `execution/prepared_objects.py` needs no manifest-format change: retain its exact top-level `objects` list. Do not refactor media primitives during this increment unless a newly discovered defect goes back through their owner/gates.

## Contracts the implementation must preserve

### Purpose, source coordinates and exact identity

- `dub`: inherited parent purpose must be `dub`, parent feasible/current, all current requested rows of every selected target present and accepted/usable under existing `current_plan_state` and `output_assessment` semantics. Missing/stale/corrupt/listening/acknowledgement failures reject admission and publication.
- `incomplete_preview`: inherited purpose must match. Keep every parent requested row/exclusion and each target's own included source mask; render only included valid captured voices. It never becomes a dub. Empty voice sets remain explicit. Each requested target still gets its own bed; an empty included union preserves working source speech throughout.
- `original_only`: inherited zero-target identity parent, source picture and working original comparison only; no instrumental requirement or target/voice/readiness claims. A transcript may be absent, following the parent contract.
- Keep 6B1 `render_eligible` ordinary-dub-only. Render API returns separate `purpose`, `current`, `allowed_to_render`, `status` and captured/result validation fields.
- The source selection is absolute relative to the common source clock; FitPlan line/map/placement coordinates and working/stem windows are selection-relative. Never add selection start to a natural-line onset or apply it twice to working audio. Capture audio ordinal, track ID, absolute start/end and parent source duration.
- Signature covers canonical parent result/producer/map identity, source/stem/natural input proofs, all masks/purpose, exact CFR/crossfade/renderer policy and captured administrator limits. It excludes display labels, project revision, mix gain and subtitle style. Record actor separately; identical complete derivation reuses one command/run and first actor history. A changed capacity capture is a new immutable command, not a retry mutation.

### Relational ownership inventory

All four new tables use existing `Owned`, owner constraints and bounded fields. Each JSON snapshot/receipt has an explicit serialized bound and strict validation; JSON IDs never replace necessary family FKs.

| Relation | Required columns and constraints |
| --- | --- |
| `FitRenderCommand` / `fit_render_commands` | `parent_result_id`, `parent_command_id`, `parent_run_id`, `parent_operation_id`, `parent_fingerprint`, `source_asset_id`, `source_selection_id`, `source_track_id`, `run_id` nullable only during atomic admission, `signature`, `purpose`, `actor_id`, `admission_sequence`, `line_count` requested rows 0..1000, `included_count` 0..line_count, `target_count` 0..16, `input_count` 2..1003, `snapshot`. Unique project/signature and run ID; family unique `(id,parent_result_id,parent_command_id,project_id,workspace_id)` and `(id,run_id,project_id,workspace_id)`. Parent result FK includes its command/run/operation, not only its ID. Snapshot is fixed header/policies/limits and compact heads, not another full map. |
| `FitRenderInput` / `fit_render_inputs` | `command_id`, parent result/command IDs, semantic key, kind `source/working/instrumental/natural`, `asset_id`, `source_selection_id`, nullable `source_track_id`, nullable `working_asset_id/instrumental_asset_id`, nullable `fit_line_id/track_id/segment_id/output_id`, nullable `analysis_media_id/producer_run_id/producer_operation_id/prepared_object_id`, captured SHA/byte size, bounded proof JSON/fingerprint. Unique command/semantic key. Natural shape requires all cell fields and exact parent FitPlanLine/output/asset family; media shape requires the exact AnalysisMedia/selection/producer/asset family; source shape has source asset and no invented cell/stem. Supporting family unique `(id,command_id,project_id,workspace_id)` and natural `(id,command_id,fit_line_id,track_id,segment_id,output_id,project_id,workspace_id)` for artifacts. |
| `FitRenderResult` / `fit_render_results` | `command_id`, `run_id`, `operation_id`, `generation`, parent result/map fingerprint, manifest fingerprint, artifact/voice/bed counts, bounded measured summary. Unique command ID; command/run and operation/run/generation family FKs, plus result/command/operation owner-family unique for artifact linkage. Never overwrite on failed retry. |
| `FitRenderArtifact` / `fit_render_artifacts` | `result_id`, `command_id`, `operation_id`, `prepared_object_id`, `asset_id`, semantic key, kind `fit_video/fit_original/fit_voice/fit_background`, type `float_wav/video_mp4`, primary `input_id`, nullable `secondary_input_id` (instrumental, beds only), nullable track/segment/fit-line/output IDs, voice-only canonical rational `placement_start_ms` and `audio_speed` (null for other kinds), one bounded metadata envelope containing receipt/provenance, metadata fingerprint. Unique result/semantic key, result/object and result/asset. Result/command/operation family; primary and secondary input/command families; PreparedObject/operation/asset family; voice input/cell/output family. Bed CHECK requires secondary input, source/video/original/voice forbid it. Bed receipt binds both working/instrumental input IDs and exact target mask; source/video and original identities are separate. |

Add only referenced supporting unique keys: FitPlanResult's `(id,command_id,run_id,operation_id,project_id,workspace_id)`; FitPlanLine's `(id,command_id,track_id,segment_id,output_id,project_id,workspace_id)`; NaturalOutput's output/cell/audio-asset family; AnalysisMedia's ID/run/selection/working-asset and ID/run/selection/instrumental-asset families; SourceSelection's ID/track family and SourceTrack's ID/source-asset family; PrivateOperation's ID/run/generation family; PreparedObject's ID/operation/asset family. Use the separate nullable `working_asset_id`/`instrumental_asset_id` columns on render input to reference the corresponding AnalysisMedia key, with a CHECK tying the one present to `asset_id`. Do not use a generic asset ID that a same-project unrelated stem can satisfy. Natural alias `output.operation_id` and actual producer origin operation are distinct and both must be captured/validated through `synthesis_cache.validate_output_evidence`/`cached_payload`.

For source/selection consistency, command has composite selection/track and track/source-asset FKs. Add its supporting `(id,source_selection_id,project_id,workspace_id)` family key for every input and `(id,source_selection_id,source_track_id,source_asset_id,project_id,workspace_id)` for the source input. The source input binds `asset_id` to that last source-asset position. Thus source/selection/track cannot drift independently within a project. AnalysisMedia input FKs include the same source_selection_id. Validate the parent command capture has exactly that source chain before admission; no existing fit record is rewritten. Enforce all-null/all-present nullable families with CHECK constraints; SQL composite FKs with a NULL component alone do not enforce that shape. Freeze column order and named constraints before writing mutation probes. Command snapshot/compact heads are bounded to2MiB; each input proof to8KiB; each artifact metadata envelope to160KiB; result summary to64KiB. Input proof stores IDs/measurements/canonical evidence hashes, not raw provider terminal URLs, dialogue, credentials or full producer payloads. All1000 requested rows must fit actual maximum-ID serialization fixtures without truncation.

### Prepared metadata and checkpoint

New typed files use a separate code-owned descriptor; legacy `store_audio` metadata remains byte-for-byte shape-compatible with `synthesis_cache.py:87–103`.

```python
# New typed PreparedObject.metadata_json; paths are never serialized.
{
    "media_type": "float_wav",       # or video_mp4
    "kind": "fit_voice",             # allowlisted kind/type pairing
    "measurement": finished.metadata(),
    "provenance": {
        "command_id": command_id,
        "parent_result_id": parent_result_id,
        "parent_fingerprint": parent_fingerprint,
        "semantic_key": semantic_key,
        "input_fingerprint": input_fingerprint,
        "renderer_policy": "owned_fit_render_v1",
    },
}
```

Descriptor type binds float WAV to `audio/wav`, safe `audio.wav`, 48 kHz stereo IEEE float32 codec/container and measured sample/peak receipt; video MP4 binds `video/mp4`, safe `video.mp4`, video-only H.264/yuv420p and the exact CFR/frame receipt. Validate actual gated metadata container/codec strings, never client MIME/extensions. Preserve finite peak >1.0. Each object envelope ≤160 KiB with each CPU receipt ≤65,536 bytes; counts and fixed-size provenance prevent unlimited accumulation. `FinishedAudio.metadata()` has the seven AudioFile measurement fields plus `sample_count`, `peak`, `receipt`; current codec/container are `pcm_f32le`/`wav`. `VideoFile.metadata()` contains SHA/bytes/duration/codec/container/width/height/frame_rate/frame_count/receipt; current codec/container are `h264`/`mov,mp4,m4a,3gp,3g2,mj2`, and receipt rationals use `[numerator, denominator]`. Do not invent a CPU `full_decode` field that its returned schema does not contain: verify bytes through the actual gated decode path and bind that validation in the owned envelope. Revalidate these exact schemas after6B2A gates.

```python
# Render operation prepared_payload: default 2 MiB, no map/receipt duplication.
{
    "binding": {
        "command_id": command_id, "command_fingerprint": signature,
        "run_id": run_id, "operation_id": operation_id,
        "generation": generation, "input_fingerprint": dependency_fingerprint,
        "parent_result_id": parent_result_id, "parent_fingerprint": parent_fingerprint,
        "renderer_policy": "owned_fit_render_v1",
    },
    "objects": object_ids,
    "manifest": [
        {"object_id": object_id, "semantic_key": semantic_key,
         "input_id": input_id, "metadata_fingerprint": metadata_fingerprint}
    ],
    "manifest_fingerprint": manifest_fingerprint,
    "summary": measured_summary,
}
```

`objects` and manifest IDs are unique and set-equal. Stable keys are `video`, `original`, `voice:<fit_line_id>`, `bed:<track_id>`, maximum 80 ASCII characters. At most 1018 artifacts = 1000 included voices + 16 beds + original + video. Inputs max 1003; excluded requested rows stay in the immutable parent capture and compact head guard, not fake media inputs. Original-only has exactly two inputs/artifacts. Payload ≤2,097,152 serialized UTF-8 bytes with `allow_nan=False`; facts/summary ≤65,536. Check exact keys/types, canonical hashes, manifest cardinality derived from the validated parent, and complete expected semantic set. No partially published success or overwritten same-kind voice. Parent result contains the authoritative map once; per-object metadata binds receipt and proof by canonical hash.

## Task 1: Strict DTOs, parent-result handoff and fixture contracts

**Files:** Create `dubbing/render_contracts.py`, `tests/test_render_contracts.py`, `tests/render_helpers.py`; modify `dubbing/fit_plans.py`, `tests/test_fit_plans.py`. All source paths have prefix `src/videotranslate/`.

- [ ] Write behavioral RED for strict request normalization, all eight CFR choices, forbidden numeric coercion, inherited purpose and no client input/mask/limit override. Start with this complete public DTO shape:

```python
from fractions import Fraction
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .contracts import Fingerprint, ID, Strict

class RenderRate(Strict):
    numerator: Annotated[int, Field(ge=1, le=120000)]
    denominator: Annotated[int, Field(ge=1, le=1001)]

    @model_validator(mode="after")
    def allowed(self):
        value = Fraction(self.numerator, self.denominator)
        allowed = {Fraction(n) for n in (24, 25, 30, 50, 60)}
        allowed |= {Fraction(n, 1001) for n in (24000, 30000, 60000)}
        if value not in allowed:
            raise ValueError("Unsupported render frame rate")
        self.numerator, self.denominator = value.numerator, value.denominator
        return self

class RenderCreate(Strict):
    parent_result_id: ID
    expected_parent_fingerprint: Fingerprint
    purpose: Literal["dub", "incomplete_preview", "original_only"]
    frame_rate: RenderRate
    crossfade_ms: Annotated[int, Field(ge=0, le=100)] = 0

class RenderOptions(Strict):
    command_id: ID
```

Reject crossfade greater than half any target's merged included interval during capture validation; never clamp it. Original-only requires crossfade 0 because no bed is rendered. A numerator/denominator may canonicalize an equivalent permitted fraction; bool/float/string may not. Internal capture DTOs use strict IDs, SHA-256, positive bytes, actual integers and exact rational fields; reuse existing bases without forcing a 1000-entry nested object through an unbounded recursive traversal.

- [ ] Run `PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest tests/test_render_contracts.py tests/test_fit_plans.py -q`. Establish callable/type scaffolding first so the meaningful RED is rejected/accepted-value or missing response-field behavior, not only import failure.
- [ ] Add `result_id` and `payload_fingerprint` to fit detail. Both null when pending; preserve historical result ID if malformed; fingerprint only after strict map/checkpoint/summary validation succeeds. Stale but valid parent can expose both identities while remaining noneligible. Do not change list `not_assessed` or old `render_eligible` semantics. Add assertions for pending/current/stale/corrupt and unchanged existing fields:

```python
assert pending["result_id"] is None and pending["payload_fingerprint"] is None
assert valid["result_id"] and valid["payload_fingerprint"]
assert stale["result_id"] == valid["result_id"] and stale["current"] is False
assert corrupt["result_id"] == valid["result_id"]
assert corrupt["payload_fingerprint"] is None and corrupt["render_eligible"] is False
```

- [ ] Define reusable test fixture contract `render_ready` in `tests/render_helpers.py`: returns `(client, csrf_headers, project_id, parent_detail)`, with four-second actual source video/audio, current owned working/instrumental, two source roles, real generated natural WAVs, valid synthesis producer/alias/measurement lineage, accepted listening through existing guarded route, and published smart-fit parent. Recording separation/synthesis adapters stay test-only and return actual generated media, never production fixtures. Reuse `dubbing_helpers`, `test_synthesis_operations.install_clone`, `test_fit_plans.listen` patterns and `media_fixtures`; expose `ready_render_fixture(..., targets, purpose, source_offset_ms, accepted)` as the factory for explicit variants. No protected customer source. Test fixture construction separately before render assertions.
- [ ] GREEN the exact command, review the focused diff and make one coherent scoped commit when assigned actor execution is permitted. No commit or implementation is authorized by merely writing this plan.

## Task 2: Four owned relations and frozen 0012

**Files:** Modify `models/finishing.py` and only supporting-key declarations in `models/analysis.py`, `models/synthesis.py`, `models/dubbing.py`; create `alembic/versions/0012_fit_renders.py`, `tests/test_render_migration.py`.

- [ ] Write `test_populated_0011_up_down_up_and_exact_render_family_fences`, parameterized `sqlite/postgresql`. Start at frozen `0011_fit_plans`, populate source/analysis/natural/fit families and unrelated same-project, other-project and other-workspace neighbors. Assert old values survive up/down/up, exactly four tables are added, metadata parity and migration self-containment. RED must be a missing relation/acceptance of a wrong family against a callable schema candidate.
- [ ] Run `VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest tests/test_render_migration.py -q`. Confirm the administrator endpoint is the controller's fixture-only test service before execution; absence is a blocker, not a passing skip. Never substitute the retained application database.
- [ ] Implement the relation inventory above with existing SQLAlchemy patterns. A representative required composite constraint is:

```python
ForeignKeyConstraint(
    ["parent_result_id", "parent_command_id", "parent_run_id", "parent_operation_id",
     "project_id", "workspace_id"],
    ["fit_plan_results." + key for key in
     ("id", "command_id", "run_id", "operation_id", "project_id", "workspace_id")],
    name="fk_fit_render_parent_result",
)
```

Use frozen literal tables/columns in 0012, `down_revision="0011_fit_plans"`, and SQLite batch alters where supporting unique constraints require them. Downgrade removes render relations before supporting keys, leaves old records untouched, and never edits 0011. Avoid mutating global metadata to accommodate PostgreSQL cycles; tests use fresh MetaData clones.
- [ ] Probe parent/cell/output/asset/selection/analysis producer/operation/generation/result/artifact/input families independently. Each mutation changes one FK column on a row chosen to avoid an unrelated unique violation. PostgreSQL asserts SQLSTATE `23503` **and intended constraint name**; SQLite asserts FK failure. Shape CHECK tests separately assert null-family and purpose/count restrictions. Example:

```python
with pytest.raises(IntegrityError) as error, engine.begin() as db:
    db.execute(inputs.update().where(inputs.c.id == natural_input_id)
               .values(output_id=other_cell_output_id))
assert error.value.orig.sqlstate == "23503"
assert error.value.orig.diag.constraint_name == "fk_fit_render_input_natural"
```

- [ ] GREEN both backends and the old `tests/test_fit_plan_migration.py` / `tests/test_prepared_lifecycle_migration.py`; commit only schema/model/tests slice. Record supporting constraints actually added, not a broad speculative key inventory.

## Task 3: Plain capture, strict validation, atomic admission and purpose policy

**Files:** Create `render_capture.py`, `render_commands.py`, `tests/test_render_admission.py`; modify `routes/finishing.py` for POST entry point; use Task 1 DTOs and Task 2 models.

- [ ] Write behavioral RED `test_exact_current_parent_and_owned_inputs_admit_once`, `test_changed_parent_or_cell_has_no_partial_command`, `test_preview_masks_and_original_only_are_not_dubs`, and `test_strict_map_validation_outside_sql_then_fresh_atomic_capture`. POST request:

```python
c, h, p, parent = render_ready
body = {
    "parent_result_id": parent["result_id"],
    "expected_parent_fingerprint": parent["payload_fingerprint"],
    "purpose": parent["purpose"],
    "frame_rate": {"numerator": 30, "denominator": 1},
    "crossfade_ms": 0,
}
first = c.post(f"/api/projects/{p}/fit-renders", headers=h, json=body)
second = c.post(f"/api/projects/{p}/fit-renders", headers=h, json=body)
assert first.status_code == second.status_code == 202
assert first.json()["id"] == second.json()["id"]
assert second.json()["reused"] is True
```

- [ ] Run `PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest tests/test_render_admission.py -q`; record absent/rejected capture or duplicate result as RED.
- [ ] Implement `load_render_candidate(db, project, body)` returning plain capture (no commit), `validate_render_candidate(candidate)` returning a fully validated immutable value outside SQL, and `admit_render(db, project, body, validated, actor_id)` performing fresh locked checks/inserts. Route owns transaction boundaries: authorized short read → end read → pure validation → expire/reload and fresh `project_for(...,write=True)` → full current guard plus exact candidate proof comparisons → command/inputs/immutable input facet/run/event → one commit → expire/re-authorize/reload authoritative response. Never call `fit_plans.detail()` inside admission; it commits at `fit_plans.py:491`.

Capture and validate actual parent result/command/run/current operation/generation, `validate_stored`, `validate_summary`, actual prepared checkpoint map equality/fingerprint/canonical facts, and all original parent rows. Capture source Track audio ordinal and asset/selection chain. Working comes only from current `analysis.media_for(...,"extract")`; instrumental only from current `media_for(...,"separate")` for target-bearing renders. Validate AnalysisMedia's selected producer, operation, PreparedObject/Asset relation, measurement/type and exact source selection. Natural inputs come only from included parent rows and `validate_output_evidence`; capture both current output operation and actual origin operation for cache aliases. Do not do storage I/O while capturing DB proofs.

Under the admission lock run existing full parent current/eligibility checks and compare immutable row/proof fingerprints to the validated candidate. The fingerprint comparison may serialize bounded metadata; it may not rerun exact fit arithmetic. Candidate changes reject 409 and rollback every insertion; no retry silently swaps parent or audio. Bound snapshot and each proof before persistence. Use canonical full signature, server-generated input semantic keys, and `finishing.render_input:<command_id>` as the immutable command facet. Add existing applicable source and producer facets to the render run dependency capture; missing optional keys remain explicit capture facts, not fabricated InputState writes.

- [ ] Cover corrupted result/checkpoint/summary/natural proof, similar-duration wrong map, wrong same-project cell/stem/selection/operation, ordinary missing/stale/unaccepted rows, explicit preview exclusions, zero-target original-only, infeasible parent, archive and post-read race. Original-only needs no separation result. Preserve all natural/listening/QC/source rows by before/after snapshots. Non-original preview with no included voice still requires the captured bed inputs but uses an empty replacement union. Crossfade validity is checked against merged original included intervals, not borrowed or mapped endpoints.
- [ ] GREEN admission tests and old fit/admission suites. Commit the coherent guarded admission slice only after it works with the command stage registration from Task 7; until then keep task-local registry tests explicitly injected and never expose a production handler stub as working rendering.

## Task 4: Typed prepared files without legacy metadata drift

**Files:** Modify `execution/prepared.py`; create `tests/test_render_prepared.py`. Reuse `prepared_objects.py` unchanged unless a demonstrated narrow regression requires the controller's review.

- [ ] Write RED `test_two_fit_voice_objects_publish_by_object_id`, `test_typed_video_and_float_wav_have_exact_safe_asset_metadata`, and `test_manifest_is_all_or_nothing_and_old_audio_shape_unchanged` using two real small WAVs with different hashes plus one tiny MP4. Existing kind-key publication must demonstrably fail the two-voice identity assertion before the new path is used.
- [ ] Run `PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest tests/test_render_prepared.py tests/test_synthesis_cache_provenance.py -q`.
- [ ] Implement an internal frozen `PreparedMediaFile(path, media_type, kind, measurement, provenance)` descriptor, `store_media(context, operation_id, descriptor)` and `publish_object_map(db, run, object_ids, expected_metadata)` returning object-ID→asset-ID. Descriptor accepts only code-owned type/kind pairings and measured gated result metadata. Shared internal reservation/storage/settlement code may be extracted, but public old `store_audio(...)` and `publish_objects(...)` signatures/return behavior and exact old metadata stay unchanged.

```python
published = publish_object_map(db, run, [voice_a_id, voice_b_id], expected_metadata)
assert set(published) == {voice_a_id, voice_b_id}
assert published[voice_a_id] != published[voice_b_id]
assert legacy_record.metadata_json == legacy_audio.metadata() | {"kind": "natural_audio"}
```

Reserve before storage, put outside SQL, settle in `finally` even when write fails or lease expires. Prevalidate complete IDs/set/count and all loaded rows before Asset insertion; operation/project/workspace/state/write_settled/delete_pending/generation/type/kind/metadata hash must match. Never use ad hoc kind strings containing segment IDs. Asset safe filename/MIME comes from type, not metadata supplied by the client. Final publication relies on outside-SQL actual media validation and short metadata CAS, not decoding files within the transaction.

- [ ] Test duplicate/missing/extra objects, same-project wrong operation, wrong kind/type/MIME/codec, un-settled/deleting objects and tampered metadata reject without any successful manifest/partial Asset rows. Existing synth/QC/analysis caches remain valid including exact metadata-key validation. Test a storage exception after partial bytes followed by settlement and collectable orphan.
- [ ] GREEN typed tests plus `test_analysis_execution.py`, `test_analysis_quality_fixes.py`, `test_synthesis_cache_provenance.py`, `test_synthesis_alias_recovery.py`, `test_voice_qc_operations.py`; commit this backward-compatible slice.

## Task 5: Compact exact currentness and command-local activity checks

**Files:** Add compact-head functions to `render_capture.py`; create `render_activity.py`, `tests/test_render_activity.py`. No changes to `execution/context.py`, `execution/worker.py` or StageDefinition fields.

- [ ] Write RED `test_thousand_ready_cells_use_bounded_head_queries`, `test_activity_poll_is_throttled_and_forced_edges_are_fresh`, `test_dual_qc_heads_do_not_hide_adverse_result`, `test_override_shadowing_and_display_name_do_not_spuriously_stale`. Build **1000 ready populated cells** with valid selections/reviews/natural proofs, not 1000 missing-audio preview rows. Set-based loading may use fixture-only batched inserts preserving complete valid families; acceptance assertions must still exercise full existing parent guards.
- [ ] Run `PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest tests/test_render_activity.py -q`. Count statements using SQLAlchemy engine events and measure actual locked transaction duration; no mocked statement counts.
- [ ] Implement `load_render_heads(db, project, command)` as bounded set-based projection and `render_heads_current(...)` exact comparison. Fetch all requested parent rows, including excluded preview rows; complete active-source membership for dub; track active state; source revision/archived/current selection/transcript/settings; translation revision/state; selected audio version/output/revision; latest review; resolved binding/reference and effective controls; current synthesis connection revision/config; exact selected extract/separate media/asset/producer and their dependency validity. Use per-query joins or fixed 250-row chunks to remain inside supported bind limits. At 1000 rows allow at most 80 SQL statements for one complete projection including lease/project lock checks, and require no linear per-cell `capture_row`, `output_assessment`, `cached_payload` or `inference_inputs` calls during polling. Record real elapsed time; preserve default DB timeout and repeat real competing writes instead of changing timeout to meet the bound.

Projection semantics must match actual mutations, not guessed facets:

| Mutable fact | Existing coverage and exact guard |
| --- | --- |
| Source/selection | `source.video`, `.selection`, `.audio_track`, `.window`, `.transcript`; additionally compare actual row chain. |
| Source rows | `segment.<id>.text/timing/voice`, current revision ID, archived and active-set membership. Transcript ID alone misses within-transcript additions/edits. |
| Target/translation | `target.<tag>.active/mode/context/glossary`, `translation.<tag>.<segment>`; text facet omits revision ID, so compare actual parent revision proofs. Do not invalidate for unused context/display metadata alone. |
| Natural selection/listening | `select_output` and `put_review` have no mutable readiness InputState; compare their actual immutable heads/revisions/acknowledgements. |
| QC | Immutable `voice_qc.input:<digest>` and distinct run output facets do not update the fit dependency. Select latest applicable request and latest applicable **conclusive result** independently by command admission sequence/line ID, using the exact proof-applicability exclusions in `voice_qc.current_qc_evidence`. Include each run's status. A new result for an older admitted request changes evidence without changing max admitted sequence. |
| Natural effective input | Resolved `voice.line:<segment>` discriminator plus winning line/role binding/reference dependencies; effective override values and synthesis connection revision/config. A shadowed role/default edit must not invalidate a line override. VoiceSettings writes no InputState facet. |
| Settings/stems | Exact default-absent or current fit settings version; `output.extract`/`output.separate` and exact current successful producing media. |

Keep exact 6B1 QC semantics: pending alone may not introduce an acknowledgement risk, but full qc-evidence fingerprint includes latest request/status and can stale the parent. Do not optimize to a risk-only/ready-only fingerprint. A newer pending request cannot hide older adverse conclusive evidence. Display-name edits, unrelated track/control edits shadowed by explicit overrides, mix gain and subtitle style are not render inputs. Do not compare Project.revision/event_sequence globally.

- [ ] Implement command-local `RenderActivity(context, command_id, captured_heads, limits, directory)` with `check()` and `force()` methods. Every callback checks stop/deadline/local aggregate capacity; only every ≤1 second does it invoke existing `context.check_active()` and a short fresh project-locked compact guard transaction. `force()` always checks both. On head mismatch persist `run.is_stale=True` before raising CancellationRequested so Worker finalizes stale and ordinary GC can retire it. Exiting a transaction by raising before commit must not lose that marker.

```python
# Contract exercised with fake monotonic time AND real fresh SQL heads.
activity.force()
for _ in range(200):
    activity.check()
assert guard_calls == 1
clock.advance(1.0)
activity.check()
assert guard_calls == 2
change_selected_audio_through_route()
with pytest.raises(CancellationRequested):
    activity.force()  # no wait for the next cadence
```

The clock/counter/mutation names in this snippet are test-local helpers: inject monotonic function into RenderActivity, count calls around actual `load_render_heads`, and use existing audio-selection route with current guards. Real tests also cancel during a multi-block CPU operation: detect actual block progress, issue cancel in a second client, assert observation within one polling interval plus measured current-query/process-reap duration, and no surviving child or publication. Forced checks run before/after every materialization, CPU call, store/settlement, cache operation and just before final publisher. Existing `RunContext.check_active` remains unchanged for every old caller.

- [ ] GREEN exact facets, same-text reapproval, review change, all relevant QC state transitions, new active source row, fit first-default save, stem selection/producer change and false-positive exclusions. Compare compact guard outcomes to full parent currentness on this mutation matrix. Commit only after no differing acceptance remains.

## Task 6: Captured aggregate command budget and bounded checkpoint

**Files:** Modify `config.py`; extend `render_activity.py`, `render_contracts.py`; create `render_checkpoint.py`; extend `test_render_activity.py`, `test_render_contracts.py`; modify `tests/test_config.py`.

- [ ] Write RED `test_many_voice_calls_share_one_deadline_and_temp_budget`, `test_materialized_inputs_and_native_stdout_are_counted`, `test_1018_object_checkpoint_uses_default_two_mib_limit`, `test_invalid_checkpoint_receipts_or_generation_are_rejected`. Measure exact serialized UTF-8 bytes at maximal ID/key/hash lengths, 1000 voices/16 beds/original/video. Include a near-2 MiB parent map to demonstrate it is referenced rather than copied.
- [ ] Run `PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest tests/test_render_contracts.py tests/test_render_activity.py tests/test_config.py -q`.
- [ ] Add administrator settings: `render_max_input_bytes` default 512 MiB/max128 GiB, `render_max_output_bytes` default1 GiB/max128 GiB, `render_max_temporary_bytes` default8 GiB/max512 GiB, `render_max_wall_seconds` default3600/max86400, `render_max_video_frames` default216000/max3456000. All positive; captured validated actual integers. Environment-string parsing follows existing Settings conventions, but bool/nonfinite/programmatic invalid values fail. Public RenderCreate cannot override these. Capture one limits policy in the request signature, immutable on retry. If a worker is configured more restrictively, enforce the minimum without silently claiming larger capacity; fail MEDIA_LIMIT when the capture cannot be executed. Do not change old 64 MiB audio defaults.

One command start/deadline spans materialization, all CPU helpers, hashes/decode, stores and recovery verification; each helper receives current remaining limits. Count all files recursively under the command's owned temp directory, including source/working/stem inputs, retained outputs, nested helper intermediates and subprocess stdout. Track peak resident temporary bytes, cumulative materialized/prepared bytes, elapsed monotonic time and frames. Count files once by filesystem identity when hard-linked; reject external/symlink paths. Preflight expected writes against remaining global capacity and per-file caps; periodic callback observes growth. Release each owned output after validated store when no subsequent operation needs it. Do not reset a deadline or allocate a fresh full temporary allowance per line.

```python
assert checkpoint["objects"] == [entry["object_id"] for entry in checkpoint["manifest"]]
assert len(set(checkpoint["objects"])) == 1018
encoded = json.dumps(checkpoint, sort_keys=True, allow_nan=False).encode()
assert len(encoded) <= 2 * 1024 * 1024
assert "plan" not in checkpoint and "pieces" not in checkpoint
```

- [ ] Implement `validate_render_checkpoint(payload, binding, expected_manifest, metadata_by_id)` as a pure bounded exact-schema validator and `ValidatedRenderResult(StageResult)` carrying checkpoint fingerprint, manifest metadata fingerprints, validated parent identity and summary. Per-object receipt lives in PreparedObject metadata and later artifact row; checkpoint binds its hash, not a second copy. Reject bool/int confusion, noncanonical rationals, wrong purpose/policies/counts, bad receipt/metadata fingerprints and missing/extra keys. Parent map and every full CPU receipt remain outside operation payload. Keep `Operations.cache` default limit; do not use plan_fit's 64 KiB headroom exemption.
- [ ] GREEN single-command wall/temp/frame exhaustion across many small calls and small-byte max-count fixtures. Record measured actual receipts/capacity failures. Commit coherent resource/checkpoint slice.

## Task 7: Real CPU graph, recovery and short publication

**Files:** Create `render_execution.py`, `tests/test_render_execution.py`; modify `execution/registry.py`, `dubbing/analysis.py`, `tests/test_analysis_execution.py`; use Tasks 3–6 modules.

- [ ] Write RED `test_owned_overlap_graph_renders_and_downloads_exact_common_map`, first asserting actual output bytes/sample/frame/marker values from callable missing-behavior scaffolding. No fake path/result object counts as real rendering. Run `PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest tests/test_render_execution.py -q` and preserve the failed measurement/assertion.
- [ ] Register only `render_fit` with command options, command scope suffix, command-only admission, handler, full publication guard and publisher. `resolve_inputs` validates exact immutable command/current parent; a stale retry cannot rebind new selected inputs or recalculate parent. Use `Operations.prepare(provider="cpu", model="owned_fit_render_v1", connection_revision=0, host="", prefix="", request_payload=small_exact_binding)`. No submission/remote ID. Direct generic `/runs` creation rejects `COMMAND_REQUIRED`.
- [ ] Implement the four CPU stages using gated signatures below; parent `validate_stored` yields one exact FitPlan outside SQL. Materialize owned input assets using bounded hash verification outside SQL with the command activity callback. Add keyword-only `check=None` to `analysis.materialize`; resolve `check = context.check_active if check is None else check` and call it at the existing chunk boundary. Existing callers keep exact behavior; the render passes `activity.check` explicitly. Add regression assertions for both default and supplied callbacks. Do not globally throttle RunContext or introduce a context proxy.

```python
# Signatures to revalidate after final 6B2A gates; all exact Fraction values.
video = retime_video(source_path, video_path, source_sha256=source_sha256,
    absolute_start_ms=start_ms, absolute_end_ms=end_ms, plan=plan,
    frame_rate=frame_rate, limits=remaining_limits, check=activity.check)
original = retime_audio(working_audio, plan, original_path,
    limits=remaining_limits, check=activity.check)
voice = fit_voice(natural_audio, voice_path, speed=placement.audio_speed,
    limits=remaining_limits, check=activity.check)
bed_source = build_background(working_audio, instrumental_audio, bed_source_path,
    source_duration_ms=plan.source_duration_ms,
    dialogue_intervals=target_included_original_intervals,
    crossfade_ms=crossfade_ms, limits=remaining_limits, check=activity.check)
bed = retime_audio(bed_source, plan, bed_path,
    limits=remaining_limits, check=activity.check)
```

Names in this contract are local variables from the captured owned command/validated map and unique command-local paths. Recompute remaining limits immediately before **each** call. Force activity on both sides of every call. Graph order is video, original comparison, included fitted voices, per-target backgrounds; store each validated final output through `store_media`, then unlink only its no-longer-needed local file. Do not concatenate voices; persist mapped onset, declared speed and measured shorter duration. Bed source intervals use that target's included original starts/ends, never all-target union, mapped spans or borrowed endpoints. All original/bed outputs share parent fingerprint. Preserve bed_source.metadata() inside the final bed provenance alongside working/instrumental input IDs and included-mask fingerprint, then the final retime receipt separately inside final measurement. Its source SHA must equal the measured transient bed source SHA. This retains both composition and retiming evidence after the transient file is removed, with two separately bounded CPU receipts and no map duplication. Artifact secondary_input_id binds the instrumental input to the same command; runtime checks enforce the expected input roles. No automatic gain/normalizer/caption/mux or provider callback.

- [ ] Validate gated `FinishedAudio.metadata()` and `VideoFile.metadata()` receipts: audio sample count/rate/channels/finite peak/hash/bytes/full decode, planned endpoint vs measured sample rounding, DSP approximation policy/error bounds separate from authoritative map; video source hash/absolute selection/common origin/exact rate/ceil frame count/padding policy/codec/dimensions/full decode. Keep natural files/output measurements/QC immutable. Store command input linkage and parent map in the provenance wrapper; do not claim the CPU receipt by itself proves ownership.
- [ ] Cache the exact compact manifest and truthful facts after all expected typed outputs settle; return `ValidatedRenderResult`. Publisher rechecks full current parent eligibility plus exact selected source/stem proofs under the existing project lock, compares prepared checkpoint/object metadata fingerprints against the validated result, calls object-ID publisher, inserts one result and complete artifact set, then existing service writes output facet/status. No map rebuild, storage, CPU or decode in SQL. A duplicate publication must verify/reuse the same complete result or reject mismatch, never append half a second manifest. Run `.commit()` only at existing service/route boundaries.
- [ ] GREEN initial real graph plus ordinary/preview/original-only/empty masks and no-model assertions. Commit complete functional rendering stage, not a production stub.

## Task 8: Numerical graph fixtures and end-to-end authorized downloads

**Files:** Extend `tests/render_helpers.py`, `tests/test_render_execution.py`; create `tests/test_render_api.py`.

- [ ] Add RED cases that fail if original/bed use identity timing, if voices concatenate, if a shared map is replaced by separate target maps, if preview uses all-target removal, or if a tail/last picture is missing. Generate tiny actual WAV/video fixtures in owned temp directories; import gated marker/color measurement helpers instead of widening tolerances.
- [ ] Run `PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest tests/test_render_execution.py tests/test_render_api.py -q` and retain exact failing measurements before fixes.
- [ ] Implement missing graph/manifest wiring only; retain this acceptance matrix:

| Fixture | Exact assertion and actual measurement |
| --- | --- |
| Two roles overlap | Source0–4, A0–2 natural3 s, B1–3 natural4 s; map `(0,0),(1,1.5),(2,3.5),(3,5.5),(4,6.5)`. Picture195 frames at30 fps; original/each bed312000 samples at48 kHz; A onset0/duration3, B onset1.5/duration4. A stays shorter than its3.5 s mapped slot. |
| ZH/JA shared selection | Source rows0–2 and3–4; ZH natural3/1 s, JA4/1 s. ZH-only5 s/onset4; JA-only6 s/onset5; both6 s/onset5 for both. Parent fingerprints differ. Reusing5 s ZH bed in6 s result rejects. |
| Voice speed/pitch/tail | Natural2.5 s, declared5/4 speed gives96000 samples/2 s, same pitch and preserved final marker; speed1 gives120000 samples. Natural SHA and QC/selection rows unchanged. |
| Target beds | Working source dialogue marker + distinguishable instrumental; overlapping original spans merge once, no notch at internal overlap. Differing ZH/JA masks replace only own union. Compose bed through nonidentity shared plan and measure interior, gap and tail markers against exact map. Empty union retains working speech. |
| Picture clock | Absolute offset selection distinct from fit-relative zero, common delayed-video/audio clock, between-frame first/last source IDs, VFR and all eight CFR choices. Last picture retained; frame count `ceil(Fraction(output_ms)*fps/1000)`; endpoint padding <1 frame. |

Audio marker onset/end tolerance stays gated ≤60 ms, declared sample endpoints ≤1 sample; exact sample count when gated fixture proves it. Video identity uses actually decoded source centroids and source PTS, with gated codec classification bound and at most one output grid cell for timing; never use loose RGB distance as permission to choose a different frame. Reuse final 6B2A policies if its repairs tighten these assertions; no relaxation here.

- [ ] Exercise real HTTP POST→Worker→prepared storage→published artifacts→`GET /api/assets/{asset_id}/content` and decode the downloaded bytes. Verify Content-Type, SHA, byte count and authorized vs other-workspace/deleted-project access. Two fit_voice artifacts have same kind, different semantic/cell IDs and separately downloadable asset IDs. No response exposes local/storage/provider URLs. Recording-provider calls used to construct valid fixtures are reported as test doubles; after render admission set every provider adapter entry point to raise so CPU/recovery cannot call it.
- [ ] GREEN matrix with recorded measured values, not only fixture expectations; commit integration tests and narrowly required fixes.

## Task 9: Recovery, transaction exclusion and competing publication races

**Files:** Create `tests/test_render_recovery.py`, `tests/test_render_postgresql.py`; extend existing new modules only where RED requires it.

- [ ] Write RED for valid prepared restart with zero CPU calls; corrupted cache/metadata/owned bytes; lost lease before/during storage; put-after-GC-delete; failed store/failed delete; cancellation/deletion/settings/review/QC edits after the last successful poll; postcommit response head refresh. Use event/barrier synchronization, not timing sleeps as proof of a race.
- [ ] Run `VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest tests/test_render_recovery.py tests/test_render_postgresql.py -q` on isolated fixture databases.
- [ ] Implement recovery by short-load of exact operation/checkpoint/object metadata, then pure binding checks and actual owned storage bytes/hash/full media validation outside SQL. Use one-at-a-time materialization/release under the command budget; do not keep1018 files locally. Validate the exact parent and expected manifest against captured input/receipt proof, even if cache claims success. Then final guarded publication uses the validated result, with all CPU render functions patched to raise in the restart test:

```python
for name in ("retime_video", "retime_audio", "fit_voice", "build_background"):
    monkeypatch.setattr(render_execution, name, forbid_cpu)
assert Worker(c.app.state.settings).run_once()
detail = c.get(f"/api/projects/{p}/fit-renders/{command_id}").json()
assert detail["status"] == "succeeded" and detail["artifact_count"] == expected_count
assert provider_calls == 0 and render_calls == 0
```

`forbid_cpu` raises AssertionError and counts any invocation; fixture counters are reset after preparing the original private success. Recovery may inspect/decode bytes but may not regenerate them. Corrupt recovery returns visible configuration/invalid-media failure and no new published result, not provider fallback. Crash before cache may restart CPU; old settled objects stay orphan-owned/collectable, not called resumable partial output.

- [ ] Preserve lifecycle tests: reservation is created before put; settlement survives lost lease and records late-byte tombstone/delete_pending; published assets always protected; exact `objects` manifest protects current prepared success; unused/old generation orphans collect; GC storage deletion runs outside SQL and remains workspace-scoped/fair. Detecting stale heads commits `is_stale`; idle cache may conservatively stay protected until full currentness is assessed. Do not expand GC into 1000 full proof walks per object or prematurely delete an idle recoverable cache. Explicit retry with changed current parent rejects instead of rewriting immutable inputs/generation to a new derivation.
- [ ] Instrument transaction presence at `validate_stored`/complete map validator, storage open/put/delete, hashing/full decode and every native helper; assert no active SQL transaction during any. The project-locked publisher may compare bounded proof hashes but must never invoke complete map arithmetic or byte operations. Run real settings and name edits concurrently with a1000-ready-row admission/response, and review/QC edits between final callback and `finish_run`: settings/review/adverse or exact pending-proof change suppress publication, name edit does not. Postcommit response uses `expire_all` and fresh authorization, including deletion between commit/read. Full current/eligibility guard is mandatory even if compact polls passed. If1000-ready-cell contention exposes repeated immutable/current-proof loads, batch/prefetch those records for the render guard while retaining every existing comparison and pure evidence validator; do not drop checks, substitute the compact poll for final eligibility, alter old remote contracts, or increase timeout/row limits to pass.
- [ ] GREEN new lifecycle/races plus existing `test_analysis_execution.py`, `test_analysis_quality_fixes.py`, `test_analysis_review_fixes.py`, `test_fit_admission.py`, `test_voice_qc_arbitration.py`, `test_synthesis_alias_recovery.py`; commit the recovery/race slice with exact observed results.

## Task 10: Read APIs, bounded summaries/artifacts and truthful events

**Files:** Complete `render_commands.py`, `routes/finishing.py`; extend `tests/test_render_api.py`.

- [ ] Write RED for CSRF/ownership, summary query projection/pagination, corrupt-vs-stale authoritative detail, private download IDs, safe events and idempotent admission events. Public endpoints are:

```text
POST /api/projects/{project_id}/fit-renders                         202
GET  /api/projects/{project_id}/fit-renders                         limit1..100
GET  /api/projects/{project_id}/fit-renders/{render_id}              authoritative detail
GET  /api/projects/{project_id}/fit-renders/{render_id}/artifacts    limit1..100
GET  /api/assets/{asset_id}/content                                existing authorized bytes
```

- [ ] Run `PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest tests/test_render_api.py tests/test_fit_plans.py -q`.
- [ ] Implement list projection using command/run/result summary columns only. Return `current=None`, `currentness="not_assessed"`, `validation="not_assessed"`, nullable `allowed_to_render`, captured purpose/counts and explicit historical result summary. Do not load100 maps or metadata blobs to list100 commands. Detail independently reloads/validates immutable capture/result/checkpoint outside SQL and current proofs; status success never implies currentness. Artifact pages expose one bounded receipt per row with `asset_id`, semantic key, kind/type, cell/target, exact onset/speed/input identity and captured hash/measurements. Maximum page100, offset≤10000000, no all-artifact JSON embedded in summaries.
- [ ] Emit only actual causal events: `finishing.render_queued`, `finishing.render_started`, `finishing.render_video_ready`, `finishing.render_original_ready`, bounded voice/bed count milestones, `finishing.render_validated`, `finishing.render_published`, alongside existing run failure/cancel/stale. Use short lease-guarded event transactions outside CPU/storage. Counts reflect successfully validated/stored work; no events per sample, no fabricated percent/ETA/cost. IDs/purpose/policies/map/manifest fingerprints/bounded measured durations/counts/error codes only; no text/path/filter/provider secret. Reused admission emits no second queue event. Do not return an unsanitized native exception.
- [ ] GREEN event cursor replay, response size/pagination, auth and historical invalid/current separation. Commit complete API/read slice.

## Task 11: Frozen verification and independent gates

**Files:** Create `docs/verification/task6b2b-owned-media-render.md`; implementation actor may create ignored mode600 evidence under `var/task6b2b/`. No other product scope.

- [ ] Run all new focused tests and affected CPU/domain/execution/storage/API suites, including original 6B2A failure repairs and old synth/QC exact metadata tests. Fix only demonstrated failures and repeat affected checks. Record RED→GREEN commands/assertions, fixture/output hashes, actual decoded measurements, versions, query counts/latencies, forced-edge races, resource receipts, final candidate identity and owned evidence paths. Never present missing native/runtime/PG capabilities as passing skips.
- [ ] Freeze source/tests. Create a private `var/task6b2b/check.py` runner with this behavior: accept label then pytest arguments, launch `.venv/bin/python3.12 -m pytest`, supply a fresh owned TemporaryDirectory `--basetemp`, stream stdout to a mode600 label log, record argv/exit/duration, remove only that owned directory on success and retain it on failure. The parent directory is mode700. Do not copy secrets/environment values to logs. Use the same runner for final focused record and **one** full backend execution; retain the process handle until it reaches a terminal result, without starting another full run after a waiting timeout.

```text
VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src:tests .venv/bin/python3.12 var/task6b2b/check.py focused tests/test_render_contracts.py tests/test_render_admission.py tests/test_render_activity.py tests/test_render_prepared.py tests/test_render_execution.py tests/test_render_recovery.py tests/test_render_api.py tests/test_render_migration.py tests/test_render_postgresql.py -q
VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src:tests .venv/bin/python3.12 var/task6b2b/check.py full-backend -q --tb=short
.venv/bin/ruff check src tests alembic
.venv/bin/ruff format --check src tests alembic
.venv/bin/python3.12 -m compileall -q src tests alembic
uv lock --check --offline
git diff --check
```

Both final invocations include the fixture administrator opt-in; zero skipped PostgreSQL cases are required. If source/tests change after freeze, document the cause and establish a new frozen validation candidate deliberately; do not quietly reuse a full result from the old tree. No frontend changes means no frontend run.

- [ ] Verify final report explicitly distinguishes real generated CPU rendering/owned publication/download from test-double provider setup, subjective audio acceptance, final exports and deployment. Record receipt limits, actual budgets/default capacity failure, scope of SQLite/real PostgreSQL tests and absence of SQL during full validation/media operations. State remaining 6C/7/8/9 obligations.
- [ ] Actor self-review against the checklist below and scoped commit/handoff to controller. Controller dispatches fresh independent SPEC; original actor fixes findings and same SPEC re-reviews; then distinct QUALITY. Do not begin 6C or describe 6B2B as gated until both final gates pass. This plan document itself provides no pass/approval.

## Coverage checklist for controller and fresh actor

- [ ] Exact parent/result/current source/natural/stem producer families and additive parent IDs: Tasks1–3.
- [ ] Three inherited purposes, original/relative clocks, per-target exclusion masks and immutable idempotency: Tasks1,3,7–8.
- [ ] Same prepared lifecycle, safe typed WAV/MP4, legacy exact audio metadata, same-kind identity and atomic complete manifest: Tasks4,7,9.
- [ ] All requested rows, actual facet gaps, dual admission-ordered QC heads/status and override shadowing, bounded polls/forced edges/full final guard: Task5 and9.
- [ ] Captured global deadline/temp/input/output/frame capacity, measured receipts,1018 objects/default2MiB without map duplication: Task6.
- [ ] Actual video/original/voices/target-bed shared-map graph and numeric/pitch/tail/frame/download measurements: Tasks7–8.
- [ ] Prepared restart with actual owned-byte validation but no render/provider recall; lost lease/late-write/GC/deletion/cancel/after-poll races and no long SQL: Task9.
- [ ] Populated frozen0012 migration, precise FK classification and actual PostgreSQL contention: Tasks2,9,11.
- [ ] Summary not_assessed, separate authoritative history/currentness, artifact pagination, safe private media/events: Task10.
- [ ] Focused RED/GREEN, frozen one-full backend/static evidence, final independent SPEC then distinct QUALITY, remaining product scope: Task11.
