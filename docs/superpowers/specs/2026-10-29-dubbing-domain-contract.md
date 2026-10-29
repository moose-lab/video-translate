# Dubbing domain contract

This implementation-level contract refines the approved SaaS design without changing its scope. It fixes the source/cast/translation boundaries needed after the cloud-service increment. Field names retain the existing API's snake_case conventions. No endpoint described here is claimed implemented by this document.

## Source identity and time

An original video Asset remains immutable. Probe facts enumerate audio tracks with both `audio_ordinal` and absolute `stream_index`; project `source_track_index` always means the ordinal. Analysis must use the selected track, not whichever FFmpeg considers default. Persist SourceTrack facts with source asset/probe lineage.

The project may select an explicit source window `{start_ms,end_ms}`. A missing end means the probed file end; validate against actual source duration. Probe remains dependent on the full video only. Extraction/separation/recognition/reference selection depend on the selected track and window. The original700-second test file is retained, while its explicitly selected60-second sample exports as a60-second source window, not a700-second file with only60 seconds dubbed.

Timeline segment times are relative to the selected window. A reference cut also records absolute original-file bounds (`window.start_ms + segment.start_ms`) and source asset identity. This distinction must survive edits, previews and exports. Changing the source track/window makes affected analysis historical; old edits remain inspectable and are never silently rebound to different audio.

A provider's duration or language limit is enforced before submitting audio. Never silently truncate to a demo's120-second maximum. Auto source language requires a provider that can actually detect it; an English-only service cannot be labelled multilingual auto-detection. Missing speaker labels stay unassigned for manual correction.

## Entities and immutable history

| Entity | Ownership and purpose |
| --- | --- |
| SourceTrack | Workspace/project/source asset, audio ordinal and stream index, probed codec/language/channels/rate/duration |
| TranscriptRevision | Immutable analysis/import result, source identity/track/window, provider/model/connection revision/run and original segments |
| Segment | Stable ID within transcript lineage, original ASR/import text and original speaker label, current SegmentRevision pointer, display order |
| SegmentRevision | Immutable corrected text, relative start/end, assigned speaker, parent revision, actor/provenance and creation time |
| Speaker | Anonymous work label with editable name/description, current revision, merged/archived state; never a claim of real identity |
| VoiceReference | Immutable private audio asset/hash, exact reference text, source speaker/span or uploaded origin, duration/language/version and quality flags |
| LanguageTrack | Unique project/target tag, translation mode, current glossary/context settings and status; separate from every other target |
| TranslationRevision | Immutable segment+target text, source-text fingerprint, context/glossary/mode, provider or manual provenance, parent revision and approval |
| TranslationState | Current translation pointer, row revision, lock/stale/review state for one segment+target |
| ContextRevision | Immutable supplied/derived summary and glossary snapshot, scoped to project/target as appropriate |

Each table and reference enforces workspace/project ownership. Histories do not overwrite original ASR text, old references, source corrections or another language's translation. Project revision is lineage; per-row revisions arbitrate concurrent edits to the same cell. Unrelated cells need not conflict just because the project revision changed.

## Analysis graph and publication

```mermaid
flowchart LR
  Upload[Original private asset] --> Probe[Real probe]
  Probe --> Select[Audio ordinal + explicit source window]
  Select --> Extract[CPU extraction]
  Extract --> Separate[Remote vocal/background separation]
  Separate --> ASR[Remote timestamped recognition + available diarization]
  ASR --> Publish[Lease/freshness-checked transcript publication]
  Publish --> Review[Source and cast review]
  Review --> Translate[Independent target-language jobs]
  Translate --> TargetReview[Translation review and locks]
  TargetReview --> Clone[Per-line cloning in the next increment]
```

Each external operation has its own durable StageRun/checkpoint. Do not put two unrelated paid submissions behind one saved remote ID. A high-level workflow action queues prerequisites and advances through their transactional publishers. Existing handlers remain separate from API processes. Unavailable capabilities/configuration produce a specific review/configuration error, never a fabricated successful stage.

Prepare remote results and media before entering the short publication transaction. That transaction rechecks lease, exact inputs and current domain pointers, then publishes rows/assets/current output together with events. A changed input/lock/row revision cannot be overwritten by a slow model response. Prepared but unpublished media receives safe cleanup/orphan lineage.

Default checkpoints wait after source/cast review and after translation review. Project `auto_advance` may advance valid results, but missing role/reference, unsupported language, invalid timing or quality flags still produce an explicit review state.

## Source and cast editing

```text
GET  /api/projects/{id}/timeline?target_language=zh&limit=100&offset=0
POST /api/projects/{id}/segments
PATCH /api/projects/{id}/segments/{segment_id}
POST /api/projects/{id}/segments/{segment_id}/split
POST /api/projects/{id}/segments/merge
POST /api/projects/{id}/speakers
PATCH /api/projects/{id}/speakers/{speaker_id}
POST /api/projects/{id}/speakers/merge
POST /api/projects/{id}/references/extract
POST /api/projects/{id}/references/upload
POST /api/projects/{id}/references/{reference_id}/versions
POST /api/projects/{id}/source/import/preview
POST /api/projects/{id}/source/import/apply
POST /api/projects/{id}/workflow
```

Timeline response contains project/source identity and window, bounded source-segment page, the selected target's corresponding translations, cast/reference summaries and language-track summaries. It does not multiply every row by every target. Collection defaults/maxima follow existing100/200 bounds; selectors expose explicit totals/cursors. No paths/storage keys or credentials are returned.

Source PATCH includes expected segment revision and only changed fields. Validate text length and finite ordered times within the window; overlapping different-speaker intervals are valid. Split creates new stable segments with parent lineage and explicit text/time/role distribution; merge accepts explicit current IDs/revisions. Do not divide words or assign a second speaker by guessing. A speaker merge updates affected bindings atomically and retains archived labels/history; a name-only change does not regenerate audio.

Manual segment creation repairs missing recognition lines with explicit source revision, text, time and role. Its provenance is manual, never fabricated ASR. Reference text corrections create a new immutable version for the same owned audio with parent lineage; updating the selected binding invalidates affected voice outputs while preserving previous versions.

Reference extraction accepts owned source spans and exact text. Uploaded audio is private, bounded, decoded and duration-checked by CPU media operations; declared MIME is insufficient. Support manually replacing reference audio/text. Store actual source provenance and single-/mixed-speaker or too-short/noisy review flags only when supported by measured/provider evidence. A reference is never silently trimmed while retaining a now-incorrect reference transcript.

Source import supports SRT/VTT and explicit ID/index mappings. Parse captions as data, ignore styling/executable markup and external resources. VTT voice labels may supply work labels; plain captions do not prove speaker detection. Preview reports proposed matches and conflicts without mutation. Applying requires current source identity/revision and explicit mapping; do not zip misaligned target captions onto source IDs silently.

## Independent target translation

```text
POST  /api/projects/{id}/language-tracks
PATCH /api/projects/{id}/language-tracks/{tag}
POST  /api/projects/{id}/language-tracks/{tag}/translate
PATCH /api/projects/{id}/language-tracks/{tag}/segments/{segment_id}
POST  /api/projects/{id}/language-tracks/{tag}/import/preview
POST  /api/projects/{id}/language-tracks/{tag}/import/apply
POST  /api/projects/{id}/language-tracks/{tag}/approve
```

The target tag preserves catalog variants. Fast produces a direct translation; Cinematic uses an immutable source summary/context/glossary and a conversational revision; Autofit adds labelled speaking-duration estimates and shorter suggestions. Estimates are not actual synthesized duration. Later TTS measurement determines whether fitting succeeded. Do not auto-overwrite locked or manually approved text with a shortening suggestion.

Use stable segment IDs in structured model requests/results; reject missing, duplicate, unknown or wrong-target results. Treat source text as quoted data, not model/tool instructions. Bound text/context/glossary/request sizes and batch by actual service limits, preserving IDs and context. Save returned usage/request IDs when present; no invented cost or completion percentage.

Manual translation PATCH includes current translation revision, `expected_source_text_fingerprint`, text and lock/approval changes. Each approval row carries the same source proof. The current source fingerprint is returned on source-segment DTOs; a stale client cannot approve against a source meaning it has not refreshed, including the first revision-zero translation. Every source meaning change advances existing target-state CAS even when that target was already stale. It creates a new immutable revision with source-text lineage. Re-translation has an explicit selected-ID scope and preserves locked rows; forcing locked replacement requires an explicit option and is auditable. Import accepts SRT/VTT/numbered text or explicit ID mappings through preview/apply; ambiguous timing/count alignment is returned for correction.

If source meaning changes, the corresponding translations become stale even when locked. Existing text remains visible. A manual approval against the new source fingerprint can retain the same target wording with new approval lineage. Changes to one target never overwrite another target. Speaker name/role-only edits do not silently retranslate approved wording.

## Faceted dependency keys

| Edit/input | Keys and consequences |
| --- | --- |
| Source asset/track/window | Extraction, separation, ASR and derived reference/timeline validity; full-video probe unaffected by track/window |
| Segment text | `segment.{id}.text`; corresponding target translations, text-bound references and dependent audio/QC/mix/export |
| Segment timing | `segment.{id}.timing`; derived source-reference cuts, fit/mix/subtitles; unrelated natural TTS remains reusable |
| Speaker assignment/default reference | Per-segment/per-speaker voice-binding keys; affected TTS/QC/fit/mix/export, excluding explicit independent overrides |
| Translation text for tag | `translation.{tag}.{id}`; only that target/line's TTS/QC and downstream artifacts |
| Context/glossary/mode | In-flight/generated suggestions depend on immutable snapshots; committed approved text is preserved until explicitly replaced/reapproved |
| Mixing/subtitle settings | Mix/export or corresponding subtitle export only; no ASR/translation/voice regeneration |

Immutable connection revision identifies endpoint/model used by each run; credentials may rotate independently. Capture the original endpoint for remote polling, not whichever host a later settings edit selects. A completed synchronous result must be durably cached before being considered recoverable; no invented provider poll ID.

## Events, authorization and verification

All mutation endpoints use session+CSRF and expected relevant row revision; all lookups/history/assets/runs/streams use workspace and active-project predicates. Preserve the existing safe error envelope and404 foreign-resource behavior. Emit actual import/review/speaker/reference/translation/edit/lock/retry events with bounded IDs/hashes/counts and provenance, without raw dialogue or credentials in the event journal.

Implementation tests must prove cross-workspace denial, atomic conflicting edits, split/merge lineage, reference provenance, import mapping conflicts, source immutability, separate target tracks, locks under slow responses, context/glossary snapshots, selective invalidation and real CPU extraction. Provider mocks remain explicitly test-only. At least one later real model chain must produce actual timestamped and speaker-attributed source results. Final English→Chinese/Japanese fixture acceptance remains defined in engineering/integration-fixture.md; this domain document is not evidence that it passed.
