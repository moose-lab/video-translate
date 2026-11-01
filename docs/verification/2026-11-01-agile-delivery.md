# SaaS workbench and requested EN→ZH integration

The approved architecture is a separate Web/API/Worker SaaS with remote inference. No local AI model runtime or weights are installed. The current preview remains a development environment; production deployment is separate.

## Working result

The user's SIZsFGvtClM original was uploaded through the authenticated product API, with source SHA256 `18dab5bf7665e33842335da25c24e899d2c14a9e8ce7f43fc5b49a473bcccf9f`. Selected window:0–59510ms. The real cloud chain produced eight Chinese natural voices and eight independent QC results. Smart Fit keeps voice speed1 and extends picture to76.810067s. The primary10-artifact delivery and the caption-v2 12-artifact delivery are succeeded/current, with valid private manifests. Downloads were checked against registered byte sizes and SHA256; the playable Chinese remuxes passed full decode.

Results are in the adjacent `VideoTranslate-SIZsFGvtClM-EN-ZH` folder: original English, Chinese playback, optional caption-v2 playback, exact export files and receipts. Caption-v1 was rejected for horizontal clipping. V2 samples at2/35/73s show complete Chinese wrapping; the opening paragraph overlaps the source lower-third. These are previews: AudioReview count remains0. Japanese testing was deferred by the user.

## Current implementation and checks

- Server pipeline, manual/policy checkpoints, scoped continue/cancel/resume and current-result reuse: reviewed `83a4f17`; actual Chinese pipeline completed by reusing current results with0new inference calls.
- Burned/sidecar SRT/VTT/ASS, explicit actual fonts and initialized Unicode wrapping: reviewed `5d8ab2e`, `548be77`, `a69de52`, `c317bd8`. Installed multi-script font fallback has bounded discovery and measured face/coverage/hash proof; no claim of646-language quality acceptance.
- URL commands and direct adaptive local mux: reviewed `0951904`, `d79c3f4`, `39f2474`, `12a5016`. Original-audio rank takes priority over bitrate. The given URL exposes no progressive MP4, so direct adaptive support was added. Retrying the same retained download still failed on the current network; metadata and one media request returned200 while the selected video request did not complete. No browser cookies or model retries were used. The completed dubbing sample uses the previously downloaded original through the ordinary upload path.
- Actual PCM source and selected-natural waveforms: reviewed `e9777bb`, `89c4f82`. Source:2856480frames/48000Hz/59510ms; natural voice:723600frames/24000Hz/30150ms; both600bins. Exact waveform-download hashes verified.
- Reference upload/parameter authoring and source/waveform UI: reviewed `9f7bef9`, `2388984`, `64d9431`. Fresh browser checks displayed real waveforms; source seek12000ms moved the original player to12s, readyState4/errornull. Natural seek1000ms moved that audio to1s, paused/errornull. Repeating a waveform cache hit retained the graph. Real service defaults/inheritance and upload controls rendered without writing an AudioReview.
- Final frontend:21files/127tests passed7.54s, Node24 TypeScript and production Vite build passed. Old workbench test doubles were updated to valid current-workflow/fit-settings read contracts; the source paging assertion waits for its actual asynchronous reload. No assertion was relaxed.
- Backend: reuse the completed frozen `b60212a` full1063-test baseline. Later increments each have focused actual-media/PostgreSQL/recovery/privacy tests and independent reviews. A second full backend suite was not started for these small increments. Final Ruff check/format and frozen lock check passed. Formatting11files preserved all242Python ASTs exactly. Wheel and source distribution built successfully; an initial offline build lacked cached hatchling, then the ordinary registry build succeeded.
- Preserving activation at schema0014 checked all62 old-table fingerprints, encrypted credential bytes/key, integrity and foreign keys. Final read-only check found original source/8segments unchanged, both current deliveries intact, pipeline completed/clean, model run IDs/statuses/attempts unchanged, no queued jobs and AudioReview0.

## Deployment boundary

`deploy/` contains separate Web/API/Worker/migration containers, private PostgreSQL/S3 configuration, trusted proxy policy and actual codec/R3/font/Unicode-wrap build checks. Fresh installed-wheel verification was performed in the earlier packaging increment. Docker/Podman/Nginx are unavailable here, so no Linux image build, Compose startup, cloud bucket/TLS integration or public deployment is claimed. No Git push or public release was performed.
