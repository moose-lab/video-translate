# Provider and setup verification

These checks cover configuration, metadata and recording test doubles. They do **not** establish inference permission, generated audio quality, commercial readiness, or completion of the later dubbing pipeline. No model weights, local ASR/TTS runtimes, or actual audio inference were used in this increment.

## Test-driven evidence

Representative observed red-to-green cycles (the RED was run before implementation):

- `pytest tests/test_languages.py -q`: three failures for missing catalog/API/normalization, followed by three passing tests; later default Auto, exact schema spelling, hashes, RTL and variants were added.
- `pytest tests/test_provider_settings.py`: missing encrypted models/settings first failed, then CAS, encryption and immutable revision tests passed. Subsequent focused failing tests covered unsupported controls, missing key/model states, stale checks, incompatible schema and rotation state.
- `pytest tests/test_provider_network.py`: missing safe network/redirect and proxy functions failed first; bounded transfers, no retry after an ambiguous POST, auth removal on redirects, public IP checks, DNS-over-HTTPS and pinned CONNECT tests then passed.
- `pytest tests/test_provider_adapters.py`: missing OmniVoice/Gradio, HF ASR/chat and NVIDIA/Demucs functions failed first; tests use recording doubles only. They check event IDs and SSE resumption, exact payloads, true stem separation, output validation and cleanup.
- `cd web && pnpm test`: initial auth/setup and subsequent credential, controls, language and service tests were exercised through the rendered interface. The protected input is cleared after save and is never put in browser storage.

Final verification on this checkout: `PYTHONPATH=src .venv/bin/pytest -q` **244 passed**; `ruff check`, `ruff format`, and `python -m compileall` passed. With bundled Node 24.22.1: `pnpm test` **18 passed**, `pnpm typecheck` and `pnpm build` passed. The local editable installation acquired the macOS hidden flag after `uv add`; `PYTHONPATH=src` was used for Python commands rather than changing shared state.

An isolated PostgreSQL 14.18 database was created solely for this increment: migration 0003 upgrade, downgrade to 0002, upgrade again, fake credential save and provider CAS passed. The temporary database was deleted and the PostgreSQL server left running. A separate temporary application/account, with no credential, completed the real OmniVoice public metadata/schema check through the administrator proxy; returned `public_demo` and `inference_verified=false`. Public Space metadata and schemas for OmniVoice and Demucs, plus NVIDIA health/config, were also checked through the same transport. None of these checks submits audio.

## Interfaces and boundaries for the next domain increment

- `languages.catalog.resolve`, `search`, and `/api/languages` use bundled offline data. `name` is the pinned table spelling; `model_name` is the captured official enum spelling. Configurable Spaces must validate and use the actual schema enum with `model_name_from_enum`. A catalog entry is not proof that recognition, translation, synthesis and verification work together.
- `/api/provider-settings`, `/api/credentials/{kind}`, `/api/providers/{slot}`, and `/api/providers/{slot}/check` expose nonsecret settings, credential configuration/revisions and metadata-only checks. `providers.settings.resolve_revision` returns immutable tenant-scoped settings; future runs must snapshot the chosen revision. Credential rotation does not put secrets in connection history and does not invalidate completed media results.
- `providers.hf_router.translate` and `transcribe` are synchronous and have no remote poll ID. A later domain handler must durably cache a successful response before publication and mark a lost ambiguous submission uncertain. `providers.omnivoice.submit_clone` / `poll_clone` and `providers.demucs.submit_separation` / `poll_separation` retain the provider event ID and return bounded temporary files for domain-owned storage; the caller must clean up those files. Never put provider payloads or remote paths into API/event JSON.
- `providers.nvidia_stream.stream_remote` implements the English file stream with 16 kHz mono PCM16 and a 120-second maximum. It has no resumable remote ID; caller-owned audio must be validated and prepared before calling. It does not add primer, padding, inferred speakers, word timing or confidence.
- `providers.network.SafeHTTP` uses explicit host allowlisting, public-address checks, bounded reads and pinned direct connections. An optional administrator-only proxy and Cloudflare DNS-over-HTTPS preserve original TLS hostname validation and do not send provider authorization to DNS or proxy. The local loopback HTTP proxy was exercised against public metadata; a remote HTTPS proxy has not been independently exercised. The pinned HTTPX/httpcore backend integration must be rechecked on dependency updates.
- The setup UI and provider endpoints are early infrastructure. Editable multi-role source/translation, cloning, quality control, mixing, export and the end-to-end workbench remain later domain work. Browser smoke verification, acceptance and any real integration are separately coordinated; no deployment was performed.

Packaging verification found that the repository's `data/` ignore rule initially excluded the catalog from both wheel and source archive. Hatch force-includes now bundle `catalog.json`, `manifest.json`, and `gradio_enum.json`; both artifacts were rebuilt and inspected successfully under `/tmp/videotranslate-package-audit`.

## Independent review corrections

The independent specification review identified five gaps, each reproduced by a focused failing test before correction:

- Every settings slot and check now carries the same machine-readable `ProviderCapabilities` shape: stage, declared default language support, explicit supported/unsupported language lists, controls, duration and resume/cancel limits, and an independently marked unknown tested coverage. OmniVoice supported canonical codes are derived from the actual validated Space enum; this is declared model metadata, not an end-to-end test. NVIDIA declares English support and explicitly rejects missing or non-English source language before network access.
- NVIDIA's model, Space and origin are restricted to the supported file-stream preset, and the resolved official origin is passed into the adapter and checked. OmniVoice and Demucs reject model names other than the implemented preset; their Space IDs remain configurable and checked against provider metadata/schema. The UI makes fixed model fields and NVIDIA's fixed endpoint/Space ID read-only.
- A Hugging Face model selection may retain a `:provider` suffix such as `:deepinfra` or `:fastest`. The metadata check validates and looks up only the repository component; inference requests preserve the full selection.
- NVIDIA stream failures are classified as `network` before submission and `uncertain` once a start message may have reached the service, including failure while closing the submitted stream. The worker must not automatically duplicate an uncertain submission.
- Authentication and service form errors are connected to the corresponding controls with `aria-describedby`; input-validation failures also set `aria-invalid`, while a stale revision preserves the draft and does not mark valid inputs invalid.

Review-fix regression: all 244 Python tests, Ruff, compile and lock checks passed; all 18 frontend tests, strict typecheck and production build passed. The PostgreSQL 0003 upgrade/downgrade cycle and fake credential/provider CAS were repeated successfully in a temporary database. The five focused initial review tests were observed failing before implementation. Public metadata and account identity checks do not verify inference permission, model output, or quality.
