# Cloud adapter evidence — 2026-10-29

These are inspected service contracts for the upcoming adapter increment. Metadata availability is not a successful inference, an SLA, or an end-to-end test.

## Language catalog

The official OmniVoice code repository at commit `08be0b4ccbac3e13e374e86fbfead4b4cac343e2` contains `docs/languages.md`, a structured table of646 names, OmniVoice IDs and ISO639-3 codes. Parsing that table yields646 distinct IDs. Every normalized name→ID pair matches the pinned VoiceStudio language-code map at `5abc33602d17b81805731717b2a117857a98751c`; zero differences. Use this official metadata as the catalog source with attribution, plus explicit Auto. No application implementation needs copying from VoiceStudio.

Examples: Chinese→`zh`/ISO`cmn`, Cantonese→`yue`, Japanese→`ja`/ISO`jpn`, English→`en`/ISO`eng`. Preserve three-letter IDs and language variants; do not truncate them. Runtime capability and tested-language evidence remain separate from this catalog parity result.

Sources: [official table](https://github.com/k2-fsa/OmniVoice/blob/08be0b4ccbac3e13e374e86fbfead4b4cac343e2/docs/languages.md), [pinned VoiceStudio map](https://github.com/debpalash/VoiceStudio/blob/5abc33602d17b81805731717b2a117857a98751c/electron/src/shared/language-codes.json).

## HF OmniVoice demo

The official Space API reports `k2-fsa/OmniVoice` running on ZeroGPU with Space commit `64deef91cf1f7bfdfc97ff07502b4cd47a0e361e`. Its live `/gradio_api/info` exposes `/_clone_fn` with ordered parameters:

```text
text, lang=Auto, ref_aud, ref_text, instruct,
ns=32, gs=2.0, dn=true, sp=1.0, du=null, pp=true, po=true
```

It returns FileData audio plus a status string. The language enum includes the complete catalog. The adapter must check both output audio and status; a completed queue event is insufficient proof of successful synthesis. FileData includes a remote service path which must remain internal. Retrieve output through a validated allowed host and copy into private application storage.

Exact success status was subsequently verified from the pinned [Space app source](https://huggingface.co/spaces/k2-fsa/OmniVoice/blob/64deef91cf1f7bfdfc97ff07502b4cd47a0e361e/app.py): `Done.`. Empty text/reference yields no audio plus an instruction; generation exceptions yield no audio plus an error. The injected generator is forwarded by the official demo wrapper. A schema saying only “string” does not justify assuming `Success`; require the known status and nonempty valid audio output.

Gradio's official HTTP contract returns an `event_id` on POST and delivers terminal results via SSE GET using that ID. This can support the durable worker's saved remote-handle polling. Upload the reference using the documented upload contract, persist the returned generation event ID immediately, and resume polling that ID after observation timeouts. If the POST may have succeeded but no ID was saved, enter uncertain-submission review rather than submit again. Demo job retention and quota are external limitations which must be surfaced.

Sources: [official Space](https://huggingface.co/spaces/k2-fsa/OmniVoice), [live API schema](https://k2-fsa-omnivoice.hf.space/gradio_api/info), [Gradio HTTP guide](https://www.gradio.app/guides/querying-gradio-apps-with-curl).

## HF inference router

The official ASR contract accepts audio plus `return_timestamps`; validate actual returned chunks/times. It does not promise speaker diarization. Missing diarization must produce an explicit capability/review state rather than fictional speakers. HF chat completion uses an OpenAI-compatible endpoint at `https://router.huggingface.co/v1`; returned translation IDs and language coverage still require validation.

No valid configured HF token is available in the app yet. Provide a protected server-side configuration path; do not ask for secrets in chat or extract browser credentials. Service settings must never echo the stored token. These observations made no inference requests and incurred no reported inference usage.

Sources: [timestamped ASR](https://huggingface.co/docs/inference-providers/en/tasks/automatic-speech-recognition), [chat completion](https://huggingface.co/docs/inference-providers/en/tasks/chat-completion).

## Public demo availability check

Agent Reach/Exa discovery found public diarization and separation demos. A direct HF Space metadata check returned `RUNTIME_ERROR` for all four examples below at the time of inspection. They must not be used as assumed working defaults merely because search indexes expose their pages or API examples:

- [vumichien/Whisper_speaker_diarization](https://huggingface.co/spaces/vumichien/Whisper_speaker_diarization), commit `12197ad5878446029c3e9065e5c88b187b30bae8`.
- [sanchit-gandhi/whisper-jax-diarization](https://huggingface.co/spaces/sanchit-gandhi/whisper-jax-diarization), commit `2b47d3b42c1712253ecd1fbf984c882df0cc161c`.
- [FahadAlam/Speaker-Diarization](https://huggingface.co/spaces/FahadAlam/Speaker-Diarization), commit `530fef93588fcafbfc78d45a4d969b0fd21eb71e`.
- [akhaliq/demucs](https://huggingface.co/spaces/akhaliq/demucs), commit `aa628f7485f7ae8dce915c2828b8c3070d3fe498`.

Availability is time-sensitive. Recheck before use. Support a configured HF-hosted endpoint/Space and truthful connection tests; remote deployment templates may install their model dependencies in the cloud, while the SaaS development app and CPU media worker remain free of local inference packages and weights. Do not allocate paid hardware or accept model access terms on the user's behalf as a consequence of discovery.

## Additional live service contracts

Subsequent metadata discovery found these reachable alternatives; inference is still untested:

- NVIDIA's [Nemotron Diarization Space](https://huggingface.co/spaces/nvidia/nemotron-diarization), commit `7e62c797615676c5785b4508ef6d1d976c53a464`, reports RUNNING. Its `/health` returns `ok:true`; `/api/config` reports English and multilingual services ready. The documented English file WebSocket `/api/diarization/file/stream` accepts up to120 seconds of16kHz mono PCM16 and returns speaker-attributed segment timestamps. Start with JSON `type=start,sampleRateHz=16000,maxSpeakers=1..8`, wait for ready, send binary frames≤64KiB, then `type=end`; require terminal `isFinal`. The selected60-second English fixture fits this limit. This streaming service does not expose durable job polling; connection loss cannot be presented as resumable. Multilingual live input has a separate30-second limit, so it must not silently replace the English file route or become an unlimited QC default.
- [kajise/Demucs_v4-FT_2s](https://huggingface.co/spaces/kajise/Demucs_v4-FT_2s), commit `b24f0dc29c2a01917aff0e204d209af5b7dcf8b3`, reports RUNNING with Gradio4.44.1. `/info` exposes `/predict(audio)` returning Vocals and Instrumental FileData. OpenAPI confirms `/upload`, `/call/{api_name}` and `/call/{api_name}/{event_id}`; its API prefix is empty, whereas the current OmniVoice Space uses `/gradio_api`. Inspect schema rather than applying one prefix to every Gradio version.
- [nakas/demucs_playground](https://huggingface.co/spaces/nakas/demucs_playground), commit `d924a6d388a60dc69d42d061ebbda7a27fab6347`, also reports RUNNING, but uses older Gradio3.35.2 and four output stems. Its queue/serialization contract differs; it is a fallback candidate, not the initial adapter default.

No audio was submitted during these checks. Reachability, public API documentation and actual model/output acceptance remain distinct evidence.
