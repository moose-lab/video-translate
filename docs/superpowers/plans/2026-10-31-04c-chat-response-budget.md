# Bounded chat-response waiting policy

> **For agentic workers:** REQUIRED: Superpowers subagent-driven-development and TDD. Execute after task5A has passed independent SPEC then QUALITY, before5B/live target retries. One fresh implementer; independent SPEC then QUALITY. Do not modify the retained preview or submit real model calls during implementation/review.

**Goal:** Let synchronous structured translation use an explicit finite response-wait policy suitable for inference, while preserving ordinary metadata, ASR, upload and Gradio acceptance policies and all unknown-submission protections.

**Architecture:** Add a private allowlisted per-request timeout profile to the existing SafeHTTP JSON transport. Structured chat requests select the chat profile; the shared client's default remains unchanged. Timeout policy is transport configuration, not a new language/model input or permission to retry.

**Tech Stack:** Existing HTTPX/Python3.12, recording transport and durable registered translation worker tests. No SDK/dependency change, migration or local model.

## Evidence and limits

Actual retained Chinese/Japanese Cinematic context calls entered submission uncertainty after16.285/16.509seconds. Neither had passive exception/response capture: the exact root exception is unknown. Existing SafeHTTP uses15-second I/O timeouts with connect5seconds. Response waiting is a plausible issue, not a proven cause. No caller may claim this change guarantees those requests will succeed.

Primary references read2026-10-31: [HF InferenceClient timeout](https://huggingface.co/docs/huggingface_hub/en/package_reference/inference_client) is configurable and defaults toNone; [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/) distinguish per-phase inactivity limits and support per-request overrides. This project deliberately retains finite waits. A180-second chat read budget below is a product policy choice, not a provider guarantee or total wall-clock deadline.

## Scope and exact behavior

Files: modify`providers/network.py` and`providers/hf_router.py`; add`tests/test_chat_wait_policy.py`, extend focused client/worker regressions as needed; write`docs/verification/chat-response-budget.md`. Do not change ASR request shape, provider model/host/credential rules, structured JSON schema, context/refinement semantics or UI. Do not change the active source/translation rows to bypass uncertainty.

- [ ] Write RED with an actual HTTPX recording transport: structured chat selects a finite profile(connect5, write30, read180, pool5 seconds). Default JSON POST and GET retain current15-second values/connect5; multipart upload retains connect5/write120/read30/pool5. Use the same client for sequential calls and prove the chat override does not mutate its defaults.
- [ ] Implement an internal allowlisted profile argument on`SafeHTTP.post_json` (default preserves existing callers) and select chat for`structured_chat`. Existing plain`translate` must remain compatible; if it selects chat too, test its unchanged body/result contract explicitly. Validate profile names/types before network; never pass arbitrary caller dictionaries/URLs through as HTTPX timeout configuration. Do not allow a timeout setting inside source text, glossary, model output or run options to change transport behavior.
- [ ] Write RED/GREEN for a ReadTimeout or interrupted stream under the chat profile: exactly one named POST, bounded sanitized unknown result, no automatic second POST. Invalid/encoded/oversized responses and provider status handling must keep existing conservative submission semantics. No token, dialogue, request headers or exception message may enter logs/events/public errors.
- [ ] Add registered-worker recording regression: context→draft→critique→rewrite use the chat profile on separate existing operations; each success is privately checkpointed then published. A lost response leaves that phase uncertain and prior successes reusable. A guarded explicit acknowledgement retries only the affected phase; it retains old generation history and causes at most one new POST in that attempt. No source/reference/separation repeat and no automatic target approval. Include heartbeat/normal lease renewal during an externally waiting request; this timeout change must not claim a lease transfer or publish from an invalid worker.
- [ ] Preserve all host/public-address pinning, proxy/authorization/redirect rules, input/output byte limits, identity encoding, HTTPX retries0, actual usage/ID reporting and full phase/publication guards. Transport policy alone must not enter translation inference fingerprints or stale already prepared valid content. Existing new task5A generation-fenced receipt behavior must keep passing; do not refactor it as part of this task.
- [ ] Run focused network/client/translation/receipt tests first. Self-review, freeze, then full backend with actual isolated PostgreSQL, Ruff/format/compile/lock/diff. Use owned disposable basetemp/databases and clean only those. No frontend run is needed if unchanged. Record exact RED/GREEN and commit. Independent SPEC then QUALITY before activation.

## Controller acceptance after both gates

Back up/preserve the persistent source DB/key and activate an exact reviewed archive with its frozen migration head. Validate retained source/credential/lineage; never create a new project or edit the context merely to evade existing unknown jobs. Request explicit approval for **one retry of each** retained Chinese/Japanese context phase, explaining possible duplicate charge. The earlier source-ASR approval is consumed and cannot be reused.

Only after that approval: retry those exact runs through the acknowledgement API; use passive, unchanged-payload recording to retain actual response or exception type/timing privately and run at most one extra POST per approved phase. Continue later draft/refinement phases as ordinary new authorized product work. If still uncertain, retain the state and diagnose the captured evidence rather than claim success, switch model silently or repeatedly ask for unchanged retries. No invented usage, estimated charge or provider IDs.

The source-ASR, cast and reference success from`registered-source-cast-reference.json` remains valid. Final target wording, natural clones/QC, fitting/mix/subtitle/video exports, workbench and broader integration are still required.
