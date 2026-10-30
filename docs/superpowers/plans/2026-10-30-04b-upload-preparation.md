# Bounded cloud media upload preparation repair

> **For agentic workers:** REQUIRED: Superpowers subagent-driven-development and TDD. Start only after task4C's independent SPEC and QUALITY gates. One fresh implementer, then independent SPEC followed by QUALITY. This is a real-integration prerequisite before5A, not a change to translation semantics.

**Goal:** Allow the actual approximately60-second working audio to upload on the observed connection without falsely describing a pre-inference upload failure as an uncertain paid model submission.

**Architecture:** Retain the existing SafeHTTP/Gradio/PrivateOperation boundaries. Give media upload a separate finite write timeout; keep connect and named inference submission policies separate. Upload is preparation: the named operation is submitted only after durable `Operations.prepare` then `Operations.begin`.

**Tech Stack:** Existing HTTPX, Python3.12, recording transports and actual Worker/API tests. No new dependency or model runtime.

## Current evidence

In the persistent protected preview, registered source probe and extract succeeded. Three separation attempts stopped before any separation PrivateOperation was created: run remote_state remains`not_submitted`, remote_idnull. A passive wrapper around the unchanged `SafeHTTP.upload` on the third attempt recorded11,425,998bytes,16.030seconds, exception chain`ProviderError → WriteTimeout → WriteTimeout → TimeoutError`. It returned the original exception unchanged. No named model POST or token transmission to the third-party Space occurred. The first two failures were not independently wire-captured and must not be assigned an exact cause solely from this third observation.

`providers/network.py` currently gives every HTTPX operation15seconds except connect5seconds. The same generic timeout is too short for this upload connection. Current upload catches RequestError as`uncertain`, even though no named inference operation has begun. Do not acknowledge an unknown inference or reset a submitted remote ID to repair this preparation failure.

## File map

- Modify`src/videotranslate/providers/network.py`: separate upload-only bounded timeout; contextual preparation error classification; preserve address pinning/allowlist/authorization/header/redirect/byte limits.
- Add focused`tests/test_upload_preparation.py`; extend existing provider tests only where their expectation explicitly treated an upload as named inference. Add registered separation recovery test to prove no duplicate named POST/operation.
- Document`docs/verification/upload-preparation.md`. No migration, credential, endpoint/model switch, unrelated refactor or UI change.

## Required RED/GREEN work

- [ ] Write a recording transport test that inspects actual HTTPX request extensions. A multipart upload must have finite write120seconds, connect5seconds, read30seconds and pool5seconds; ordinary GET and named JSON model POST retain current15/5 policies. Boundaries are constants or validated constructor parameters, not request-supplied URL options. A timeout override on the upload's `client.stream` is sufficient; do not expand every provider request timeout.
- [ ] Run the test against baseline and record failure. Implement the upload-only timeout. Keep max64MiB input and1MiB response, identity encoding, no automatic HTTPX retry, validated pinned public addresses and trusted proxy behavior.
- [ ] Write RED tests injecting WriteTimeout before upload completion, malformed/oversized upload response and valid upload. RequestError during preparation must classify as retryable network failure rather than uncertain inference; invalid preparation response must be invalid_response/configuration rather than unknown model submission. Do not weaken `post_json` uncertainty for an interrupted named inference POST.
- [ ] Implement preparation classification at the appropriate upload boundary. Preserve bounded safe public error details; do not log exception messages/headers/paths/token. A partially uploaded file is not a model handle. No post-submit unknown state may be cleared automatically.
- [ ] Write a registered-worker regression using a real CPU media fixture: first upload times out, no separation operation or named POST exists; a bounded retry can prepare/upload successfully, persist the operation, then submit exactly one named call/save the real returned eventID. Restart resumes that ID; a later download failure retains terminal FileData and cannot call the model again. Existing active lease/cancel/source guards still suppress publication.
- [ ] Run focused provider/separation/worker tests, then full backend suite once frozen including isolated PostgreSQL (existing127.0.0.1:53227). Ruff/format/compile/lock/diff checks. Record actual RED/GREEN and commit only task files. Independent SPEC then QUALITY before controller activates a frozen reviewed composition and retries the retained source run.

## Controller acceptance

After both gates: stop only owned preview Worker/API, preserve and back up the persistent DB+key, activate exact reviewed code with compatible frozen migrations, retry only known not-submitted separation run through the actual HTTP API, and resume workflow before worker claims it. Capture actual preparation/submission/terminal/result IDs and validated source transcript. Do not create a new source project or re-upload/re-extract the video merely to work around this failure.

A slow/live provider may still fail or reject work. Report the actual result; one successful upload is not final EN→ZH/JA dubbing acceptance. Continue5A/5B/media/workbench/integration afterward.
