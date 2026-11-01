# Video Translate SaaS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking. The user approved design A and continuous full construction on 2026-10-29; no per-task permission check is needed.

**Goal:** Build the complete Video Translate SaaS workflow described in the approved design: remote-model video translation and character-preserving dubbing with all upstream language choices, editable stages, durable retries, background mixing and verified exports.

**Architecture:** React/TypeScript web client; FastAPI project and identity API; PostgreSQL-backed jobs/events/revisions and private S3-compatible storage; independent CPU media worker; Hugging Face-first remote inference adapters. SQLite and filesystem adapters are explicit development/test options, never evidence of deployed SaaS infrastructure.

**Tech Stack:** Python 3.12, FastAPI/Pydantic 2, SQLAlchemy 2, Alembic, psycopg, Argon2, cryptography, HTTPX, boto3, gradio_client/huggingface_hub; React, TypeScript, Vite, Vitest. FFmpeg for CPU media operations only. Dependencies are locked after installation. No AI weights are installed locally.

## Approved steering

- SaaS, not a local browser-only application.
- First exercise real remote APIs; no local model downloads.
- Hugging Face is the primary model ecosystem.
- User-selected integration source: `https://www.youtube.com/watch?v=SIZsFGvtClM`; test English → Mandarin Chinese and English → Japanese through the built product. This replaces the earlier sample-video choice for final integration.
- Complete scope persists across increments; partial green tests do not complete the goal.

## Subprojects and dependency order

These are implementation increments inside one approved product, not scope reductions. Each increment gets its own detailed plan, red/green tests, spec review and code-quality review.

1. **SaaS foundation**: account sessions, workspace isolation, projects, private upload/download, settings primitives, development/production validation. Detailed plan: `2026-10-29-01-saas-foundation.md`.
2. **Durable execution**: job graph, leases/heartbeats, persisted events and reconnect, cancellation, retries, remote-request recovery, revisions and invalidation. Detailed plan is written against increment 1's actual models before implementation.
3. **Cloud providers and language catalog**: full 646-language catalog, aliases/RTL, per-provider capabilities, protected token configuration, connection tests, HF remote adapters, provider error classification. Include the reusable browser login/service setup screen here so credentials can be entered safely before final integration; the full editing workbench remains increment7. No local inference fallback. Detailed plan: `2026-10-29-03-cloud-services-and-setup.md`.
4. **Analysis, cast and translation**: selected audio track/window, cloud separation and timestamped ASR/diarization, editable source segments, speaker/reference management, subtitle import, multi-target translation, glossary/context and locks. Implementation-level ownership/history/time/API boundaries are recorded in `../specs/2026-10-29-dubbing-domain-contract.md`; the detailed execution plan is `2026-10-29-04-analysis-cast-translation.md` and follows the actual cloud-adapter interfaces.
5. **Synthesis and quality**: per-line remote cloning, consistent or per-line references, per-line overrides, incremental cache, independent ASR QC, manual repair, duration planning.
6. **Media finishing**: fixed timing and shared Smart Fit mapping, source-preserving background replacement, gains/limiter, preview, multi-audio MP4, WAV/MP3, SRT/VTT/ASS and hardsubs, final artifact validation.
7. **Web workbench**: login/projects/upload, source/cast/translation editors, waveform timeline, task/event inspection, retries, mixing, download and service configuration; uses actual API state.
8. **Integration and delivery**: security and isolation tests, failure/restart recovery, real HF model run from fresh upload, browser scenarios, locked builds, cloud deployment artifacts, deployment proof when published.

## Stable external contract

- API prefix `/api`. IDs are opaque UUID strings; media URLs are authorization checked.
- Errors: `{"error":{"code":"...","message":"...","retryable":false,"details":{}}}`. Validation errors omit sensitive input values.
- Collection response: `{"items":[],"total":0}`.
- Auth: `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`.
- Auth response: `{"user":{"id":"...","email":"...","name":"..."},"workspace":{"id":"...","name":"...","role":"owner"},"csrf_token":"..."}`. Session cookie is HttpOnly. CSRF token is held in client memory and sent as `X-CSRF-Token` for mutations; reload recovers it from `/auth/me`.
- Projects: `GET/POST /projects`, `GET/PATCH /projects/{id}`, soft delete `DELETE /projects/{id}`.
- Project fields: `id, name, status, revision, source_language, target_languages, source_asset_id, source_track_index, settings, created_at, updated_at`.
- Source upload: `POST /projects/{id}/source`, multipart field `file`, response `{"project":{...},"asset":{...}}`.
- Assets: `GET /projects/{id}/assets`, `GET /assets/{id}/content`; do not return filesystem paths or storage credentials.
- Timeline: `GET /projects/{id}/timeline`; segment edits, speaker edits, reference uploads and language tracks use project-scoped routes defined in the respective increment's contract.
- Operations: `POST /projects/{id}/runs`, `GET /projects/{id}/runs`, `POST /runs/{id}/retry`, `POST /runs/{id}/cancel`.
- Events: `GET /projects/{id}/events` with sequence cursor; SSE endpoint supports `Last-Event-ID`.
- Provider settings: workspace-scoped encrypted credentials, read responses include only `configured`/capabilities/status; separate connection test endpoint.
- Export: creates a durable run, returns artifact URLs only after output validation.

## Verification and evidence

- [x] 1. SaaS foundation tests including cross-user access, CSRF/session expiry and media limits. Independent spec and quality gates passed; see foundation verification.
- [x] 2. Concurrent claims, retry classification, restart recovery and stale-output rejection tests. Both independent gates passed at`652c0ce`; real CPU probe and recording-only remote lifecycle evidence are distinguished.
- [x] 3. Catalog parity, cloud adapter contracts and protected setup. Independent spec and quality gates passed at`67ff839`; five real metadata checks/account authentication are distinct from still-pending inference.
- [x] 4. Multi-speaker edits, reference lineage, translation contexts/locks and selective invalidation tests. Task4C independent SPEC/QUALITY passed through`bdb2e8d`; actual source integration and final exports remain separate. The observed cloud-upload preparation repair precedes task5.
- [x] 5. Line-level cloud request, cache and QC backend behavior. Task5A passed SPEC/QUALITY through`6303ad3`; chat-wait repair passed both through`f93605f`. Task5B corrections at`0a94d55`, evidence at`c0385d8`, passed same-reviewer SPEC120+3+5 and distinct QUALITY46+3, including actual PostgreSQL. Frozen full748 passed. Recording-provider tests are not live inference; actual registered clone/QC/listening acceptance remains item8.
- [ ] 6. Real FFmpeg media fixtures covering overlap, timing, backgrounds, multilingual subtitles and multi-track exports. Pure shared planner6A passed SPEC/QUALITY at`53182a6` (137fresh each, independent240+66 and120families/max-boundary probes). This arithmetic does not close media execution;6B1 now captures owned durable plans, followed by actual6B2/6C rendering/mix/caption/export work.
- [ ] 7. Frontend component tests, strict type check/build and actual browser scenarios.
- [ ] 8. Fresh uploaded video runs through real remote stages and produces verified video/subtitles, with requests/events/artifacts recorded.
- [ ] 9. Complete docs/source map, reproducible containers/migrations and verified deployment state.

## Execution journal

2026-10-29: User approved scheme A. Independent repository created; design committed as `4052288`. Working on feature/cloud-dubbing. Existing media samples remain separate acceptance inputs and will not be passed off as new processing runs.

2026-10-29: Foundation implementation committed as `634d14c`; controller reran the complete suite and observed 87 passing tests. Independent specification and quality reviews are required before marking increment 1 verified. User's new source was resolved through Agent Reach's YouTube/yt-dlp path: IBM Technology, “Agentic Engineering: 5 Terms Every AI Developer Should Know”, 700 seconds, English source track and publisher English subtitles. Source evidence and paired-language acceptance criteria live in `docs/engineering/integration-fixture.md`.

2026-10-29: Foundation spec review found unbounded lists; `b77622f` added validated pagination and24 regressions. Independent spec re-review passed. Quality review reproduced blocking upload ownership SQL on the event loop; `6e7a64c` fixed it and added2 regressions. Independent quality re-review passed: original500ms-delay reproduction now has21ms maximum heartbeat gap and201 upload. Controller independently ran113 tests and a live isolated PostgreSQL14.18 migration/auth/isolation/revision-CAS check. Increment1 is verified within its documented scope; no frontend, remote inference or deployed SaaS is claimed. Increment2 durable execution is now being implemented from its detailed plan.

2026-10-29: Durable execution implemented real worker/probe, persistent runs/attempts/events, exact input invalidation, leases/retries/cancel and remote checkpoints. Independent spec review reproduced two stranded-handle cases after input edits; fixes `195a611`/`363e29c` preserve reconciliation and bounded retry policy. Spec review passed at148tests, with independent live PostgreSQL migration/claim/event-order evidence and separate HTTP API/worker/restart/SSE proof. Separate quality review remains pending; increment2 is not yet marked verified. Cloud service contracts now include reachable HF-hosted NVIDIA diarization and Gradio Demucs alternatives; metadata reachability is not model inference.

2026-10-29: Durable quality review found synchronous SQL inside the async event stream and a stale cache signature after changed-input retry. Fixes `5dfff7d` and `652c0ce` passed independent reproduction: slow-query loop gap525ms→12ms; retry cache reused the current successful run while the original creation key retained409 semantics. Final independent full suite153passed. No review findings remain. Increment2 verified; increment3 begins with full catalog, encrypted cloud settings, adapter contracts and reusable browser login/setup.

2026-10-30: Cloud services/catalog/setup increment passed independent spec and quality reviews at`67ff839`. Controller fresh verification:250 Python tests,22 frontend tests, typecheck/build, Ruff/format/compile/lock all passed. Review fixes include explicit capability/configuration boundaries, NVIDIA submission uncertainty, HF chat-vs-ASR model suffixes, accessible field errors, wrong-type language422, concurrent settings merges, credential-verdict invalidation and rejecting unexpected compression before body decoding. Actual608px browser layout was corrected and verified. The user saved HF credentials through the protected interface; all five real metadata checks were reachable and the three authenticated slots passed account validation, with all inference_verified flags false. No token was copied from chat, no audio inference or deployment performed. Nginx same-origin config is present but syntax/runtime unverified. Increment4 starts with task4A immutable domain/manual editing, followed by real analysis/reference and remote translation tasks in order.

2026-10-30: Task4A manual domain completed and passed independent SPEC/QUALITY at`84dfeff`. Controller fresh303-test suite with live PostgreSQL, lint/format/compile/lock all passed. Immutable source/cast/translation history, guarded manual imports, current-source proof, exact invalidation and active ordering are implemented. The actual user preview remains verified baseline3 and has not been migrated; protected credentials remain untouched. Task4B now begins remote source analysis/reference/workflow integration. Master item4 remains open until4B and4C are complete; no cloud audio inference or final dubbed sample has yet been produced by this product.

2026-10-30: Task4B and four-stem profile passed both gates through`1c1dae8`. Task4C now passed independent SPEC67+3 probes and QUALITY67+3 real PostgreSQL concurrency probes through`bdb2e8d`. Implementer full508backend/no skips and34frontend/type/build/static/lock passed. Item4 implementation/tests closed; live acceptance remains item8. Runtime restart removed temporary preview/key/DB; a fresh persistent preview was created and source SHA matched. Narrow Whisper timing repair passed SPEC37 and QUALITY17 tests, activated only on exact schema0007 composition. The real separation upload hit WriteTimeout before any named inference; repair plan2026-10-30-04b-upload-preparation.md precedes the prepared2026-10-30-05-synthesis-and-qc.md. Items5–9 remain open.

2026-10-31: Task5A and the narrow chat-wait repair passed their independent gates and exact`f93605f`/schema0009 preview activation preserved all existing rows/vault/key. Task5B first SPEC found three real evidence/arbitration/clock defects; original actor fixes`093e328`/`0a94d55` passed the unchanged probes and full748 in776.76s. Same SPEC re-review120affected+3unchanged+5new probes and fresh distinct QUALITY46affected+3new probes passed, no actionable findings. Item5 backend closed; no actual product clone/QC/listening or final outputs claimed. The two original target-context retries still await separate user approval. Media task6 begins with the pure bounded shared planner in`2026-10-31-06a-shared-fit-planner.md`, followed by owned CPU media execution/mix/caption/export increments; no timing arithmetic alone closes item6.

2026-11-01: Owned fit6B1 closes at corrected source`32e9dc2`/actor evidence`81c40f9`: frozen full950, final same SPEC118+3 and same distinct QUALITY96 tracked+5 corrected-loader original probes+3 post-commit probes explicitly PASS. Q1's real write-lock timeout is resolved;21.580s large response/39.121s Worker remain measured latency limits. Root inspected reports and terminal logs. Fresh sole6B2A actor now implements real CPU audio/video primitives from its detailed plan; owned media6B2B and mix/caption/export6C remain required. The user explicitly requires test-video upload/processing and playable original-versus-ZH/JA video comparisons with notification after actual outputs exist. Items6–9 remain open; no final media or deployed service is claimed.

2026-11-01 user steering: the process was too slow and overbuilt; switch to agile delivery. Prioritize the usable upload→translation/dubbing→mix/subtitles→export loop, then complete remaining coverage through short increments. No more long-plan expansion or repeated full backend runs for small changes; use affected checks and focused review, with full regression at integration milestones. The already-running corrected6B2A full run is retained. A frontend project/upload/source/job slice now runs in parallel against already-gated APIs with disjoint web ownership. Detailed future plans remain references, not a requirement to delay the first demonstrable output until every internal hardening item is implemented. Privacy, ownership, current-input publication, paid uncertainty handling and the complete requested product/delivery scope remain intact.
