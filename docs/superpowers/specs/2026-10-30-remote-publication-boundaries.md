# Remote operation and publication boundaries

This is an implementation refinement for tasks4B/4C and synthesis. It records constraints discovered in the verified execution/provider interfaces. It is not implemented by this document and does not change the approved product scope. Task4A remains limited to manual domain data/editing.

## Three distinct kinds of persisted data

1. Public run facts: `StageResult.facts`, returned by the run API, at most64KiB. Use IDs, durations, hashes and measured counts. Do not put dialogue, provider bodies, signed URLs or storage/local paths here.
2. Private operation state: the exact connection revision, resolved Gradio host/API prefix, real event ID when present, input fingerprint and request generation. This survives worker restart and must never be reconstructed from the newest workspace connection after a settings edit.
3. Private prepared result: normalized transcript data or media manifests written durably after a successful provider operation, before domain publication. Successful synchronous responses are recoverable from this cache without inventing a provider poll ID.

Storage and domain publication are different phases. Download/decode/probe/hash audio outside the short database publication transaction. Prepared storage objects are not current public Assets merely because upload succeeded. Publish Asset rows, domain revisions/current pointers and output fingerprints only after lease/freshness/row-lock checks. Keep private cleanup/orphan lineage for objects whose publication is rejected. No long media or network operation holds the project transaction.

## Submission boundary

The current `submit_separation` and `submit_clone` helpers combine metadata, upload and the paid named-call POST. A stage must not mark its run `submitting` before unrelated schema discovery or file upload and then call every discovery failure an uncertain model submission. Expose a narrow prepare/submit boundary, or a carefully placed callback immediately before the actual named-call POST. Preserve convenience clients and their existing tests where useful; do not couple low-level HTTP clients to ORM sessions.

Before the potentially paid POST, durably bind the connection revision and resolved host/prefix to that operation, then commit the existing submission checkpoint. After receiving the provider event ID, record it against the same operation. A crash between POST and saving the ID remains uncertain and requires explicit acknowledgement before a new submission. Polling uses the saved host/prefix/ID, without repeating POST or rediscovering a new host.

For NVIDIA and HF synchronous requests, a lost response after possible submission remains uncertain. A successful normalized result is privately cached and marked complete before publication. Recovery checks this durable result first; it cannot re-run inference merely because there is no remote ID. A transport can classify a failure as provably unsent only when it actually knows that boundary. Never infer unsent from a generic timeout or error string.

## Retry and cache identity

The verified `retry_run` retains the original inputs when an accepted remote job is still pending. That job is reconciled at its original endpoint even after source/configuration edits; stale output cannot become current. When the old operation is completed, or an uncertain submission is explicitly acknowledged, the engine resets `request_key` before a new submission.

Bind private result/checkpoint reuse to the run's input fingerprint and request generation, not just `run_id`. A retry under changed inputs must not reuse the previous prepared transcript/audio. Preserve old operation history without copying credentials into it. Credential rotation remains independent from immutable endpoint/model history and completed media cache validity.

If recovery finds an accepted operation or a prepared result, emit the actual recovery kind. Do not describe a cached synchronous result as a newly submitted remote job, or call it a local inference run.

## Scope and batch output keys

The current default run scope is `stage:target_language:segment_id`; options are included in cache matching but not in the output key. Multiple translation batches for one target therefore cannot all publish into one indistinguishable `output.translate:{target}` state. Give each batch a deterministic, validated scope based on its stable selected IDs or a real domain batch identifier. A small optional stage-specific scope resolver is one possible extension; existing probe scope and keyed-request semantics must remain unchanged.

Each batch/model operation has its own durable submission/checkpoint and exact source/context/target-row snapshots. A local batch identifier must be labelled local, never passed off as a provider request ID. Aggregate target readiness depends on the required current batches/rows. Completion of one batch cannot make an entire target appear translated or invalidate another batch's newly committed text.

## Media and configuration limits

- Reuse the probe's protocol/container allowlists when adding FFmpeg operations. Source and reference bytes cannot cause arbitrary nested network or local-resource reads. Validate downloaded media before publication and bound output size, duration and process lifetime.
- Audio extraction must retain the selected stream's offset against a common video timeline. Direct WAV output can discard leading timestamps and advance speech; the controller reproduced this with a delayed second audio track. See `../../engineering/media-timing-preflight.md` for actual CPU measurements and the tested windows. Extend the fixtures for the origin cases that the product declares supported; do not generalize that experiment to arbitrary containers.
- Preserve explicit source-window bounds and selected audio ordinal. NVIDIA's120-second English file limit must be checked before submission; no silent window truncation or multilingual substitution.
- `GradioClient` currently permits HF authorization only for the official OmniVoice host. A different Space cannot receive that credential merely because its hostname ends in `.hf.space`; either reject an unsupported authenticated configuration before submission or use an explicitly administrator-trusted auth policy. Public compatible Spaces can remain explicitly unauthenticated.
- A schema/health/account check remains metadata evidence. The first real source-analysis and synthesis calls must be recorded separately, with the exact fresh source and resulting artifacts.
