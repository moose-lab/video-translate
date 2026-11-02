# Superpowers v7.0.1 review — gates, tests, packaging, documentation

Reviewed read-only range `1b5d47d63aee7f5bb52a59bcfb3cfec9c646b112..584473af495391a1e6553cff8a2009723e2a5ea6` in `/Users/moose/Documents/Codex/2026-10-28/ace-studio-3/outputs/video-translate` using the exact v7.0.1 Senior Code Reviewer template. No checkout, index, HEAD, source, test, dependency, database, media, or model state was changed. This report is the only file written, under `/tmp`.

### Strengths

- The fast gate is explicit about its limited coverage: `Makefile:5-7,11-22` runs catalog/runtime/adapter/surface/configuration/network/translation/timeout contracts; `README.md:63-72` says it does not replace the full media regression. The full backend target refuses to silently omit opt-in PostgreSQL coverage (`Makefile:28-31`).
- CI uses the same Make targets, frozen dependency installs, read-only repository permissions, finite timeouts, and SHA-pinned actions (`.github/workflows/ci.yml:5-45`). The backend job installs FFmpeg before tests, which is required by the actual tiny-MP4 fixture in `tests/conftest.py`.
- All five Action pins were independently verified against their exact upstream repository commit endpoints using Agent Reach's GitHub CLI route (`/opt/homebrew/bin/gh api repos/OWNER/REPO/commits/SHA`). Each endpoint returned exit 0 with an identical full SHA. Verified URLs are listed below.
- The deletion does not merely erase all related tests: `tests/test_provider_adapters.py` redirects translation and clone-preparation request/credential assertions to actual durable-path entry points; malformed Gradio submissions, status/result validation, and bounded transport behavior remain covered. Removal of the dedicated dead-wrapper tests is justified by removal of their only implementation, rather than a relaxed production assertion.
- The split retains existing timeout and uncertainty assertions in `tests/test_chat_wait_policy.py`, including one-POST behavior, secret sanitization, prepared checkpoints, explicit uncertainty acknowledgement, heartbeat renewal, and lost-lease publication fencing. New helper tests check preserved failure categories and credential policy (`tests/test_provider_runtime.py:55-118`).
- Updated QC concurrency tests patch the new runtime import locations while retaining their original assertions (`tests/test_voice_qc_arbitration.py:105-187`; `tests/test_voice_qc_operations.py:675-752`). The helpers' move did not weaken those tests' expected no-I/O local adoption or one-paid-POST guarantees.
- `deploy/Dockerfile.web:15` consumes `deploy/nginx.conf`; no active packaging/deployment reference to the deleted `web/nginx.conf` was found. The modified historical verification document distinguishes the old gateway from the maintained configuration.
- The audit and README separate supplied CI/local evidence, historical full-backend evidence, human listening, actual inference, and unperformed Linux/cloud deployment. Supplied logs were read without repeating the suites: `/tmp/vt-modularity-make-check.log` records 147 backend and 127 frontend tests plus Ruff/format/lock/type/build checks; `/tmp/vt-modularity-package.log` records successful sdist/wheel builds. Archive content inspection was supplied by the controller, not repeated or independently represented as a live installation test.

### Issues

#### Critical (Must Fix)

None found in this review's domain.

#### Important (Should Fix)

None found in this review's domain.

#### Minor (Nice to Have)

Both items below were found at the reviewed committed head and are now resolved in the controller's two-file working-tree follow-up, independently read and checked after the original review. No unresolved issues remain in this review's domain.

1. **Document the fixture's required PostgreSQL role in the new full-test instructions.**
   - File: `README.md:65-69` (new onboarding text).
   - Evidence: the example uses arbitrary `TEST_USER`, while existing fixtures execute `CREATE DATABASE ... OWNER vt_test`, e.g. `tests/test_translation_postgresql.py:21-25` and `tests/test_voice_qc_arbitration.py:33-41`. The role-name dependency predates this diff, but the new quick-start does not expose it.
   - Impact: a developer following the new instructions against a clean disposable PostgreSQL instance can pass the Makefile's nonempty-variable guard and still fail with `role "vt_test" does not exist` (or lack membership/ownership rights).
   - Fix: document creation of an isolated test-only `vt_test` LOGIN/CREATEDB role and use that role in the example URL, or separately make fixtures use their authenticated test owner. The documentation-only fix is sufficient for this change.

2. **Point the upstream translation citation at the behavior it describes.**
   - File: `docs/engineering/model-modularity-audit.md:16`.
   - Evidence: at the exact pinned VoiceStudio revision, the `#L389-L425` translation-branch link covers `_resolve_translation_context` and cache persistence. The stated already-LLM skip is supported by `dub_translate.py:1247-1259` and `1295-1315`; its call site is at `857-862`. These ranges were read directly from the pinned GitHub contents endpoint.
   - Impact: the audit's conclusion is supported, but its direct citation leads reviewers to unrelated code and makes the claimed comparison harder to reproduce.
   - Fix: change the translation citation to `#L1247-L1259` or include the `#L1295-L1315` branch as well.

### Recommendations

The two small documentation corrections have been applied and re-reviewed. Keep the existing distinction between the fast PR gate and the full PostgreSQL/media gate; there is no basis from this review for adding real inference to CI or rerunning the complete suite for this documentation adjustment.

### Declined to judge

- Production adapter/catalog/runtime semantic correctness: assigned to the separate production-semantics reviewer; this seat inspected those lines only to establish coverage and import-target validity.
- Full backend/media/PostgreSQL runtime pass at the reviewed head: intentionally not repeated per controller instruction; fresh focused/fast evidence is present, historical complete-suite results are explicitly historical.
- Live GitHub Actions job success: no push or remote workflow run occurred; pin existence and workflow wiring were verified, not a hosted runner execution.
- Linux Docker/Nginx/Compose operation, live managed PostgreSQL/S3/TLS behavior, or public deployment: unavailable/unexecuted and explicitly outside this increment's acceptance claim.
- Actual paid inference, protected preview data, and sample listening/quality acceptance: intentionally untouched and still separate acceptance states.
- Exact parity of pnpm versions between existing Docker packaging and the new local/CI instructions: Dockerfile's pnpm 11.25.0 versus local/CI 9.12.2 is pre-existing packaging state; no introduced incompatibility was established, and Linux image execution remains explicitly unverified.
- Independent legal provenance/AGPL compliance determination or an exhaustive audit of VoiceStudio's entire local-model implementation: beyond this gates/documentation review; selected linked upstream claims were source-checked without copying implementation.

### Assessment

**Ready to merge? Yes**, within this review's domain, including the reviewed two-file documentation follow-up.

**Reasoning:** No important test weakening, broken gate wiring, invalid Action pin, or current packaging reference to the deleted gateway was found. The onboarding and citation-anchor findings are both resolved in the reviewed working-tree follow-up; no remaining findings establish a production regression.

### Action pin verification evidence

All URLs below were queried as exact commit API endpoints and returned the identical SHA (exit 0):

- [actions/checkout](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1) — `3d3c42e5aac5ba805825da76410c181273ba90b1`
- [actions/setup-python](https://github.com/actions/setup-python/commit/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0) — `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0`
- [astral-sh/setup-uv](https://github.com/astral-sh/setup-uv/commit/68559e99cc807c1eb7e9238fd43a15bba460eec2) — `68559e99cc807c1eb7e9238fd43a15bba460eec2`
- [pnpm/action-setup](https://github.com/pnpm/action-setup/commit/ea17c68df8912ef543352723c149a84f56e3d413) — `ea17c68df8912ef543352723c149a84f56e3d413`
- [actions/setup-node](https://github.com/actions/setup-node/commit/949feb2413d6458794dcd2491c4babbbce0c15c1) — `949feb2413d6458794dcd2491c4babbbce0c15c1`

### Documentation follow-up review

Independently inspected the exact uncommitted `git diff -- README.md docs/engineering/model-modularity-audit.md` after the controller's correction. `README.md:65-68` now requires a pre-created `vt_test` role with LOGIN/CREATEDB on the isolated instance, a configured password, and a URL using that role. This matches the existing fixture owner contract. The audit's translation citations now point to the already-LLM explanation at `1247-1259` and the real branch at `1295-1315` in the same pinned upstream revision; those ranges were read directly during this review. `git diff --check` passed. Only these two documentation files were modified in the working tree by the controller. No tests were rerun for this prose/link-only follow-up.

**Unresolved items: none in this review's domain.**
