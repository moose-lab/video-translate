# Cloud Services and Protected Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with test-driven-development. Execute continuously after durable execution passes independent spec and quality gates. Steps use checkbox syntax.

**Goal:** Deliver the complete upstream language catalog, protected cloud credentials and service selection, tested remote-adapter contracts, and a working browser setup screen that the later dubbing workbench reuses.

**Architecture:** Keep remote service clients separate from pipeline domain handlers. Workspace-owned settings and immutable connection revisions identify the exact endpoint/model used by a run; encrypted credentials remain server-only. The first React screen supplies real account login and cloud setup, so credentials can be entered safely while subsequent pipeline work proceeds. All inference remains remote.

**Tech Stack:** Existing Python/FastAPI/SQLAlchemy/HTTPX/cryptography, a small WebSocket client dependency if needed, React/TypeScript/Vite with locked pnpm dependencies and Vitest/Testing Library. Metadata and frontend dependencies are allowed; no torch, transformers, local ASR/TTS packages, or model weights.

## Existing execution boundaries

`StageDefinition` has an options validator, dependency resolver, handler and optional transactional publisher. `RunContext` exposes source access and durable begin/record remote submission checkpoints; saved IDs must resume their original remote request. `set_inputs` maintains exact project keys; revision alone is not cache validity. This increment does not register incomplete translation/synthesis stages. Low-level adapters normalize real provider contracts; subsequent domain increments bind them to runs and timeline rows.

## File map

- `languages/catalog.py`, `languages/data/catalog.json`, `languages/data/manifest.json`: pinned646-language metadata plus Auto, aliases/variants/direction and provenance.
- `models/providers.py`, migration`0003_cloud_services.py`: workspace credentials, current slot connections and immutable connection revisions.
- `providers/vault.py`: Fernet encryption with a server-side derived purpose/workspace-bound key and strict payload ownership checks.
- `providers/contracts.py`: typed capabilities, requests/results, adapter failure categories and explicit async-resume support.
- `providers/settings.py`: safe serializers, slot validation, revision CAS, defaults, immutable revision retrieval and input invalidation.
- `providers/network.py`: HTTPS/host policy, bounded streaming, safe redirects/credentials and mapped errors.
- `providers/hf_router.py`: official HF ASR and OpenAI-compatible chat contracts.
- `providers/gradio.py`: explicit Gradio4/7 upload, named-call submit and saved-ID SSE polling.
- `providers/omnivoice.py`, `providers/demucs.py`: exact model requests and output normalization.
- `providers/nvidia_stream.py`: HF-hosted NVIDIA English file ASR+diarization protocol.
- `routes/languages.py`, `routes/providers.py`: authorized settings/check APIs and bounded catalog access.
- `web/`: React application, shared API/auth modules, accessible login and service setup screens, language picker and component tests. Later workbench increments extend these files.
- `tests/test_languages.py`, `test_provider_settings.py`, `test_provider_network.py`, `test_provider_adapters.py`: metadata, tenancy, credentials, transport and response contracts.
- Update app/config, project language validation, package locks, README/.env.example and engineering sources/evidence.

## Language contract

Parse the official Apache-licensed OmniVoice language table at commit `08be0b4ccbac3e13e374e86fbfead4b4cac343e2`; the already inspected source is in the parent work/video-translate-research/omnivoice/docs/languages.md. It contains646 distinct names/IDs and ISO639-3 mappings. Every normalized name→ID pair matches the pinned VoiceStudio map at `5abc33602d17b81805731717b2a117857a98751c` (zero differences). Preserve this complete set and source hashes in the manifest; do not copy upstream application code.

Each language exposes `code,name,iso639_3,aliases,direction,variants,is_auto`. Auto is source-only. Support exact canonical names, ISO aliases and explicit common/native aliases; ambiguity is rejected. Preserve BCP47 variants (`zh-Hans`,`zh-Hant`,`en-US`,`en-GB`) separately from the canonical synthesis ID. Never truncate three-letter IDs. Direction is `ltr`, `rtl` or `auto` when script metadata is unknown; actual text controls use `dir=auto` and isolated labels. Include Hebrew/Arabic/Persian/Urdu and CJK regression cases.

Preserve the exact upstream model parameter name, including Unicode normalization form; normalize lookup keys separately. A visually identical normalized name can fail a strict Gradio language enum. Test all catalog model names against the pinned source set, including combining-mark names.

`GET /api/languages?q=&include_auto=true&limit=100&offset=0` returns `{items,total,upstream}` with bounded search≤100chars, limit1..1000, offset≥0. The dataset is bounded at647; catalog availability is distinct from provider stage coverage. Project create/PATCH normalizes accepted names/codes/variants, rejects unknown targets/Auto targets and duplicate normalized target tags. Existing valid project field shape remains unchanged.

## Settings and credential contract

Five connection slots: `separation`, `transcription`, `translation`, `synthesis`, `verification`. A current connection belongs to one workspace/slot and has revision, adapter, endpoint/Space ID, model, strongly typed nonsecret controls, credential reference and check state. Every accepted settings edit appends an immutable connection revision. A remote run can therefore retrieve its original endpoint/model after a later edit. Credentials are independently rotatable and are never copied into revision JSON.

Use one shared `huggingface` workspace credential for HF adapters; an optional slot-specific credential can serve an explicitly configured OpenAI-compatible translation service. All credential/connection references enforce matching workspace in queries and database constraints. Encrypted payloads bind workspace and purpose; wrong-workspace ciphertext swapping fails. Return only `configured`, revision and timestamps. Do not return a token prefix, suffix, hash, plaintext or ciphertext. Rotation preserves cached audio; endpoint/model/controls changes update the appropriate `provider.{slot}` input fingerprint and invalidate only dependent runs.

```text
GET /api/provider-settings
PUT /api/credentials/huggingface    {revision,token?:SecretStr,clear?:bool}
PUT /api/providers/{slot}          {revision,adapter,endpoint?,space_id?,model?,controls,credential_ref?}
POST /api/providers/{slot}/check   {revision}
```

Revision0 creates a missing record; stale writes return409. Omitted token keeps the old secret; empty token is invalid; clear and token together are invalid. Clearing is an explicit user action. Every mutation requires CSRF; reads/checks are workspace-scoped; foreign records are404. Validation, error messages and logs never echo secret inputs.

Read-only settings may include validated preset descriptions without creating records on GET. Selecting/saving presets writes the actual five connections; it does not start inference. A check performs bounded metadata/health and credential validation only. Report separately `reachable`, `credentials_valid` (nullable when untested/not needed), declared capabilities, check time and `inference_verified=false`. A successful whoami or schema fetch must not be called a successful model run. If settings/credential revision changes during a check, the old result cannot overwrite current status.

## Task 1: Complete catalog and behavior tests

- [ ] Write RED tests for count647/646 targets, unique canonical IDs, manifest provenance/parity, normalization, preserved variants, Auto rejection for targets, search/bounds, RTL and CJK.

```python
def test_catalog_keeps_full_set_and_variant():
    assert len(all_languages()) == 647
    assert resolve_language('cmn').canonical_code == 'zh'
    assert resolve_language('zh-Hant').tag == 'zh-Hant'
    assert resolve_language('ja').model_name == 'Japanese'
    assert resolve_language('kbt').canonical_code == 'kbt'
```

- [ ] Run `uv run pytest tests/test_languages.py -q`, observe missing behavior, then implement the pinned resource/parser and API/project normalization. Tests run offline against committed metadata, never download models or depend on upstream availability. Record GREEN and commit.

## Task 2: Vault, connection revisions and protected APIs

- [ ] Add RED tests for secret encryption at rest, cross-workspace read/write/ciphertext swapping, CSRF, revision conflicts, clear/keep/rotate, safe serializers/errors, immutable old endpoint retrieval and dependency invalidation limited to changed service controls.
- [ ] Use cryptography's established Fernet + purpose/workspace-bound key derivation; server secret has existing production entropy validation. Do not invent encryption algorithms. Store workspace/purpose inside authenticated encrypted payload too. Document server-key rotation/re-encryption requirements. No secret in browser persistence, API response or event.
- [ ] Implement the three provider tables, self-contained additive migration, typed settings service and routes above. A connection revision stores only normalized nonsecret settings. Config changes serialize project invalidation in consistent project-ID order; credential-only edits do not mark audio stale. Probe remains unaffected by any model setting.
- [ ] Default presets: HF-hosted Demucs, NVIDIA English ASR+diarization, HF-router chat, official OmniVoice and HF-router Whisper QC. Defaults are selectable experimental services, with their real duration/auth limits. Missing required HF token is explicit configuration state, not a successful check.
- [ ] Run settings and foundation/execution tests, migration parity, then commit.

## Task 3: Remote transport and provider contracts

- [ ] First write HTTPX MockTransport/WebSocket recording-server tests for exact requests and outputs. These are transport contract doubles, never evidence of model inference. Cover authentication failure,429/quota, pending/heartbeat/error/complete SSE, interrupted POST, resume by saved ID without re-submit, malformed/oversized response, missing audio, unsupported language, wrong host/redirect and credential leakage.
- [ ] Enforce HTTPS, no userinfo/fragments, trusted hosts and public IP resolution. Default only official HF router/API hosts and validated `*.hf.space`; other hosts require administrator environment allowlisting. Do not allow arbitrary user URL fetches. Follow redirects only after validating each destination, with no Authorization forwarding across origins. Never log complete headers, provider bodies or signed URLs. Bound response/file sizes, timeouts and text lengths. No implicit retry of an ambiguous POST.
- [ ] Implement typed capability results: supported/unsupported/unknown language per stage, declared versus actually tested, duration limits, available controls and resume/cancel support. Unsupported controls/languages fail explicitly; no engine/language substitution.
- [ ] HF router: `https://router.huggingface.co/v1` chat completions and official ASR contract with return_timestamps. Translation accepts stable segment IDs and validates exact output IDs/types/language; ASR validates actual chunk times, never invents speaker labels. Synchronous APIs with no pollable ID are explicitly nonresumable. Preserve real request IDs only when returned; do not fabricate provider IDs from local IDs. Later run handlers must durably cache successful synchronous results before publishing, or enter uncertain review after loss.
- [ ] Gradio: metadata detects API prefix; current OmniVoice uses `/gradio_api`, Demucs4 uses empty prefix. Multipart `/upload` returns service file paths kept internal. POST `/call/{api_name}` returns event_id; GET the same saved ID until terminal SSE. Validate terminal body and copy permitted output media into bounded temporary streams/files; service paths never become local paths. No `file://` fetch. Actual audio integrity is verified by later media/domain handlers.
- [ ] OmniVoice exact endpoint `/_clone_fn`, ordered args `text,lang,ref_aud,ref_text,instruct,ns=32,gs=2.0,dn=true,sp=1.0,du=null,pp=true,po=true`. Pass canonical language NAME from catalog. Require audio FileData plus successful status; queue completion alone is insufficient. Expose only supported controls. Attach model provenance/use metadata (official pretrained model is research/noncommercial); do not claim commercial readiness.
- [ ] Demucs preset `kajise/Demucs_v4-FT_2s`, `/predict(audio)` returns Vocals/Instrumental; upload + named call + saved-ID polling. Keep two stems distinct with actual file metadata. Do not treat the original soundtrack as a separated background.
- [ ] NVIDIA preset `nvidia/nemotron-diarization`: check health/config; English file route `/api/diarization/file/stream`,16kHz mono PCM16, ≤120s, frames≤64KiB. Send start/await ready/binary/end; require final result and normalize actual speaker/timestamp segments. Streaming has no durable poll ID; declare nonresumable, loss after submission is reviewable uncertainty. Do not silently use multilingual live route with its30-second limit. No audio padding/primer or scripted speaker assignment. Future domain code determines source window and role editing.
- [ ] Add OpenAI-compatible chat adapter reuse for a configured approved host, with the same strict segment response validation; no mandatory OpenAI dependency/account. Run contract suite, Ruff/compile and commit.

## Task 4: Reusable browser auth and cloud setup

- [ ] Resolve maintained React/Vite/TypeScript/test versions and lock pnpm dependencies. Current verified metadata: React19.3.1, Vite8.3.5 (Node≥22.12 supported), pnpm9.12.2. Use compatible maintained versions and actual official APIs, not guessed future syntax.
- [ ] Create `web/package.json`, lock/tsconfig/Vite config, `src/main.tsx`, `api/client.ts`, `auth/AuthProvider.tsx`, `auth/AuthPage.tsx`, `settings/ServiceSetup.tsx`, reusable `LanguagePicker.tsx`, focused tests and CSS. Use existing auth APIs, HttpOnly cookies and CSRF held in memory recovered through `/auth/me`; never localStorage/sessionStorage secrets. API prefix remains `/api`; loopback Vite proxy to explicit dev API, production same-origin static build. Do not expose Vite publicly or set allowedHosts=true.
- [ ] Add failing component tests for register/login/logout/reload, expired session, settings load/save/check, API failure display, missing token, safe clear, stale revision and saved-secret disappearance. Use fake tokens only. Form state must not be overwritten by background responses; submit is disabled while pending and errors are associated with fields.
- [ ] Implement an accessible Chinese interface: Video Translate wordmark, quiet light workspace, deep green primary controls matching approved design, clear labels/focus/keyboard navigation, responsive layout and readable spacing. Show one shared HF credential entry, five service rows/cards, actual status/limits and an advanced settings disclosure. Standard view uses user terms: 背景分离、识别与角色、翻译、声音克隆、配音复核. Keep endpoint/model syntax in advanced settings where it aids a decision. Link precise model/service source pages safely. No fake completion cards, sample transcripts, progress percentages or invented costs.
- [ ] Clear secret input on successful save; server read never repopulates it. A browser reload preserves the configured badge from API, not the token. Connection checks display only what was checked and retain inference_unverified until real runs later. Show all catalog choices while separately showing service coverage.
- [ ] Serve built static assets only when present with safe SPA fallback excluding `/api`, or supply an explicit same-origin production web container route. Keep the eventual workbench able to reuse auth/API/settings components without replacing this screen.
- [ ] Run component tests, strict typecheck and production build. Actual browser inspection uses CUA only (controller performs it), not standalone Playwright/AppleScript. Commit scoped frontend changes.

## Task 5: Independent checks and protected credential handoff

- [ ] Full Python tests/migrations/lint/format/compile, frontend tests/typecheck/build and Git diff/secret checks. Verify a real local API + browser UI registering a test account, saving fake config, reloading without token disclosure, detecting reachable services and handling unauthenticated/invalid-key responses. Do not submit audio or count metadata checks as inference.
- [ ] Controller uses actual browser controls to test the screen and saves a screenshot under parent outputs/VideoTranslate-service-setup.png. Only after the protected form exists may the user be asked to enter their HF token there; never ask for chat secrets, cookies or raw headers. Continue independent pipeline implementation while waiting for configuration.
- [ ] Save precise evidence in `docs/engineering/providers-verification.md`, update official source links and startup commands/env examples. Include current metadata health separately from contract doubles, actual inference and deployed SaaS. Independent spec then quality review must pass before domain pipeline implementation.

## Remaining full-product scope

This increment does not finish multi-role timeline/edit/import, the three translation modes/context/glossary/locks, per-line cloning/QC bindings, timing/background mixes/subtitle/video export or the complete workbench. Those approved increments remain intact. Final real tests use the selected English video for Chinese and Japanese from fresh product upload and real cloud requests; earlier prototype output and transport doubles never qualify.
