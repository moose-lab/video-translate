# Structured chat response-wait policy verification

Date: 2026-10-31. Implementation base: `9f15ff2`; controller documentation-only
commit `35530a5` was added after implementation increment `b50cb07`.

## Policy and limits

`structured_chat` selects the private allowlisted `structured_chat` timeout profile
on `SafeHTTP.post_json`. Its HTTPX timeout values, in seconds, are connect 5,
write 30, read 180 and pool 5. The profile name and its type are validated before
the resolver or transport is called. Timeout dictionaries and unknown names are
rejected; quoted source/context/glossary data cannot supply transport settings.

This is a finite per-phase inactivity policy, not a total wall-clock deadline,
provider guarantee, or permission to retry. The retained Chinese/Japanese calls'
underlying exceptions were not captured; this change does not establish why
those calls became uncertain or promise that a retry will succeed.

The shared client's default remains connect 5 and write/read/pool 15. Ordinary
JSON POST, GET, legacy `translate`, ASR and Gradio acceptance keep that default.
Multipart upload retains connect 5, write 120, read 30 and pool 5. There is no
global-client mutation, inference-payload/fingerprint change, migration,
dependency change, or change to host/credential/proxy/redirect rules, pinned
public DNS, identity encoding, byte bounds or HTTPX retries=0.

The policy choice follows the already reviewed references in the approved plan:
[HTTPX timeout behavior](https://www.python-httpx.org/advanced/timeouts/) and
[HF configurable inference-client timeout](https://huggingface.co/docs/huggingface_hub/en/package_reference/inference_client).
No new provider capability claims or real inference were used as evidence.

## TDD and focused regression evidence

All test provider responses are explicit recorded doubles. Request timeout
evidence comes from actual HTTPX `request.extensions["timeout"]`, not simulated
elapsed inference time.

1. Before production changes:
   `PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest -q tests/test_chat_wait_policy.py`
   produced **9 failed, 1 passed**. The chat/default/upload sequence failed because
   chat still used read/write/pool 15; eight invalid-profile cases failed because
   the private argument did not yet exist. The legacy translation contract passed.
2. After the minimal transport/client increment, policy/network/client/adapter
   tests produced **81 passed**. Increment committed as `b50cb07`.
3. Timeout and interrupted-stream policy-removal probe: a standalone Python process
   temporarily wrapped `SafeHTTP.post_json` in memory to discard `_timeout_profile`,
   then ran pytest with `-k 'single_submissions and (timeout or interrupted)'`.
   It produced **2 failed, 26 deselected**, both on real request extension values
   reverting to read/write/pool 15. No repository source was reverted or changed
   by this probe. The normal implementation passes both cases.
4. Final focused command:

   ```sh
   PATH=/opt/homebrew/bin:$PATH PYTHONPATH=src:tests .venv/bin/python3.12 -m pytest -q \
     tests/test_chat_wait_policy.py tests/test_provider_network.py \
     tests/test_translation_client.py tests/test_translation_operations.py \
     tests/test_submission_receipts.py tests/test_provider_adapters.py tests/test_worker.py
   ```

   Result: **176 passed in 78.06s**. The policy module contains 28 tests.

Covered behavior:

- A single client performs chat, default JSON POST, GET and multipart upload with
  the exact independent budgets. Legacy translation body/result stay compatible;
  real recorded response IDs and usage remain intact.
- Read timeout, partial-stream interruption, encoded/oversized/malformed responses,
  redirects and provider status errors retain conservative single-POST semantics.
  Public errors remain bounded and sanitized; test dialogue, credentials and
  exception text are absent from captured logs and public worker events/errors.
- Registered Cinematic context, draft, critique and rewrite each use distinct
  existing operations. An independent DB session observes a committed private
  prepared checkpoint before normal finish/publication for every successful phase.
- A lost response at each of the four phases causes no automatic replay. Guarded
  acknowledgement adds one POST for the affected phase, retains its old submitting
  operation/generation, preserves earlier prepared operations and continues later
  phases normally. Source/non-translation runs are unchanged; targets stay unapproved.
- A private draft checkpoint produced with the previous default timeout survives
  lease expiry/restart and publishes using the same operation ID, generation and
  input fingerprint, without creating a new HTTP request.
- Controlled HTTP transport blocking with events keeps the real worker heartbeat
  running. With lease 3s/heartbeat 1s, four actual heartbeat calls are observed;
  persisted lease/heartbeat timestamps extend beyond the original lease expiry
  while the request is still blocked. Releasing a valid worker publishes normally;
  replacing its lease token first prevents caching and publication. No 180s sleep
  or claim that MockTransport enforces elapsed timeout behavior is involved.

During test development, two heartbeat tests initially used the wrong assertion
for an absent translation (`None`, rather than a row with null text). Only that
test assertion was corrected. The final focused run includes both passing cases.

## Full verification after self-review and code freeze

Production and test code were frozen before the full backend run. The full suite
uses Python 3.12, `PATH=/opt/homebrew/bin:$PATH`, `PYTHONPATH=src:tests` and
`VT_TEST_POSTGRES_ADMIN_URL=postgresql://vt_test@127.0.0.1:53227/postgres`.
Each opt-in PostgreSQL test owns its uniquely named database. A Python
`tempfile.TemporaryDirectory` under `outputs/.runtime` owns pytest's `--basetemp`;
`-o tmp_path_retention_policy=failed` bounds retained artifacts, and the outer
temporary directory is removed after the process exits.

- Full backend: **678 passed in 550.04s (0:09:10)**, exit 0, including actual
  isolated PostgreSQL tests; no skips or failures. This was one original run,
  not restarted after an observation timeout.
- `.venv/bin/ruff check src tests alembic`: passed.
- `.venv/bin/ruff format --check src tests alembic`: 137 files already formatted.
- `.venv/bin/python3.12 -m compileall -q src tests alembic`: passed.
- `uv lock --check --offline`: passed; 75 packages resolved.
- `git diff --check`: passed.

The owned `outputs/.runtime/chat-wait-full-mrk_s1gh` directory was removed after
the suite exited. Existing test PostgreSQL server state was left running; no
protected databases were stopped or altered.

No frontend files changed, so no frontend suite was run. The retained preview,
credentials/vault, source database/project/jobs and real provider requests were
not touched. No push, deployment, activation or user retry approval occurred.
Independent SPEC then QUALITY review and controller activation remain separate.

## Independent gate closure

Both independent gates passed through frozen `f93605f` on `feature/cloud-dubbing`.
SPEC independently ran **176 tests in77.90s**, plus **10 adversarial/actual
PostgreSQL cases in6.70s**, reproduced baseline RED9failed/1passed and current
GREEN12passed, and passed all static checks. It found no missing or extra scope.
A separate fresh QUALITY reviewer ran **176 tests in74.86s** and **15 new
adversarial probes in2.71s**, with all static checks passing and no actionable
Critical, Important or Minor finding. Reports/probes/logs are retained in parent
`outputs/.runtime/chat-wait-spec-*` and `chat-wait-quality-*`.

Original implementation stdout was streamed into the tool transcript rather than
retained as raw log files. The full result is original exec session2610/final
chunk55efd5, exit0,678passed550.04s; its original PID57621 was observed live by
the controller before completion. A clearly labelled transcript-reference note
is retained in `outputs/.runtime/chat-wait-original-tool-evidence.json`; it is not
a raw stdout log or an additional independent full run. The independent review
results above are fresh measurements, not relabelled author results.

Controller activation and actual model acceptance remain subsequent operations.
No gate grants retry permission: the two retained uncertain context calls still
need fresh explicit approval for at most one retry each. The earlier source-ASR
permission was consumed. Passing tests do not establish that the old exception
was a timeout or guarantee the real requests will succeed.

## Reviewed preview activation

The controller activated an exact `git archive f93605f` candidate and explicitly
migrated the stopped owned preview from0008 to0009. The [upgrade proof](protected-preview-synthesis-chat-upgrade.json)
records a protected DB/key backup, exact row-fingerprint preservation for all40
pre-existing tables, unchanged vault ciphertext/revisions/server key, and passing
integrity/FK checks. After restart the existing account authenticated without
registration, credentials remained configured, all eight source rows/manual cast
and the current reference remained present, and the synthesis route registered.
Both original context jobs remained `needs_review/submitting`, with no
acknowledgement or model call. The controller requested fresh approval for at
most one retry each; no authorization record was created in advance.
