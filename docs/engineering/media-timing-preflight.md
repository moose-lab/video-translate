# CPU media timing preflight

This is an isolated FFmpeg experiment for the future extraction stage, not a dubbing output or model inference. The product extraction stage is not implemented by this document.

The controller generated an8-second64×48 MP4 with two audio tracks:440Hz from the video start, and880Hz delayed by2seconds. Real FFprobe returned video/first-audio start0, and second-audio start1.978seconds with6.021333seconds of packets (including AAC priming). The delayed track is audio ordinal1, absolute stream2.

Selecting that second track and directly writing PCM WAV produced6.036313seconds of audio with immediate sound: WAV discarded the initial timestamp gap. This would incorrectly advance source dialogue in a dubbing timeline.

The following tested filter retained the selected track's position for windows`[S,E]` at16kHz:

```text
-ss S -copyts -start_at_zero -i SOURCE -map 0:a:1 -vn
-af aresample=16000:async=1:first_pts=S*16000,
    atrim=start=S:end=E,asetpts=PTS-S/TB,
    apad=whole_dur=E-S,atrim=duration=E-S
-ar 16000 -ac 1 -c:a pcm_s16le OUTPUT.wav
```

The experiment supplied evaluated numeric values, not literal arithmetic placeholders in the command. All arguments were passed as a process argument list. Results:

| Extraction | PCM duration | First0.5s RMS | Measured tone frequency |
| --- | --- | --- | --- |
| Direct WAV, no alignment | 6.036313s | 2857.934 | 880Hz |
| Aligned window0–8s | 8.000000s | 0 | 880Hz after the delay |
| Aligned window1–5s | 4.000000s | 0 | 880Hz after the remaining delay |
| Aligned window3–7s | 4.000000s | 2901.350 | 880Hz immediately |

Assertions passed for duration, initial silence/tone and selected-track frequency (zero crossings within875–885Hz). The fixture and measured JSON are in the controller-owned temporary directory`/var/folders/sr/7sz78lvn5kxd436pgp4mkh1w0000gn/T/videotranslate-audio-offset-uys5u0j8`.

This proves the observed case with a zero-start video/container and a delayed AAC track. It does not establish arbitrary nonzero container origins or timestamp discontinuities. Task4B must incorporate an explicit common timeline origin and relevant fixtures rather than assuming every audio stream begins at zero. Reference provenance and exported subtitles still use the selected video's logical window coordinates.

## Nonzero origins and routine MP3 priming

A second controller experiment created an ordinary3-second MP3 and an8-second MP4 whose packet timestamps were shifted by10seconds. It also remuxed that movie into Matroska. These are valid media cases; a blanket rejection of nonzero starts would reject ordinary MP3 reference uploads.

| Fixture | Format start | Format duration | Additional timing facts |
| --- | --- | --- | --- |
| MP3 reference | 0.025057s | 3.030204s | Encoder priming; audio stream has the same metadata |
| Shifted MP4 | 9.976009s | 8.023991s | Video starts10.000000s with8.000000s duration |
| Shifted MKV | 10.000000s | 18.034000s | Video/audio DURATION tags are absolute ends18.024/18.034s |

The same timestamp-preserving filter, without the blanket nonzero-origin rejection, produced a3.030s MP3-derived WAV with immediate660Hz tone, an8.024s MP4 window with first sound at0.0233125s, and correct4-second windows3–7s for both movies. This confirms common-origin subtraction for the observed MP3/MP4 cases. It also demonstrates that one cannot blindly subtract format start from every format duration: MP4's reported duration is already relative here, while the MKV metadata gives an absolute end requiring origin-aware normalization.

The experiment files are in`/var/folders/sr/7sz78lvn5kxd436pgp4mkh1w0000gn/T/videotranslate-origin-preflight-szm2n0us`. These findings are being incorporated into task4B's real fixtures and extraction/probe implementation; they do not claim arbitrary discontinuous timestamps or a finished product-stage integration.
