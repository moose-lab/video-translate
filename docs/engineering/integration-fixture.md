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

## Current status

Source acquired at `/tmp/videotranslate-fixtures/SIZsFGvtClM-original.mp4` for later fresh product upload. Acquisition selected YouTube formats398+140 and remuxed them without generation: 25,861,753 bytes, 1280×720 AV1 video and AAC stereo44.1kHz, English audio metadata. FFprobe reports700.406712 seconds. SHA-256: `18dab5bf7665e33842335da25c24e899d2c14a9e8ce7f43fc5b49a473bcccf9f`. Original absolute stream1 is audio ordinal0; select that original English track.

Full source decode completed with FFmpeg exit0, explicitly mapping its video and English audio to a null sink. Publisher captions were separately acquired at `/tmp/videotranslate-fixtures/SIZsFGvtClM.en.vtt`. These checks establish a readable input and independent reference, not translated-output quality.

Acquisition and source probing are preparation only. Real model runs, product workflow, translated outputs and quality review remain pending. This document defines the test; it does not claim it passed.

## Persistent reacquisition after runtime restart

The former temporary fixture and preview state were absent on2026-10-30 resumption. The same formats were reacquired through the documented yt-dlp route into `/Users/moose/.agent-reach/fixtures/SIZsFGvtClM/SIZsFGvtClM.mp4`. Its25,861,753bytes and SHA256 exactly match the source above; FFprobe again reports700.406712seconds. English VTT is retained alongside it. New product upload/jobs must have their own real lineage; old temporary IDs cannot be treated as live. Initial sample selection is0–59,510ms to stop at the publisher's utterance boundary, consistent with the approved approximately60-second sample. See `docs/verification/2026-10-30-runtime-recovery.md` for the observed recovery boundary.
