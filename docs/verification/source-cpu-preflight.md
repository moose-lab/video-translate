# User-selected source: actual upload and CPU preparation

The controller exercised the real production app/API and registered CPU worker handlers at`4df1b73` on2026-10-30. This is a source-media preflight, not cloud inference or a dubbed sample. It does not close task4B's pending review findings or the final EN→ZH/JA integration requirement.

Input was the retained whole [user-selected YouTube video](https://www.youtube.com/watch?v=SIZsFGvtClM),25,861,753 bytes. Its current SHA256 matched`18dab5bf7665e33842335da25c24e899d2c14a9e8ce7f43fc5b49a473bcccf9f`. A newly created isolated test account/project uploaded that whole file through the real multipart source endpoint. No prebuilt clip, provider response double, inference credentials or protected preview data was used.

The actual`probe` run succeeded:700,407ms, AV1 1280×720,29.970fps; English AAC stereo44.1kHz on audio ordinal0/absolute stream1. The source-selection API then set an explicit0–60,000ms window. Whole source byte count/hash remained unchanged. The guarded`prepare_media` command ran actual extraction and paused at`configure_separation`, because the isolated workspace intentionally had no configured model service.

| Actual extracted asset | Duration | Format | Bytes | SHA256 |
| --- | --- | --- | --- | --- |
| Working audio | 60,000ms | 48kHz stereo PCM16 WAV | 11,520,078 | `68bd81e2e5a31ab037666e0e25d80a7b90136f2d431ee0d2c728325eeed8f7ad` |
| ASR input | 60,000ms | 16kHz mono PCM16 WAV | 1,920,078 | `5fa0fe5df1602d67285d360a5a0f0a544c791200c1ecbd2145abef9471c35517` |

Both assets were retrieved through the authorized content endpoint, checked against stored byte counts/hashes, inspected as actual WAV and fully decoded by the production CPU validation path. The only private operation was`provider=cpu`, phase`prepared`, with no remote ID. There was no second queued worker task after the missing-service checkpoint. The successful pass took3.505s; this is one local preparation measurement, not a service-performance claim.

Structured facts are retained in[source-cpu-preflight.json](source-cpu-preflight.json). The throwaway database/media and generated test login were removed when the isolated app/worker closed; the original whole source was retained. The temporary controller harness corrected its own HTTP-status/DTO assumptions before this successful pass. No product code was changed for the preflight.

Subsequent acceptance still requires a fresh upload in the completed product, actual configured cloud separation/ASR/translation/clone/QC operations, independently editable Chinese/Japanese tracks, fitting and background mixing, retained video/subtitle exports, and normal-speed review. Original English working audio cannot stand in for those deliverables.

## Public service preflight

At2026-10-29T19:03:31UTC (2026-10-30 local time), the controller also read official public Space metadata and health/schema endpoints through the production`SafeHTTP` transport with the existing administrator proxy/trusted DNS settings. No credential was supplied and no audio upload or named inference call occurred. [Structured observations](cloud-public-status.json) retain the exact timestamp and returned revisions.

- [Demucs metadata](https://huggingface.co/api/spaces/kajise/Demucs_v4-FT_2s) reported`RUNNING` at`b24f0dc29c2a01917aff0e204d209af5b7dcf8b3`; its two-stem named endpoint schema matched the adapter.
- [NVIDIA metadata](https://huggingface.co/api/spaces/nvidia/nemotron-diarization) reported`RUNNING` at`7e62c797615676c5785b4508ef6d1d976c53a464`; the public`/health` response had`ok:true`.
- [OmniVoice metadata](https://huggingface.co/api/spaces/k2-fsa/OmniVoice) reported`RUNNING` at`64deef91cf1f7bfdfc97ff07502b4cd47a0e361e`; its clone schema matched the adapter and language enum had647 entries (catalog choices plus Auto).

Availability can change. These observations do not prove an accepted inference job, available account quota/credit, correct output or a language-quality result. They only reduce the risk of discovering an already changed/unavailable public interface when reviewed product integration begins.
