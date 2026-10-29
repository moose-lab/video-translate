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
