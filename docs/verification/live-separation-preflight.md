# Actual cloud separation preflight

Controller observations on2026-10-30 use the user-selected`SIZsFGvtClM` source, with no local inference runtime or model weights. Source preparation remains CPU FFmpeg. These are separate live-service observations, not a final dubbed clip or a statement that task4B has passed its review gates.

## First actual product-path request

An isolated persistent application pinned at`4df1b73` freshly uploaded the whole25,861,753-byte source, probed700,407ms, selected0–60,000ms and ran its guarded`analyse` workflow. Only public separation/NVIDIA connections were configured; no HF token or protected preview database was read or used.

The[original Demucs Space](https://huggingface.co/spaces/kajise/Demucs_v4-FT_2s) accepted one named call and returned real event ID`54fd0fce5e714e13bfb4582b3a0fff07`. Its terminal two-file manifest was cached privately. Download then failed: canonical file routes returned403 with a file-not-allowed indication, and the server-returned same-host`/c/file=` routes returned404. No usable stem was published and NVIDIA transcription was not submitted. The workflow correctly stopped for run review. The saved event/manifest was inspected without repeating the inference POST or consuming SSE again.

The[pinned Space source](https://huggingface.co/spaces/kajise/Demucs_v4-FT_2s/blob/b24f0dc29c2a01917aff0e204d209af5b7dcf8b3/app.py) runs a shell command and returns expected output paths; a complete named-call response does not prove that command produced usable model audio. The root cause of its unavailable output files is not established from public metadata alone. No file-permission bypass, guessed cache path, credential forwarding or local separation fallback was attempted.

The persistent diagnostic state is`/tmp/videotranslate-live-source-state.json`; its isolated database retains the original request/selection/operation. It is not the protected service-setup preview. Further activity must preserve that history and must not redirect its saved manifest to a new host.

## Verified alternative service,5-second probe

The controller inspected official public metadata,[pinned app source](https://huggingface.co/spaces/teamup-tech/Demucs/blob/541b5b5bdee7e1eb6163d6f4e064e9e24f33c40c/app.py), and the[live schema](https://teamup-tech-demucs.hf.space/gradio_api/info) for`teamup-tech/Demucs`, Gradio6.24.0. Its explicit model is`htdemucs`, different from the original preset's`htdemucs_ft`. The protocol is`/gradio_api`, named call`/process`, two ordered inputs`input_0` audio and`input_1` model, and four ordered outputs`Drums,Bass,Vocals,Other`. The last output is Other, not an already combined instrumental track.

One controller-only5-second probe used an actual first0–5,000ms cut from the same source at48kHz stereo PCM16. Real event ID`b8e321c96bf1427287cd0ebe1a0ce22b` was saved before polling. All four actual output files were downloaded successfully and passed hash, size, WAV-header, exact240,000-frame and full-decode checks. Each is5,000ms,48kHz stereo PCM16 and960,044 bytes. [Structured evidence](demucs-multistem-smoke.json) records the four distinct hashes and input hash.

No credential was sent. No model-runtime code from the Space was executed locally. The diagnostic WAV files and safe report are in the parent outputs directory`VideoTranslate-cloud-service-smoke/`;`vocals.wav` was offered for playback as original-English separation. These are genuine cloud outputs, but this probe is explicitly not a registered product stage, not the60-second paired-language integration, and not a voice-cloning or subjective-quality acceptance.

The viable service now needs an explicit product profile with truthful model identity, four-stem validation and CPU background reconstruction. Existing saved jobs, provider revisions and user settings must remain bound to their original contracts. Its implementation plan is[the cloud separation profile task](../superpowers/plans/2026-10-30-04b-cloud-separation-profile.md).

## Actual NVIDIA source-recognition wire result

The controller subsequently prepared actual16kHz mono PCM16 from that5-second vocal output and called the public English file-streaming endpoint. Its first diagnostic call ended with the client's terminal-error classification. Because this protocol has no durable provider ID and the detailed frame had not been retained, the controller performed one explicit diagnostic retry with passive receive-frame capture. There was no automatic resubmission or claimed remote polling ID.

The retry received`ready` and four`result` messages, ending with`isFinal:true`, `receivedAudioMs:5000` and one actual segment from0.8 to5.04seconds, speaker`0` as a JSON integer. There were no server error messages. [Sanitized wire evidence](nvidia-live-wire.json) retains the real final response, input hash and diagnostic-only status. No user credential was supplied. The recognized words are public source-video content, not generated dubbing or manually substituted captions.

This exposed two concrete adapter inconsistencies: `normalize_final` required a string speaker, while the[official pinned protobuf](https://huggingface.co/spaces/nvidia/nemotron-diarization/blob/7e62c797615676c5785b4508ef6d1d976c53a464/proto/diarization.proto) declares`uint32 speaker`, and the[relay bridge](https://huggingface.co/spaces/nvidia/nemotron-diarization/blob/7e62c797615676c5785b4508ef6d1d976c53a464/server/nvcf_bridge.py) forwards it unchanged. Separately, the low-level client allowed50ms of frame-tail overhang but the source publisher rejected the observed40ms overhang. Raw IDs/times must remain immutable; working labels and explicitly flagged clip-bound timing must be normalized consistently without guessing missing word times or accepting larger errors.

Those focused contract fixes were assigned within the pending4B quality batch. This proves a real backend recognition response, not a successful registered product transcription/publication. The original60-second product workflow remains stopped at the unusable original separation output. Full product60-second analysis and paired translated video acceptance remain open.

## Controller verification of the adapter repair

At`70ae778`, the controller independently replayed the saved actual NVIDIA final frame through production normalization, without a network call. Numeric speaker`0` and raw end`5.04` remain unchanged; the working cue is800–5000ms with`provider_end_clipped`. [Structured local-check evidence](controller-analysis-checks.json) records that boundary and the unchanged unpublished-ASR regression passing in3.35seconds. The earlier complete controller run at`67f3398` passed401 tests in169.73seconds with isolated PostgreSQL enabled. These checks verify the repair against recorded provider data; they do not turn the diagnostic into a published product transcript or final dubbing result.

## Actual Hugging Face translation permission

The controller then used the application's existing encrypted vault and configured official HF Router connection for one short English→Chinese call. The credential remained server-side and was neither displayed nor written to the diagnostic. `Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra` returned validated segment IDs and Chinese wording, a real provider response ID, and actual usage of72 prompt/39 completion/111 total tokens. [Sanitized evidence](hf-translation-smoke.json) retains the returned text and metadata. No monetary cost is inferred from the token counts.

This independently proves current translation inference access through the saved credential; it is separate from the setup screen's earlier metadata/account checks. It is a controller-only single-line client diagnostic, not a registered task4C operation, reviewed target track, synthesized voice, or final EN→ZH/JA integration. The protected database/settings were read-only and unchanged. An initial local vault lookup used the key-file newline incorrectly; correcting it to the same trimmed representation as the running server required no credential rotation or remote retry, and only one inference request was made.

## Actual short clone and independent recognition

The configured`k2-fsa/OmniVoice` cloud Space accepted one Chinese clone request using the actual5-second separated English reference and the preceding actual translated sentence. The controller saved real event ID`de56e3d089f9415bb77cb8a41c8025fe` before polling and the terminal FileData before download. The returned225,164-byte WAV is4690ms,24kHz mono PCM16; full FFmpeg decode passed. [Clone evidence](omnivoice-clone-smoke.json) records the actual input/output hashes, model language, controls and saved artifact. The audio was offered for playback in the conversation. No local model was used.

One independent HF`openai/whisper-large-v3` call then recognized the generated audio with timestamps. [QC evidence](hf-clone-qc-smoke.json) records the actual returned text. It matches the intended Chinese sentence after the stated Unicode/punctuation normalization. Detected-language metadata was absent and remains unknown. This is evidence for this one sentence's words, not proof of voice identity, pronunciation quality or normal-speed human acceptance. Both calls used the existing encrypted application vault without displaying or writing a credential; the protected settings/database remained unchanged. These are controller diagnostics, not registered task5 jobs or a completed/video-aligned60-second target export.
