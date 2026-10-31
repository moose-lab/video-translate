# CPU retiming investigation

These controller experiments prepare actual media finishing. They do not add a product renderer, change the protected preview, or establish speech quality. All files are outside Git at `/Users/moose/.agent-reach/fixtures/ffmpeg-retiming-20261031/`. No model, dependency or system package was installed.

## Sources and existing runtime

Agent Reach's Jina Reader and GitHub CLI paths were used to inspect the [official FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html) and [Rubber Band API](https://breakfastquay.com/rubberband/code-doc/classRubberBand_1_1RubberBandStretcher.html). Installed tools were FFmpeg 7.1.1 and Rubber Band 4.0.0. A filter or binary being present does not prove alignment.

The FFmpeg documentation distinguishes tempo changes from timestamp editing and describes command scheduling. Rubber Band exposes an offline keyframe map separately from the overall duration ratio. These are candidate mechanisms, not acceptance evidence. Official source pins:

- Repository `breakfastquay/rubberband`, tag `v4.0.0`, commit `1d95888bec3ae0a17c0c4af791810d5a63f6bc35`.
- [`rubberband/rubberband-c.h`](https://github.com/breakfastquay/rubberband/blob/1d95888bec3ae0a17c0c4af791810d5a63f6bc35/rubberband/rubberband-c.h), blob `ec4638da92d73d1d68495cf38d93c346ac965b24`.
- [`main/main.cpp`](https://github.com/breakfastquay/rubberband/blob/1d95888bec3ae0a17c0c4af791810d5a63f6bc35/main/main.cpp), blob `b566cb954cde969b9470a40dddde7d19bdce0e23`.

The inspected CLI source explicitly clamps samples when `ignoreClipping` is true. That flag is not a floating-point headroom guarantee. Direct use of this CLI would therefore require a separately proven gain policy; it must not silently replace the product's later explicit peak-protection stage. These sources have their own licensing and must be included in any eventual worker dependency/build inventory.

## A file can decode while its timing is wrong

A deterministic four-second, 48 kHz mono PCM fixture contains five short distinguishable tone bursts. The planned common map is `(0,0),(1,1.5),(2,3.5),(3,5.5),(4,6.5)`, matching the overlapping-role numeric fixture. The last burst occupies source 3.85–3.99 seconds. Its expected output interval is 6.35–6.49.

`tempo_probe.py` applies `asetnsamples=n=48:p=0`, an `asendcmd` file with tempo changes, and one named `atempo` filter. FFmpeg exits successfully, but the resulting audio is **6.401354 seconds**, and the last burst is measured at approximately **6.23–6.40** using ten-millisecond RMS windows. Padding the result to 6.5 seconds would hide the wrong location. This exact naive dynamic pipeline is a negative design example, not a rejected claim about every possible use of `atempo`.

## Offline map experiments

The same source was processed with the existing Rubber Band CLI, with a separately declared total ratio 1.625. A map containing both endpoints produced a warning and wrong duration for the tested R3 configuration. Replacing it with interior keyframes at source samples 48,000, 96,000 and 144,000 removed that warning; the total duration then matched 312,000 samples for both tested engines. This is configuration-specific evidence, not a general library defect.

| Experiment | Output frames | Last measured burst | Headroom observation |
| --- | ---: | --- | --- |
| Naive dynamic FFmpeg tempo | 307,265 | 6.23–6.40 s | Not assessed |
| CLI R2, interior map | 312,000 | 6.34–6.50 s | Float sample peak clamped to 1.0 in the above-unity test |
| CLI R3, interior map | 312,000 | 6.35–6.50 s | Float sample peak clamped to 1.0 in the above-unity test |
| Direct R3 C API, interior map, 4096-frame blocks | 312,000 | 6.34–6.49 s | Input peak 1.46484375; output peak 2.10317969, retained as float |

The C API experiment uses explicit typed signatures from the pinned header, checks engine version 3, supplies all input in a study pass and again in a process pass, drains output, and frees state in `finally`. It performs no implicit clipping or normalization. Intermediate markers differ by up to about 50 ms in this particular block configuration; exact total length is not sample-exact transient placement. Its script is `rubberband_c_probe.py`, and its numerical result is `rubberband-c-api-probe.json`.

Raw experiment records are `tempo-dynamic-probe.json`, `rubberband-cli-probe.json`, `rubberband-interior-probe.json`, `rubberband-float-probe.json` and `rubberband-c-api-probe.json`. `official-sources.json` contains file sizes, Git blobs and SHA-256 hashes. The original FFmpeg Jina read is 979,341 bytes with SHA-256 `95ca21f310c69b4a97f72a3085432e0182357764286936e919ad7f0ba45c73aa`.

## Requirements for the implementation plan

1. Treat this as mechanism research. Select and version an explicit rendering policy only after product tests pass. A missing required CPU capability must be visible; no silent engine substitution.
2. Preserve floating-point headroom through background construction, retiming and overlapping voices. Gains and peak protection belong to the explicit mix step. Check finite samples, actual peaks and complete decode.
3. Recheck the common map with marked source frames and distinguishable audio markers at each important boundary, including the final word/tone. Declare and measure frame/sample/DSP tolerances; padding total duration is insufficient.
4. Exercise stereo phase/mono compatibility, pitch, silence, rate bounds, very short pieces and all 1000-line/3001-piece planner boundaries. Coalescing equal slopes is lossless; removing genuine timing changes or imposing an unadvertised small graph limit is not.
5. Bind original comparison audio, each target-specific background bed and video to the same exact plan. Use each target's included source-row union for replacement. Natural voices and their QC identity stay unchanged.
6. Bound CPU, bytes, memory, temporary storage, frame counts, filter/control files and time. Run cancellation/lease checks during each pass and drain/reap children. A direct native-library wrapper also needs isolation and failure/recovery tests; the small prototype is not that wrapper.
7. Keep absolute source-window/demuxer origin and output frame-grid rounding explicit. Test delayed audio, fractional rate and VFR. Actual duration/padding is measured separately from the rational planned endpoint.
8. Retain the existing Worker/Operations/PreparedObject lifecycle for eventual owned outputs. The prototype creates no alternate lifecycle or production route. Independent SPEC and QUALITY gates apply before later media orchestration consumes these primitives.

The remaining finishing, workbench, live EN→ZH/JA and multirole acceptance, workflow continuation, URL ingestion and deployment deliverables remain in the master plan. This investigation closes none of those product gates.
