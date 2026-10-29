# Remote synthesis and independent QC boundaries

This records the approved increment5 boundary against the existing references/manual target domain and actual cloud diagnostics. It is preparation, not an implementation or acceptance claim. Increment4, including remote translation, must pass its independent gates before increment5 implementation. No local inference or system-voice fallback is permitted.

## What the live probes establish

`docs/verification/omnivoice-clone-smoke.json` records one actual official `k2-fsa/OmniVoice` Chinese request using the actual separated English reference. Its returned audio was4690ms,24kHz mono PCM16 and fully decoded. `hf-clone-qc-smoke.json` records a separate real Whisper call whose returned wording matched the intended sentence after the documented normalization. These validate a short provider path, not all languages, voice identity, a product job, or final timing. Missing detected-language metadata remains unknown.

## One line, one immutable inference identity

Resolve the owned active target row and effective reference before submission. Reuse `effective_voice_inputs` from the reference domain: an explicit line binding wins over its speaker default, and a dormant role binding must not invalidate an overridden line. Missing, foreign, archived, stale or unusable references become specific review issues. An explicitly bound valid line reference may be usable without inventing a speaker label. Preserve measured reference warnings and require appropriate review; never silently cut audio while retaining an uncorrected reference transcript.

Natural synthesis depends on actual target text, explicit canonical target/model language, the reference audio hash and immutable corrected reference text/version, model/connection revision and validated controls. Speaker display names, subtitle styling, final gains and an unchanged natural-audio timing slot are not inference inputs. Timing still affects a reference extracted from a changed source span. Store per-target/per-line controls and their immutable revisions separately from the reference audio. Unsupported controls/language fail before the named model request.

Distinguish inference freshness from publication permission. Capture target/source/reference review proofs and the current line-output revision for a short publication guard. A manual choice or edit during inference must not be overwritten. It also must not turn a valid same-input prepared success into another implicit paid request: a fresh guarded command may reuse that success while preserving current manual state. Natural-audio history and superseded choices remain inspectable. Explicit regeneration or replacement must be audited, rather than hidden behind default retry.

## Durable external operations

Use one independently checkpointed operation per remote clone. Separate metadata validation/upload preparation from the named inference POST. Persist the resolved provider host, Gradio prefix, exact API, model-language mapping, controls and uploaded-reference request before the POST; persist the real event ID immediately afterward. A later settings edit cannot redirect polling. Retain terminal FileData before attempting the download, so a restart/download error resumes the same result. Unknown submission requires the established explicit acknowledgement before another POST. Never invent an ID for a synchronous operation.

Validate the returned file itself: bounded bytes, actual container/codec, channels/rate, measured duration, SHA and complete decode. `Done.` alone is insufficient. Store private raw/normalized provider evidence and provenance separately from bounded public events. Do not place tokens, provider file paths, signed URLs, dialogue or local paths in run facts. Storage reservations, lease/cancel/source guards, late-write settlement and orphan protections must follow the established prepared-object lifecycle. Expensive network/CPU/storage work stays outside publication SQL.

Batch generation is an explicit selection of owned line IDs with independent per-line jobs and results. Restart, partial failure or one-line edits recover unaffected successes. One completed line cannot mark a whole target ready. Chinese and Japanese outputs, settings and history stay independent. No background mix, time stretch or final loudness processing is folded into natural synthesis.

## Independent recognition and review

QC consumes the actual selected generated-audio hash, expected current target wording and immutable verification-provider revision. It is a separate remote request with its own checkpoint/cache and publication guard. Prepare bounded CPU audio for the provider; never inject the expected target text into the recognition prompt. Respect the actual provider capability contract, including the existing HF route's absence of forced-language support and possibly absent detected-language metadata. Do not claim automated QC for all646 catalog languages.

Keep raw recognized text/times and a documented comparison normalization. Bounded character/word edit metrics and empty/unexpected/reference-word warnings are evidence for review, not fabricated confidence, speaker similarity or guaranteed pronunciation. Any language-specific normalization must be explicit. Missing/unsupported recognition remains visible with a manual-review route. A failed QC phase retains natural audio and can retry independently; it cannot silently replace a clone with another voice or mark the line accepted. A manual correction/selection/approval has immutable actor/provenance and current-row guards.

Record natural duration and its ratio to the current slot as measurements. A suggested shortening or speed change is separate from an accepted wording/control revision. Changes to slots can invalidate duration planning and later fitting while preserving unchanged natural audio. The common overlap-aware video/audio/background/subtitle map, crossfades, final gain/limiter and exports remain increment6.

## Required verification

Use recording providers only inside tests and real CPU audio for file validation. Verify exact line/target request counts, prepared-result replay after publication conflicts, terminal-download recovery, uncertain submission, actual input changes, effective-binding precedence, stale/missing/foreign references, correct controls/languages, partial-batch retry, cancellation/lease loss, independent QC, current-wording guards, measured-duration provenance and cross-workspace denial. Include populated frozen migrations and actual isolated PostgreSQL where new tables are needed. Live cloud calls and normal-speed human listening remain separate controller acceptance after both independent reviews.
