# Bounded upload preparation repair

The controller's passive capture of the third retained-source separation attempt recorded an 11,425,998-byte multipart upload failing with `WriteTimeout` after 16.030 seconds, before a separation PrivateOperation or named inference POST. That operation remained `not_submitted`; this observation does not establish the exact cause of the two earlier uncaptured failures. This repair starts from controller-confirmed baseline `66b2748` after task 4C's independent gates.

`SafeHTTP.upload` now sets its own finite HTTPX timeout: connect 5 seconds, write 120 seconds, read 30 seconds and pool 5 seconds. These are fixed code values passed only to the multipart stream. Ordinary GET and named JSON POST retain connect 5 seconds and all other deadlines 15 seconds. Upload RequestError is a retryable `network` preparation failure; malformed, oversized or encoded upload responses are `invalid_response`. A partial upload cannot produce a named model handle. Named inference POST interruption, invalid event ID and ambiguous response handling remain `uncertain`.

The existing 64 MiB input / 1 MiB upload-response bounds, identity encoding, host allowlist, public DNS pinning, trusted proxy behavior, zero HTTPX retries, redirect and authorization policies are unchanged. No production module other than `providers/network.py` changed. No credential, protected preview, real provider request, frontend, migration, model switch, push or deployment was involved.

## Test-first evidence

Before the production change, `PYTHONPATH=src PATH=/opt/homebrew/bin:$PATH .venv/bin/python3.12 -m pytest tests/test_upload_preparation.py -q` failed **11 tests**, with **3 passing**. Failures demonstrated the actual HTTPX request extension still had write/read/pool 15 seconds, upload failures were `uncertain`, and the registered worker entered `needs_review` after a pre-inference upload timeout. The three passing cases protected malformed named model event-ID uncertainty. One subsequent test correction used the existing durable phase name `accepted` rather than `submitted`; no lifecycle production change was required.

Recording transports inspect the actual multipart, GET and named POST request extensions; inject write/read/connect failures; reject malformed/oversized upload bodies; preserve named POST uncertainty; and accept a valid opaque upload path. The registered worker regression uses actual CPU-generated source media, production probe/extract/separation registration and real WAV output fixtures. Its first upload fails before any separation operation or named POST. A bounded worker retry uploads, persists preparation and begins exactly one named POST. A new worker resumes the exact returned recording event ID; terminal FileData is saved before a download failure and survives another retry without another upload, poll or named POST. These are recording-provider tests, not real inference evidence.

## Verification

- Focused provider/separation/recovery/worker suite: **154 passed in 86.91 seconds**. It includes existing lease, cancellation, source/settings staleness and publication guards.
- PostgreSQL readiness: `SELECT 1` returned `1` using the existing isolated local test server. Tests use `VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres` and create/drop their own databases.
- Frozen-code full backend/PostgreSQL suite: **522 passed in 304.82 seconds**, no skips. Command: `PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres .venv/bin/python3.12` invoking `pytest -q --basetemp=<owned TemporaryDirectory>/pytest`. The owned directory was removed after the run.
- `.venv/bin/ruff check .` passed. `.venv/bin/ruff format --check src tests alembic` passed for **116 files**. Python source/test compilation, `uv lock --check` and `git diff --check` passed.
- A separate broad `ruff format --check .` found only existing Python fence formatting in three historical plan Markdown files (`2026-10-29-01`, `02`, `03`); those unrelated documents were left unchanged.

Pytest commands use the existing Python 3.12 environment, `PYTHONPATH=src`, and `/opt/homebrew/bin` on PATH for FFmpeg. The focused/full runs own a `TemporaryDirectory` under `/tmp` and remove only that directory on completion. Initial task-owned RED/GREEN temporary directories were also removed. Frontend checks are unnecessary because no frontend file changed. Independent SPEC then QUALITY review and any controller-owned retained-source live retry remain separate gates.
