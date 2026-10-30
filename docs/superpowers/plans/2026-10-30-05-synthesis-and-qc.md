# Remote line synthesis and independent QC implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development and test-driven-development. One implementer at a time; task5A must pass independent SPEC then QUALITY before5B. Approved continuous construction requires no additional permission. Task4C must pass both gates before either implementation starts.

**Goal:** Produce independently recoverable natural voice clones for every selected target line, with immutable reference/control provenance, measured duration, editable selection and independent recognition evidence.

**Architecture:** Guarded project APIs capture commands; existing independent Worker and PrivateOperation/PreparedObject machinery execute remote calls and persist results before short publication transactions. Natural audio, editor selection, QC and later finishing have separate dependencies. Model inference remains remote; FFmpeg performs only bounded media preparation/validation.

**Tech Stack:** Existing Python3.12/FastAPI/SQLAlchemy/Alembic/HTTPX, Gradio HTTP adapter, HF Router ASR and private storage; CPU FFmpeg. No local inference packages or system voice fallback.

## Actual interfaces and source of truth

- Binding resolution is in `dubbing/references.py`: `effective_voice_inputs(db, project, segment_id)` includes the resolved line-or-role binding and reference dependency snapshot. `binding_for`, `VoiceBindingVersion`, `ReferenceVersion` supply the actual immutable reference; explicit line binding wins. A dormant role must not enter an overridden line's inference identity.
- `providers/omnivoice.py` currently has language-enum mapping, `clone_arguments`, `normalize_result` and convenience submit/poll. Convenience submit/poll wrap too much work for durable publication: the new handler must split metadata/upload, named POST, real event-ID checkpoint, terminal FileData checkpoint and download. Keep existing public helper contracts compatible.
- `execution/prepared.py` exposes `Operations`, `current_operation`, `store_audio`, `publish_objects`; use its generation checks and `execution/prepared_objects.py` reservation/settlement rules. Do not build a second media lifecycle. Network/CPU/storage work occurs outside publication SQL.
- `execution/registry.py` provides command-only stages, scoped output keys and publication guards. `dubbing/remote_translation.py` demonstrates strict private prepared success, separate inference/publication guards and actual remote metadata. Do not depend on a project-wide revision for a line edit.
- `media/audio.py` exposes `validate_audio` (full decode, actual codec/rate/channels/duration/hash) and `extract_audio` (CPU16kmono preparation). Use these instead of trusting a WAV suffix or provider success string.
- `dubbing/translation_contracts.py` and `translations.py` provide current-source guards, target row CAS and manual/approval history. Source/track/row ownership must be rechecked by the new APIs.
- Approved semantics: `../specs/2026-10-30-synthesis-qc-boundaries.md`. Actual short provider diagnostics in `docs/verification/omnivoice-clone-smoke.json` and `hf-clone-qc-smoke.json` establish only a short Chinese path; they are not product-stage or final-video acceptance.

## Task5A: Natural line clones, selection and duration measurements

### Files and responsibilities

- Create `models/synthesis.py`: owned immutable synthesis requests/results and versioned selected natural audio/controls. Root/current pointers and immutable revisions may share a focused module; all cross-domain links use composite owned FKs.
- Create frozen additive `alembic/versions/0009_synthesis.py`; import models in `models/__init__.py`. Migration never imports mutable application model definitions.
- Create `dubbing/synthesis_contracts.py`: bounded explicit selected-row commands, control updates, output selection/review and DTOs.
- Create `dubbing/synthesis.py`: command capture, effective-reference resolution, input identity, publication CAS, output selection/history and measured slot planning.
- Create `dubbing/remote_synthesis.py`: remote metadata/upload/POST/poll/terminal/download/prepared lifecycle; no human-state mutations outside publisher.
- Create `routes/synthesis.py`; register it in `app.py`; register real `synthesize` handler in `execution/registry.py`.
- Extend `providers/omnivoice.py` only for reusable preparation/poll pieces while preserving existing helper behavior. Add exact named-operation schema/control validation where needed.
- Tests: `test_synthesis_domain.py`, `test_synthesis_operations.py`, `test_synthesis_migration.py`, `test_synthesis_postgresql.py`. Verification note: `docs/verification/task5-synthesis-qc.md`.

### Command and read contract

Use `/api/projects/{project_id}/language-tracks/{tag}` as the base. Implement:

```text
POST /synthesize                 explicit current selected source IDs/target row proofs
GET  /synthesis                  paginated current line outputs and outstanding work
GET  /synthesis/{request_id}     command and independent line-run status
GET  /segments/{id}/audio-history  paginated immutable natural outputs/selections
PUT  /segments/{id}/voice-settings  CAS controls revision (null clears override)
PUT  /segments/{id}/audio-selection CAS explicit owned natural-output choice/review
```

The request captures `selection_revision`, `transcript_revision`, canonical target, explicit source IDs/current source-text fingerprints, current translation row revisions and current natural-audio selection revisions. Track defaults and line overrides must be immutable and inspectable. Existing track-level settings may be extended only with typed guards; a free-form project JSON is not an immutable controls history.

- [ ] Write failing API/domain tests before adding routes/models: current owned row enqueues one actual line run; foreign/historical/missing translation or reference does not. Two targets and two speakers bind the correct references; a line override isolates dormant role changes. A reference with staleness/overlap/length warnings requires visible review, and acknowledgement captures its exact version rather than silently accepting another.
- [ ] Implement frozen schema, owned FK/lineage, strict DTOs and guarded commands. Bound selected rows to1000, reads/history to100, controls/text to existing provider limits. Source/target/reference state is captured once under project lock; no server-side inference in the route transaction. Default preserves already chosen/approved natural audio; explicit replacement is audited and still CAS guarded.
- [ ] Write failing tests for the exact inference identity: actual target text, canonical model language, reference audio SHA+immutable corrected transcript/version, effective binding, model/connection revision, validated effective controls. Display names, final gains/subtitle styling and natural timing slot do not trigger another clone. Timing changes still stale references cut from changed source spans. Changed meaning/reference/controls do invalidate only affected target lines.
- [ ] Implement the real command-only per-line stage and immutable request. Use a distinct target/line scope, never one shared target output key. Reject unsupported model/control/language before the named POST; preserve unknown capability visibly. An explicitly bound valid line reference is usable without inventing a speaker.
- [ ] Write failing recording-provider tests for metadata/upload preparation, real POST count, saved eventID immediately after acceptance, restart polling the saved host/prefix/API, saved terminal FileData before download, retryable download failure and successful recovery without a second POST. Public facts/events must contain only IDs/counts/hashes/measured values; no dialogue/reference text/paths/signed URLs/token.
- [ ] Implement the remote handler using the existing network allowlist and vault. Before POST persist exact host, Gradio prefix, named API, metadata revision/schema/language mapping, controls and uploaded reference request. `Done.` is followed by bounded download and `validate_audio`; corrupt/empty/oversized/wrong-container output is rejected. Persist actual measured duration/rate/channels/codec/SHA and full-decode evidence in the private result. No duration estimate can masquerade as a measurement.
- [ ] Write failing fault-injection tests for synchronous/poll completion followed by lost lease, source/target/manual-selection edit, cancellation and publication failure. Prepared success remains reusable for identical inference inputs through a fresh guarded local review; it cannot force a new paid request merely because an editor pointer changed. Unknown POST outcome requires explicit existing acknowledgement, never an automatic retry. Partial batch failure leaves all unaffected line outputs reusable.
- [ ] Implement short publication and immutable output/selection history. A prepared output may be retained historically while a changed editor guard blocks current selection. Explicit same-input regeneration must be distinguishable from default cache reuse and recorded as an actual intentional request. No phase auto-approves listening/QC.
- [ ] Return duration planning as `natural_duration_ms` measured, `slot_duration_ms` current, ratio and `measurement` provenance. A slot change recomputes planning and invalidates later fitting while preserving the same unchanged natural audio. A shortening suggestion or speed-control edit is explicit; no automatic wording/control alteration and no time stretching in5A.
- [ ] Run populated upgrade/down/up/parity/FK rejection on SQLite and isolated real PostgreSQL. Run full backend suite, relevant frontend tests/build if touched, Ruff/format/compile/lock. Record actual RED/GREEN and commit. Independent SPEC then QUALITY, with no successor implementation until both pass.

## Task5B: Independent line recognition QC and human repair

### Current5A integration points

Task5A implementation is committed in`fbc0b76` plus`adca2f4` and remains under independent review at this note's creation. The following names are inspected current interfaces, not permission to skip its gates:

- `models/synthesis.py`: `NaturalOutput` links the exact target/segment cell, validated audio asset/SHA, producing line/operation and measured media properties. `AudioSelection.current_version_id` points to an owned `AudioSelectionVersion.output_id` with its immutable revision/actor/provenance. A source/timing slot is not the selected generated-audio identity.
- `dubbing/synthesis_outputs.py`: `selection_for`/`history`/`current_lines` expose selection revisions and current output; `output_json` explicitly reports `acceptance: not_assessed`.5B adds actual QC/review projection rather than replacing that placeholder with unconditional success. Keep current bounded output/history reads.
- `dubbing/synthesis.py`: `inference_inputs` validates current target wording, effective reference, actual controls and model configuration; `editor_guard` captures source/target/selection/current-control proofs.5B must distinguish comparison/readiness guards from recognition identity, not rerun TTS or ASR merely because a manual pointer changed.
- `execution/receipts.py` is for actual asynchronous event-ID receipts. HF ASR is synchronous and returns no guaranteed provider ID. Do not manufacture a receipt ID or repurpose a source/transcript ID as one. Use the existing private successful-response checkpoint before QC publication.

After5A gates, execute the separately planned bounded chat-response policy and its reviews before5B, as recorded in`2026-10-31-04c-chat-response-budget.md`. Unknown target-context jobs cannot be bypassed by editing their source/context; source-ASR retry approval has already been consumed.

### Comparison and review limits

Normalize with explicit Unicode NFKC/casefold and documented punctuation/separator handling. Preserve meaningful letters and combining-script content. Compare nonempty content; two empty normalized strings must not count as a successful speech match. Cap comparison length/work explicitly before quadratic edit calculations; exceeding the budget yields a visible unavailable/manual-review reason rather than silently truncating and reporting a pass. Word metrics require meaningful tokenization; languages without such tokenization still receive bounded character evidence, not an invented word-accuracy score.

Reference carryover is a warning based on actual unexpected matching phrases, not any shared generic token such as`AI`. Retain the matching evidence privately for authorized review. Missing detected language remainsnull; mismatched or unknown reported language is a review warning at the declared comparison granularity, not a fabricated detection confidence.

Recognition results may be reused for identical selected-audio bytes and verification configuration/preprocessing policy while comparison is recomputed for changed expected wording. A slow result must not approve a newer selection/wording. Manual listening acceptance/rejection has exact current audio/target/source proofs, actor/provenance and immutable history. Audio selection alone remains separate from acceptance. Timing-only changes that preserve the same current natural audio and wording must not trigger a paid recognition call; stale source-derived references remain explicit.

QC may inspect currently selected, owned and validated natural audio even when a subsequent wording edit has made its original synthesis inputs stale. This is necessary to compare unchanged bytes against corrected expected words without another recognition call. Preserve the synthesis/reference staleness separately in readiness; recognizing or manually reviewing those bytes must not silently make the old generation current or unblock an ordinary final export. Invalid measured provenance remains a hard denial before remote recognition.

A current explicit listening acceptance may override automated-QC failure, unavailable/unsupported coverage, unassessed evidence, text mismatch or unknown/mismatched language. Capture acknowledgement of the exact currently shown QC evidence/issues with an evidence fingerprint or equivalent CAS proof and immutable actor/audio/wording/source history. Readiness then reports a manual-review basis and retains the original QC issues; it must not rewrite failed/unknown recognition as successful. New selected audio/meaning invalidates the old acceptance. Missing/foreign/corrupt audio, invalid measured provenance and stale natural/reference/source inputs remain hard readiness blockers. This manual path is necessary for declared languages outside automatic recognition coverage; one accepted row never completes all rows.

The QC evidence proof guards the review write and records what was shown; it is not the listening-acceptance identity. Additional successful QC of unchanged bytes/meaning must not revoke that acceptance. Genuinely new adverse QC issues may require fresh issue acknowledgement for the manual-override readiness basis while the listening record remains current. Expose acceptance, automated evidence/issues and overall readiness separately; none changes the paid recognition identity.

### Files and responsibilities

- Add owned immutable QC request/result/review models in `models/synthesis.py` or focused `models/voice_qc.py`; freeze additive `0010_voice_qc.py` rather than changing0009 after its gate.
- Create `dubbing/voice_qc.py`: current generated-audio/wording proofs, command capture, comparison metrics, guarded publication and manual review.
- Create pure `dubbing/qc_comparison.py`: documented Unicode comparison and bounded edit distance; no confidence or speaker similarity claims.
- Extend `routes/synthesis.py` with QC/review endpoints and `execution/registry.py` with the real independent `voice_qc` stage.
- Tests: `test_voice_qc.py`, `test_voice_qc_operations.py`, migration and real PostgreSQL extensions; update `docs/verification/task5-synthesis-qc.md`.

### API and lifecycle

```text
POST /api/projects/{p}/language-tracks/{tag}/voice-qc
GET  /api/projects/{p}/language-tracks/{tag}/voice-qc/{request_id}
PUT  /api/projects/{p}/language-tracks/{tag}/segments/{id}/audio-review
```

- [ ] Write RED for actual selected generated audio → CPU16kmono preparation → one independent HF ASR request. The request never includes expected target words as a recognition prompt. Assert the exact remote body, canonical language/capability handling and separately saved operation/result. HF's current route has no forced-language argument; absent detected language remainsnull. Unsupported QC must be visible and still permit explicit human review.
- [ ] Implement exact QC inference identity based on generated-audio hash and immutable verification-provider revision; bind expected current wording/selection to comparison/publication separately. A wording correction may reuse identical recognition while recomputing guarded comparison; no duplicate recognition due only to a human approval toggle. Never let an old transcript approve changed current audio or wording.
- [ ] Store raw recognized wording/timestamps privately and return authorized bounded QC detail through project-scoped reads. Use explicit Unicode NFKC/casefold and documented punctuation/separator handling; report normalized character edit distance and word edit distance only where meaningful. Bound input to prevent unbounded quadratic work. Empty/unexpected output and reference-word carryover are review warnings with actual matching evidence, not invented quality probabilities.
- [ ] Write RED/GREEN for failed QC retaining natural audio; retry only QC, cache/restart/uncertain submission, audio selection/manual target changes during recognition, absent detection, CJK/RTL/combining marks, empty response, reference carryover and exact-match counterexamples. Do not label normalized exact match as voice-identity or pronunciation acceptance.
- [ ] Implement immutable actor/current-row-guarded listening acceptance/rejection and manual repair. Editing target/reference/controls, regenerating one line and retrying QC must preserve previous output/history. One accepted line cannot mark the whole target complete; report current selected-row readiness with missing/stale/failed/manual-review issues.
- [ ] Verify owned FK and populated migrations on SQLite/real PostgreSQL; full backend checks and static/locked dependency checks. Record actual commands/results, scoped commit, independent SPEC then QUALITY. Final real model integration occurs through these registered routes after both pass; previous diagnostics remain clearly separate.

## Subsequent increments remain mandatory

Task6 owns overlap-aware fixed/Smart Fit shared video/audio/subtitle/background timing, mix gains/limiter, previews and validated MP4/WAV/MP3/SRT/VTT/ASS/hardsubs exports. Task7 exposes these actual APIs in the workbench. Task8 runs both EN→ZH and EN→JA from the user-selected fresh upload plus broader multi-role and recovery/isolation acceptance. This plan does not mark those deliverables complete.

## Persistent controller integration environment

The earlier `/tmp` preview and source DB disappeared on environment restart. New controller operational state is outside Git in parent `outputs/.runtime/`, with protected directory permissions; media fixture is retained under `~/.agent-reach/fixtures/SIZsFGvtClM`. The reacquired source has the same25,861,753bytes/SHA256 as the original record. Tests use independent disposable directories/databases; do not edit protected integration data or copy credentials into tests/docs.
