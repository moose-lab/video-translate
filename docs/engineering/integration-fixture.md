# User-selected real integration fixture

The user selected https://www.youtube.com/watch?v=SIZsFGvtClM for English → Chinese and English → Japanese integration after the SaaS is built.

## Source verification

Verified 2026-10-29 via Agent Reach's documented yt-dlp metadata route. An anonymous request encountered YouTube's sign-in challenge; the existing browser session resolved metadata. Browser authentication is used only for this authorized local source acquisition, never copied into SaaS configuration or committed.

| Field | Verified value |
| --- | --- |
| Video ID | SIZsFGvtClM |
| Publisher | IBM Technology |
| Title | Agentic Engineering: 5 Terms Every AI Developer Should Know |
| Duration | 700 seconds (11:40) |
| Source language | English (`en`) |
| Audio metadata | English AAC/Opus tracks; select the original English track |
| Publisher subtitles | English available |

Raw extractor output contains temporary media URLs and is kept outside the repository. It is not an export artifact or an integration result. No video or model inference was performed by the metadata check.

## Acceptance procedure

1. Acquire this source and import/upload it through the finished product, retaining the source ID, selected audio track and SHA-256. Probe the entire file. For the initial sample use an explicitly recorded 60-second window, consistent with the user's earlier sample duration; report window bounds in both outputs. A sample pass must not be described as a full 700-second pass.
2. Create independent Chinese (`zh`) and Japanese (`ja`) target tracks from the same source revision. Use real remote model requests with Hugging Face primary. No local inference, system-voice substitute or recycled earlier sample output qualifies.
3. Run remote separation, timestamped speech recognition and available speaker diarization. Publisher English subtitles are an independent reference for checking recognition, never proof that cloud ASR ran. Missing speaker results must be surfaced for manual correction rather than invented.
4. Review source text and cast, translate with glossary/context, synthesize each line with the correct reference and run independent recognition quality checks. Preserve separate target text, line audio, QC and retry lineage.
5. Inspect both languages for meaning, omitted/extra text, carried reference words, pronunciation and timing. Record human review separately from automated decode and ASR results.
6. Export both videos with preserved background, original comparison track, target audio, correctly tagged languages and matching SRT/VTT. Verify full decode, track count, durations, nonempty output and subtitle alignment.
7. Exercise one-line manual edit and retry, confirm only the relevant target/line and downstream mix/export are invalidated. Verify cancellation, worker restart recovery, event reconnection and cross-workspace denial with the same product APIs.
8. Save real provider IDs, timestamps, sanitized event records, source/output hashes and download artifacts in an integration evidence report. Record actual returned usage only; show no invented charge or progress percentage.

The source is an English technical explainer. It exercises technical terminology and narration. A separate multi-speaker fixture remains required by the broader approved design; passing this source alone cannot prove multi-role dubbing quality.

## Initial acquisition status (2026-10-29)

Source acquired at `/tmp/videotranslate-fixtures/SIZsFGvtClM-original.mp4` for later fresh product upload. Acquisition selected YouTube formats398+140 and remuxed them without generation: 25,861,753 bytes, 1280×720 AV1 video and AAC stereo44.1kHz, English audio metadata. FFprobe reports700.406712 seconds. SHA-256: `18dab5bf7665e33842335da25c24e899d2c14a9e8ce7f43fc5b49a473bcccf9f`. Original absolute stream1 is audio ordinal0; select that original English track.

Full source decode completed with FFmpeg exit0, explicitly mapping its video and English audio to a null sink. Publisher captions were separately acquired at `/tmp/videotranslate-fixtures/SIZsFGvtClM.en.vtt`. These checks establish a readable input and independent reference, not translated-output quality.

Acquisition and source probing are preparation only. Real model runs, product workflow, translated outputs and quality review remain pending. This document defines the test; it does not claim it passed.

## Persistent reacquisition after runtime restart

The former temporary fixture and preview state were absent on2026-10-30 resumption. The same formats were reacquired through the documented yt-dlp route into `/Users/moose/.agent-reach/fixtures/SIZsFGvtClM/SIZsFGvtClM.mp4`. Its25,861,753bytes and SHA256 exactly match the source above; FFprobe again reports700.406712seconds. English VTT is retained alongside it. New product upload/jobs must have their own real lineage; old temporary IDs cannot be treated as live. Initial sample selection is0–59,510ms to stop at the publisher's utterance boundary, consistent with the approved approximately60-second sample. See `docs/verification/2026-10-30-runtime-recovery.md` for the observed recovery boundary.

## Current retained integration status (2026-10-31)

The reacquired file was freshly uploaded into the persistent product project. Registered probe, extraction, remote four-stem separation, timestamped HF ASR and source-reference extraction succeeded. The two returned working stems were authenticated-download/hash/full-decode checked. The source has eight real ASR rows; the provider supplied no automatic speaker labels, so its one narrator has an explicit manual work label. The selected reference is the complete5,620ms current source row, bound as that role's default. See [source/cast/reference evidence](../verification/registered-source-cast-reference.json), [separation evidence](../verification/registered-separation-59510ms.json) and [live chronology](../verification/2026-10-31-source-and-translation-live.md).

Chinese and Japanese Cinematic commands exist, but each initial context request has an uncertain remote outcome. No draft/refinement result is claimed. The user's one approved source-ASR retry was consumed successfully; it does not authorize retries of these context calls. A bounded chat-wait repair and both independent reviews precede fresh approval for one retry of each affected context task. Retained jobs must not be bypassed by making a new project or editing their context.

Task5A natural synthesis passed independent SPEC/QUALITY through`6303ad3`, with650 full backend tests and independent163 plus88+5 tests. That establishes backend behavior, not real registered clones or human listening. The bounded chat-wait repair also passed both gates through`f93605f` (full678; fresh SPEC176+10 and QUALITY176+15). The protected preview was upgraded to that exact reviewed code and schema0009, preserving all40 existing tables' contents, vault/key and source/reference lineage; see [upgrade proof](../verification/protected-preview-synthesis-chat-upgrade.json). Both context requests still require their newly requested retry approval. Actual target wording/clones, independent QC, fitting, background mix, captions, both videos and workbench acceptance remain open. Human listening findings must stay separate from automatic ASR/decode evidence; do not mark them passed merely to unblock an export.

The broader two-role test has a researched [candidate and attribution record](../verification/multi-role-fixture-candidate.md). No additional fixture has yet been acquired or passed. The primary source and approved approximately60-second paired-language test remain unchanged.
