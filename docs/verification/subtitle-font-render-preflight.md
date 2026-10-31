# Development subtitle-font render preflight

This is controller resource investigation for later 6C, using FFmpeg 7.1.1, libass 0.17.4, FriBidi 1.0.16 and HarfBuzz 11.4.1 on the current macOS worker. It does not implement product captions, verify Linux packaging, or establish typography for all 646 languages. No model call, global font installation, application configuration change or new Python dependency occurred.

The [previous resource record](subtitle-font-resource-preparation.md) proved source hashes and declared codepoint coverage. Actual rendering now exposes limitations that charset checks alone missed. Probe inputs, PNGs, logs and JSON records are retained outside Git under `/Users/moose/.agent-reach/fixtures/subtitle-fonts-20261031/`.

## Actual observations

1. `development-render-probe.ass` renders five short Chinese, Japanese, Arabic-with-marks, Hebrew-with-marks/numbers and Latin samples into a 960×540 frame. The frame was visually inspected. CJK/Arabic/Latin use the requested Noto faces, while requested Noto Sans Hebrew falls back through system Helvetica to Lucida Grande. Visible Hebrew is therefore not proof that the packaged Hebrew font was used.
2. Passing the entire resource directory as `fontsdir` also makes libass try to open license/JSON/ASS files as fonts. Keep font binaries in a dedicated allowlisted directory, with licenses/manifests elsewhere. A binary-only directory of symlinks was used for subsequent probes; nothing was installed globally.
3. An additional **original static** [Noto Sans Hebrew Regular](https://github.com/notofonts/noto-fonts/blob/ffebf8c1ee449e544955a7e813c54f9b73848eac/hinted/ttf/NotoSansHebrew/NotoSansHebrew-Regular.ttf) was acquired from the pinned official repository. Blob `5b43c56fa688b0ff9302a82cbebb1dae1201cf7f`, 26,900 bytes, SHA-256 `a7fa16fffb27bedb060a0866267c29e9859aeb9c21cc33f5b3aaf6eb062eca85`. The repository's [original LICENSE](https://github.com/notofonts/noto-fonts/blob/ffebf8c1ee449e544955a7e813c54f9b73848eac/LICENSE) is retained as `NotoStaticHebrew-LICENSE.txt`, SHA-256 `0dab92d0544f7b233403f14b84a663bdbfa746982eda629e7f4f9ffe1b036feb`. `static-hebrew-acquisition.json` records both files. The original variable font and evidence remain unchanged.
4. The static face is selected correctly for Hebrew letters/marks, but lacks ASCII digits: libass logs missing U+0032 and selects system Helvetica for the numeric run. The static-only experiment's initial no-fallback assertion failed for this real reason; its PNG/log remain available. It is not recorded as a successful no-fallback render.
5. A controlled ASS font override assigning only `2026` to Noto Sans removes system-font fallback in `development-render-controlled-spans.png`. However, visual comparison shows the digits move to the opposite side of the Hebrew phrase. Explicit style encoding 177/178 and two Unicode control experiments did not change that frame (same SHA). Therefore this is **not an accepted generic RTL font-run solution**. Font selection logs alone do not prove logical text order.

The controlled frame SHA-256 is `212e7a97a6a0b08bd544fa975406f8d4b22cf3f326be4bf9777fbd36b7ef9644`; the initial variable-font/system-fallback frame is `9a3bd5e4ab189736ecb52891f35f8f2ac075005c83884bbd21313804493434d9`. These synthetic frames contain no source-video or generated speech. Human inspection of these few samples is separate from comprehensive shaping and language-quality acceptance.

## Concrete requirements retained for 6C

- Package and verify an explicit font allowlist with original license texts; do not depend on macOS system fonts or scan arbitrary non-font files.
- Verify actual selected face/weight and every sample's glyph coverage, including punctuation and numbers. Charset metadata is only a precheck.
- Test mixed RTL/LTR text, numbers, combining marks and font-run boundaries against a declared logical-order reference, with representative rendered frames. Preserve the original text and record trusted generated formatting separately; do not manually reorder user text to hide a renderer problem.
- Validate the actual Linux worker/font-provider combination and report unavailable fonts or missing glyphs. The current CoreText observations do not establish Fontconfig behavior in the deployment image.
- Retain source/target/bilingual SRT/VTT/ASS escaping, mapped timing, overlaps and post-retime burn-in tests in 6C. This resource investigation closes none of those product gates.
