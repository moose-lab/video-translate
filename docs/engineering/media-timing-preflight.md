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
