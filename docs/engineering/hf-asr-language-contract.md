# HF timestamped ASR: language and request evidence

Public metadata and source verified2026-10-30 for the optional multilingual source-recognition path in task4B. No audio or credential was submitted; no weights or local inference runtime were downloaded.

The [official ASR HTTP specification](https://huggingface.co/docs/inference-providers/tasks/automatic-speech-recognition) accepts base64 audio with `parameters.return_timestamps`. Its generated SDK schema at commit[`178e1a1797858724c79fd9d12d79d0902d730497`](https://github.com/huggingface/huggingface_hub/blob/178e1a1797858724c79fd9d12d79d0902d730497/src/huggingface_hub/inference/_generated/types/automatic_speech_recognition.py) names optional sampler controls `generation_parameters`. The HTTP schema does not document a forced source-language field. Do not copy the local Transformers pipeline's `generate_kwargs` example into this HTTP body or silently claim a forced language control.

The [Whisper model card](https://huggingface.co/openai/whisper-large-v3/blob/06f233fe06e710322aca913c1bc4249a0d71fce1/README.md) documents automatic source-language prediction. That model behavior can support an explicitly declared auto-detection policy, while the HTTP response schema itself provides text/chunks rather than a guaranteed detected-language code. Keep that code unknown when absent; do not invent it from the project selection or from a script guess.

The model's pinned[`generation_config.json`](https://huggingface.co/openai/whisper-large-v3/blob/06f233fe06e710322aca913c1bc4249a0d71fce1/generation_config.json) lists100 language tokens. Metadata revision is`06f233fe06e710322aca913c1bc4249a0d71fce1`; downloaded configuration SHA-256 is`fbdfa70135de9b1d31553393f14e80aaeb1936ea36576b2ba864055943c09d23`.

Ninety-three token codes directly resolve through the current pinned646-language product catalog. Two further exact model names resolve explicitly:

| Model token | Model language | Product canonical code |
| --- | --- | --- |
| `jw` | Javanese | `jv` |
| `ne` | Nepali | `npi` |

The remaining model tokens`fo,la,mg,su,tl` have no exact canonical match in the current product catalog. Do not add a guessed nearest dialect, truncate codes, or expand the approved catalog merely to make the counts equal. Model-declared language tokens, mapped product choices and real tested languages remain distinct sets. A language token is not evidence of pronunciation or transcription quality.

The official [live provider mapping](https://huggingface.co/api/models/openai/whisper-large-v3?expand=inferenceProviderMapping) reported HF Inference, Fal, Replicate and DeepInfra available for the ASR task at this observation. The existing HF adapter uses the HF Inference route; metadata availability still does not prove account permission, credit or successful model execution. Its first actual source/QC requests require separate integration evidence.

Local research copies are `/tmp/videotranslate-hf-asr-generated-types.py`, `/tmp/videotranslate-whisper-generation-config-pinned.json` and `/tmp/videotranslate-whisper-model-card-pinned.md`. Future implementation should bundle only the minimal pinned declaration needed for offline capability tests, and keep source-ASR timestamp requirements distinct from text-only QC needs. Missing/invalid returned timing must never be filled with invented word boundaries.
