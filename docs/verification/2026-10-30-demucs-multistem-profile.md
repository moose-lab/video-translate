# Task 4B.1 — explicit remote four-stem separation profile

## Implemented contract

- New explicit `demucs_multistem` adapter: `teamup-tech/Demucs`, source revision `541b5b5bdee7e1eb6163d6f4e064e9e24f33c40c`, host `https://teamup-tech-demucs.hf.space`, prefix `/gradio_api`, named API `/process`, model `htdemucs`.
- Strict schema: exactly `input_0` Audio/FileData filepath and `input_1` Dropdown containing `htdemucs`; exactly four Audio/FileData filepath returns labeled, in order, Drums, Bass, Vocals, Other. The type shapes were checked against the controller's saved public API metadata. Incompatible schemas, metadata revision/host drift, model/Space configuration and credential references are rejected before the named model call.
- No HF token is used by this public adapter. The existing five service slots and credential host boundaries remain in place.
- The operation checkpoints profile, API name, output mapping, model, connection revision, host and prefix before the named POST. Terminal FileData is saved before downloads. A retry of a known result redownloads its saved manifest without another inference request.
- Legacy operations without new checkpoint fields retain `demucs`, `/predict`, `htdemucs_ft` and ordered vocals/instrumental behavior. Polling does not consult current settings or redirect an old ID. Legacy partial-output orphan reservations and their fenced settlement/cleanup behavior are retained.

## Audio and publication

All four actual downloads pass existing size, duration, sample-rate/channel, full-decode and hash checks. This profile retains the uploaded working format (48 kHz stereo); format drift is rejected rather than silently introducing channel gain changes.

The instrumental is the unity sum **Drums + Bass + Other**. Vocals are excluded. Installed `ffmpeg -hide_banner -h filter=amix` reported `normalize` defaulting to `true`; the implementation explicitly uses `weights='1 1 1':normalize=false:dropout_transition=0`. It writes `pcm_f32le` WAV to preserve headroom, with exact selected-frame length. There is no averaging, per-stem normalization, limiting or clipping stage. FFmpeg has bounded threads, process timeout, output size and cancellation checks. Determinable projected float-WAV size/duration limits are checked before the paid call.

Only the existing downstream vocals/instrumental asset kinds are published. Compressed remote audio is explicitly converted to an actual WAV rather than copied under a WAV filename. Stored metadata includes the decoded codec/container, duration, rate, channels, bytes and hash. Private provenance retains the four original stem hashes/facts and mapping. CPU work and storage writes stay outside the SQL publisher; the existing orphan lineage, token fencing, cache, ownership and freshness boundaries are unchanged.

## Setup and recovery behavior

New setup recommends the explicit four-stem profile. Loading or resaving an existing two-stem selection retains its settings; switching profiles requires an explicit selection. The displayed model, Space and source link follow the selection. Metadata checks and capabilities keep `inference_verified=false`; the separate controller diagnostic's actual five-second files are not presented as product end-to-end verification.

Public-artifact access failure uses safe `CONFIGURATION`, retains the original event/manifest and offers workflow `next_action=review_separation_result` when a saved public separation terminal manifest exists. Future workbench rendering should explain: **检查服务或已有结果；重试只下载已有结果。更新 Hugging Face 令牌不能解决公开文件权限。** Other failures retain the existing `review_run` fallback. Changing service is an explicit new input, never a redirect of an accepted old job.

Example new configuration (`revision: 0` for an unconfigured slot; use the currently saved revision when explicitly updating):

```json
{
  "revision": 0,
  "adapter": "demucs_multistem",
  "endpoint": "https://teamup-tech-demucs.hf.space",
  "space_id": "teamup-tech/Demucs",
  "model": "htdemucs",
  "controls": {},
  "credential_ref": null
}
```

Send through existing owner/CSRF-protected `PUT /api/providers/separation`. API name, prefix, output mapping and source revision come from the registered adapter, not extra settings fields.

## Verification evidence

- Superpowers RED: initial four profile/settings/schema/protocol checks failed because the adapter/schema/arguments were absent. Initial three real-audio checks failed because the CPU reconstruction helper was absent. Later metadata facts, format-drift, malformed-schema type and host-drift checks also demonstrated their missing behavior before implementation.
- RED/GREEN integration checks cover immutable pre-POST binding, terminal manifest before download, public 403 download-only retry, malformed/missing/duplicate outputs, paid-ID persistence on cancel/settings edit, stale suppression, deterministic preflight size limits, private-cache publication retry and legacy operation recovery.
- Real generated tones verify full-amplitude addition, vocal-frequency exclusion, preserved samples over integer full scale, exact sample count and `pcm_f32le`. Compressed-input checks verify actual RIFF/WAV output. Cancellation checks exercise the bounded process path and output cleanup.
- Initial full backend run: **425 passed, 1 failed**. The existing partial-download/GC regression exposed lost legacy orphan creation. Restoring legacy per-stem normalized storage fixed it; its focused replay and audio checks then passed (**6 passed**). No existing regression assertion was weakened.
- Final focused suite: **25 passed** (`tests/test_demucs_multistem.py`, `tests/test_multistem_audio.py`), using an owned, automatically removed `/tmp` test directory.
- Final backend/isolated PostgreSQL suite: **430 passed in 229.51 seconds**, including all live PostgreSQL migration/CAS checks; no skips. The owned full-suite temporary directory was automatically removed.
- Frontend, with bundled Node 24: **26 tests passed**, `pnpm --dir web typecheck` and `pnpm --dir web build` passed.
- `uv run --frozen --extra dev ruff check src tests`, `ruff format --check src tests`, `PYTHONPATH=src uv run --frozen --extra dev python -m compileall -q src tests`, `uv lock --check` and `git diff --check` passed.

The full backend command uses `PYTHONPATH=src`, `VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres`, `uv run --frozen --extra dev pytest -q`, and a basetemp inside an owned `TemporaryDirectory` under `/tmp`. PostgreSQL was verified alive with `SELECT 1`; migration tests create/drop their own isolated databases. No migration change was needed (head remains 0007).

## Self-review and boundary

Reviewed correctness (schema/order, sum gain, frame length, retry/cancel), readability (focused provider/media helpers), architecture (existing Operations/checkpoint and publisher pattern), security (no token to third-party Space, private provenance, allowed hosts) and performance (bounded bytes/process/threads, no CPU/storage work in publisher SQL). Existing ASR/reference consumption continues through the same downstream asset kinds.

No live inference, protected-preview changes, credential access, local AI package/runtime/weight installation, push or deployment was performed for this implementation. Controller-owned independent SPEC/QUALITY gates and the retained 60-second registered-stage integration remain separate follow-up checks. Tasks 4C/5/6/7 are not implemented here.
