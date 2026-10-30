# Shared timing, background and export boundaries

This prepares increment6 against the approved SaaS design. Implement only after5A/5B pass their independent gates and the controller writes the execution plan against their actual result models. It is not evidence that fitting, mixing or exports already work.

## Verified upstream reference

The controller read the pinned official VoiceStudio export guide and timing/export tests through Agent Reach's GitHub CLI route at`5abc33602d17b81805731717b2a117857a98751c`:

- [Export guide](https://github.com/debpalash/VoiceStudio/blob/5abc33602d17b81805731717b2a117857a98751c/docs/dubbing/export.md), blob`d66e81d2c5bbc061b0828fdf11683aba9cb340ac`.
- [Smart Fit export tests](https://github.com/debpalash/VoiceStudio/blob/5abc33602d17b81805731717b2a117857a98751c/tests/test_smart_fit_export.py), blob`8f934127feeb3c7e2c11a79339a86bc34e31a232`.
- [Timing strategy tests](https://github.com/debpalash/VoiceStudio/blob/5abc33602d17b81805731717b2a117857a98751c/tests/test_dub_timing_strategy.py), blob`015693729c1573a7b3d72206bac414e98541ebfe`.

These establish selected default audio tracks, configurable background level with clipping protection, caption burn after retime, shared overlap timing, persisted plans and stale-plan rejection. This project implements its own SaaS contracts and media code; do not copy upstream implementation. The approved product design remains the scope authority.

## One common map per rendered video

Persist an immutable fit plan tied to active source selection, selected target line/audio revisions, measured natural durations and explicit fit settings. Represent a continuous, strictly increasing piecewise-linear source→output map over the complete selected window, including preroll, inter-line gaps and tail. Source times remain selection-relative, with the original absolute window retained for input extraction. No map may silently drop or reorder source video.

Fixed-picture mode keeps the identity video map. Prefer an explicit shortening suggestion or borrowing available same-role inter-line silence, then bounded pitch-preserving audio speed changes. A suggestion never edits wording automatically. Borrowing cannot move another line's onset or cross an occupied same-role slot; different roles may intentionally overlap. When a current natural line cannot fit the configured limits, report that specific line for review rather than truncate its last word, overwrite its controls, or pad a missing line with silence.

Smart Fit permits configured local picture extension. Split at every contributing source boundary and choose the largest required picture slowdown in each overlapping interval, once. All roles share that map and start at their mapped source onsets; never stretch each role independently then concatenate. A request with multiple target audio tracks in one MP4 also needs one common video map covering the included targets. Separately exported Chinese/Japanese videos may each have their own recorded plan. Never mux audio produced against a different map merely because its duration is similar.

Original comparison audio and the source/background bed must follow the same video map. Preserve pitch with explicit CPU audio-tempo processing when retiming. Fit-adjusted line audio is a derived object; natural voice output remains unchanged. Source-time caption coordinates go through the shared map; target captions may use the actual fitted line placement/duration, but must identify which policy they use and remain within the plan. Retained overlaps must not be flattened into a sequential caption timeline.

Validate map continuity, positive finite rates, endpoint/duration agreement, source coverage, bounded output duration, ordered source partitions, current revision proofs and stable IDs before rendering. Bound chunk/filter-graph size and use deterministic rendering batches when a long plan exceeds a safe single-process graph. VFR and fractional frame rates require explicit normalization and frame-accurate tolerance. Report actual measured media duration and any tail padding; do not call a predicted plan measured audio/video.

## Background replacement and peak protection

Create the background bed from the selected source working audio outside reviewed dialogue intervals and the separated instrumental inside their union. Use bounded crossfades at the union boundaries. Overlapping speakers do not apply background removal twice. Retime that bed through the common map, then place every selected target voice at its mapped onset.

Background/dub gains are explicit immutable mix settings. Retain unity where requested; avoid FFmpeg's implicit amix input-count normalization. Sum overlapping voices in floating-point, measure actual peak, then apply documented limiter/attenuation behavior. Record the applied gain/protection and measured output peaks. A louder bed must not produce clipped exports. Background-off and original-comparison options are explicit. A gain edit invalidates only derived mixes/exports, not recognition, translation, natural synthesis or independent QC.

## Guarded media outputs

The requested selected lines must each have current accepted usable audio or an explicit review policy. Missing/stale lines block ordinary target exports. A user-requested incomplete preview is labelled as such and cannot become the accepted final export or silently reuse historical audio. Original-only video/subtitle export is an explicit selection and does not claim a dub exists.

Persist each fit/mix/export command, selected inputs and public-safe progress events. CPU rendering remains in the independent Worker, with heartbeat/cancel/timeout, bounded files and existing prepared-object reservations. Publish artifact records only after complete validation and a short current-input/CAS guard. No object-store I/O or full decode inside SQL publication. Retry a failed export without re-calling remote models; preserve already validated current intermediates.

Export MP4 with an explicitly chosen default audio track, owned original/selected targets, language tags and one matching map. Export dubbed WAV/MP3 plus SRT/VTT/ASS, original/target/bilingual captions and optional burned subtitles. Render captions after video retime. Escape caption data for each format and FFmpeg filter arguments; no source text or filename becomes shell/filter code. Use a bounded available-font allowlist with actual CJK/Japanese/RTL coverage evidence; absent glyphs or unavailable requested fonts must be visible. Do not claim tested typography for all646 languages.

Validation includes nonempty byte bounds/SHA, actual codec/container/channel/rate, complete decode, expected stream count/default/language, duration/timeline agreement, cue count/stable-ID coverage, finite in-range times, overlap/order policy and hardsub representative-frame review. Authorized downloads return project-scoped media, not server paths or provider signed URLs.

## Required evidence

Use real CPU media fixtures with distinguishable audio/frequency markers and source-frame counters, covering offset/delayed audio, fractional/VFR video, silence, same-role boundaries, two-role overlap, long/short natural audio, unknown/missing/stale lines, CJK/RTL caption escaping, dual-language tracks/default flags, gain-only invalidation, restart/cancel and publication conflicts. Verify measurable placement and shared-map behavior rather than only inspecting generated filter strings. Include waveform/peak measurements, decode/FFprobe and representative hardsub frames. Cross-project/workspace/FK and frozen migration tests remain required for new records. Controller real EN→ZH/JA media acceptance and normal-speed review are separate final integration steps.
