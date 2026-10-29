# Translation operations and review contract

This refines approved task4C against the current manual domain and task4B's private-operation boundary. It is a design record, not evidence that remote translation or the complete product works. Task4B must pass its two independent gates before4C implementation begins.

## Verified upstream behavior

On2026-10-30 the controller read the pinned VoiceStudio documentation and implementation through Agent Reach's GitHub/`gh api` route at`5abc33602d17b81805731717b2a117857a98751c`:

- [Translation guide](https://github.com/debpalash/VoiceStudio/blob/5abc33602d17b81805731717b2a117857a98751c/docs/dubbing/translation-engines.md) describes direct translation, source context/terminology, critique and spoken-language revision, and fit-to-time work.
- [Quality service](https://github.com/debpalash/VoiceStudio/blob/5abc33602d17b81805731717b2a117857a98751c/backend/services/translation_quality.py) performs one context extraction call, then distinct critique and rewrite calls after the direct draft. Manual terminology takes precedence over generated entries. Its context cache includes transcript identity and target. Its optional refinements may retain the direct draft after errors.
- [Translation router](https://github.com/debpalash/VoiceStudio/blob/5abc33602d17b81805731717b2a117857a98751c/backend/api/routers/dub_translate.py) retains literal wording alongside revisions, uses estimated durations before synthesis and keeps a shortening suggestion separate from the current text. An LLM-engine route avoids applying its refinement sequence twice.

The product reproduces these capabilities with independent implementation. It uses remote inference exclusively, durable operations and visible failures/review states. It does not copy upstream application code or silently describe a failed refinement as a successful higher-quality translation. A predicted fit is never a guarantee about actual synthesized audio.

## Immutable command and operation identity

The command identifies one owned active target track and explicit active source segment IDs. It captures the current source-text proofs, target row revisions (including absent revision0), locks/approval, supplied context/glossary, chosen mode and immutable provider connection revision. Timing snapshots are needed for fit suggestions, not for ordinary meaning translation. A source batch ID alone is insufficient because individual text corrections preserve that ID.

Use deterministic bounded batches with stable IDs. Each external call is one independently recoverable operation/run: a local command or batch ID is not a provider request ID. Fast has one direct-draft call per batch. Cinematic has context preparation and separately checkpointed draft, critique and rewrite operations. Autofit adds estimates and a separately checkpointed shorter-suggestion operation when needed. Batching critique/rewrite across known IDs is allowed; hiding multiple external calls behind a single submission checkpoint is not.

Each batch requires a distinct validated stage scope/output key. Concurrent target batches cannot share one undifferentiated`output.translate:{tag}` key. Repeating the same command while its inputs remain current reuses its actual work. A retry of one failed phase must recover prior successful phases rather than paying for context/drafts again. Chinese and Japanese have independent operations, context, row guards and review state.

The context operation records which ordered source rows it used. Bound the request explicitly. If the whole transcript exceeds one call, use a visible bounded partition/aggregation plan or reject the unsupported request before submission; do not silently send a prefix while labelling it whole-video context. Preserve any supplied summary and manual glossary as immutable input. Store generated context separately or in an explicitly linked derived revision so publishing it does not invalidate the very operation that produced it or overwrite a newer human context.

## Provider request and response

Preserve the existing simple Fast client contract. An extended structured client may accept explicit context, glossary, phase and prior draft/critique data. Source dialogue, context and glossary are quoted data; system instructions define their role and the requested target. Stable segment IDs must survive every phase. Validate exact returned ID coverage, uniqueness, target tag, value types, nonempty bounded text and total response size before storing a successful result. A syntactically valid JSON response alone is insufficient.

Keep actual provider response/request identifiers and usage counters when supplied and safely validated. Absence remains unknown. Do not invent token usage, costs, detected language or provider request IDs. Private critique/dialogue/provider bodies do not belong in public run facts/events. Keep credentials resolved server-side and apply the existing endpoint/credential host rules.

Persist every successful synchronous response privately before publishing domain revisions. A possible submission with a lost response is uncertain and requires the existing explicit acknowledgement before another call. A publication conflict does not authorize another inference request. Cached results are bound to immutable operation generation and full relevant inputs.

## Publication and human review

Each short publication transaction rechecks the active source/target identities, selected source proofs and captured target row revisions/locks. Manual edits or locks made during inference suppress replacement even if their wording hash is unchanged. Unrelated source rows and other target tracks do not block a batch. Preserve locked and approved wording by default; force replacement is explicit, recorded and still guarded against edits after the command.

Retain direct draft, critique provenance and rewritten version as distinct immutable history. A refinement failure leaves the valid direct draft available with a visible incomplete phase and retry action. It cannot report Cinematic/Autofit complete or silently fall back. Source corrections retain existing visible target wording as stale according to task4A. No phase auto-approves the translation.

Shorter suggestions carry their source/target/timing/context proofs and measured-or-estimated provenance. They never change current wording until a guarded explicit apply action. Report unknown estimates for unsupported language-rate data; do not assign an English rate to all646 languages. Future measured TTS duration and common Smart Fit mapping remain tasks5/6. Changes to a suggestion's slot stale the suggestion without discarding a still-current natural-language draft.

The workflow stops at translation review per target. Only the requested current rows and required phases contribute to readiness; one completed batch cannot mark the whole target complete. The final accepted EN→ZH and EN→JA samples still require the later clone/QC, timing, mixing, subtitle/export and normal-speed review steps.

## Required evidence

Keep tests explicit about recording providers. Demonstrate separate operation counts/phases for all three modes; exact IDs and target variants; manual glossary precedence; bounded context; independent Chinese/Japanese and RTL targets; concurrent source/manual/lock changes; protected approved rows and audited force; unchanged-source cache reuse; changed-input generation; uncertain submission; restart after each successful phase and failed publication; partial-batch failure and isolated retry. Verify migration/parity/ownership on real isolated PostgreSQL. Actual HF inference remains a separate controller-run integration after the product path and both independent review gates exist.
