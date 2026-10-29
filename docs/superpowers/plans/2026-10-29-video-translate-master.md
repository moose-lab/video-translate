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
3. **Cloud providers and language catalog**: full 646-language catalog, aliases/RTL, per-provider capabilities, protected token configuration, connection tests, HF remote adapters, provider error classification. No local inference fallback.
4. **Analysis, cast and translation**: selected audio track, cloud separation and timestamped ASR/diarization, editable source segments, speaker/reference management, subtitle import, multi-target translation, glossary/context and locks.
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

- [ ] 1. SaaS foundation tests including cross-user access, CSRF/session expiry and media limits.
- [ ] 2. Concurrent claims, retry classification, restart recovery and stale-output rejection tests.
- [ ] 3. Catalog parity with upstream set and real provider contract checks.
- [ ] 4. Multi-speaker edits, reference lineage, translation contexts/locks and selective invalidation tests.
- [ ] 5. Line-level cloud request, cache and QC behavior; no synthetic test result presented as inference.
- [ ] 6. Real FFmpeg media fixtures covering overlap, timing, backgrounds, multilingual subtitles and multi-track exports.
- [ ] 7. Frontend component tests, strict type check/build and actual browser scenarios.
- [ ] 8. Fresh uploaded video runs through real remote stages and produces verified video/subtitles, with requests/events/artifacts recorded.
- [ ] 9. Complete docs/source map, reproducible containers/migrations and verified deployment state.

## Execution journal

2026-10-29: User approved scheme A. Independent repository created; design committed as `4052288`. Working on feature/cloud-dubbing. Existing media samples remain separate acceptance inputs and will not be passed off as new processing runs.

2026-10-29: Foundation implementation committed as `634d14c`; controller reran the complete suite and observed 87 passing tests. Independent specification and quality reviews are required before marking increment 1 verified. User's new source was resolved through Agent Reach's YouTube/yt-dlp path: IBM Technology, “Agentic Engineering: 5 Terms Every AI Developer Should Know”, 700 seconds, English source track and publisher English subtitles. Source evidence and paired-language acceptance criteria live in `docs/engineering/integration-fixture.md`.
