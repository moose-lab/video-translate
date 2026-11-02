# Production Python review — Superpowers v7.0.1

Base: `1b5d47d63aee7f5bb52a59bcfb3cfec9c646b112`
Head: `584473af495391a1e6553cff8a2009723e2a5ea6`

Scope: all changed production Python modules and their surrounding production callers; compatibility, safety/error semantics, and coupling. Reviewed read-only using the exact v7.0.1 code-reviewer template. No checkout/index/HEAD changes, broad test reruns, real inference, installs, credential access, or runtime/database/media changes.

### Strengths

- `src/videotranslate/providers/catalog.py:16-108` uses frozen records, immutable nested declarations, and mapping proxies for the seven existing adapter IDs. It consolidates role, credential, model/endpoint, control, and checked-metadata declarations without introducing dynamic dispatch.
- `src/videotranslate/providers/settings.py:52-119` derives capability and preset policy from those declarations while keeping model-specific Whisper declarations and Demucs provenance explicit. The production route retains the same seven-ID Pydantic enum and five slots.
- Shared `provider_failure`, `credential_token`, `materialize`, `normalize_asr`, and `transcribe` functions retain exact AST-equivalent bodies. The failure mapping therefore preserves the distinction between definitive failure, accepted-job access failure, and uncertain submission; stored-input reads retain size/hash checks and cancellation checks.
- Durable paths remain intact: `src/videotranslate/dubbing/remote_synthesis.py:174-198` and `src/videotranslate/dubbing/analysis.py:289-325` still checkpoint before named submission, stop uncertain submissions for review, and checkpoint terminal data before downloading. Removal affects unused shortcut submit/poll wrappers, not these production paths.
- Production-wide reference searches found no remaining caller of the removed `translate`, `submit_clone`/`poll_clone`, `submit_separation`/`poll_separation`, `RemoteResult`, or old `providers.hf_router` Python import path. Cache evidence and persisted provider IDs remain stable.

### Issues

#### Critical (Must Fix)
None found in the reviewed production Python changes.

#### Important (Should Fix)
None found in the reviewed production Python changes.

#### Minor (Nice to Have)
None worth requesting in this bounded behavior-preserving refactor.

### Recommendations

No production Python change requested. Keep the independent tests/CI/packaging/deployment review as a separate merge gate.

### Verification

- Manually read the production diff and surrounding route/stage/cache callers, including authentication, credentials, transport setup, synthesis, separation, translation, source ASR, voice QC, and publication boundaries.
- Independently compared the six moved helper bodies listed above against the base commit by AST: exact equivalence.
- Independently checked current Pydantic adapter enum against the base route's literal declaration; checked catalog IDs, five-slot ordering, and defaults: unchanged/consistent.
- Imported the current execution registry, provider routes, translation workflow, and voice-QC cache through the existing `.venv` with `PYTHONPATH=src` and bytecode writes disabled: success. An initial probe without `PYTHONPATH=src` resolved the environment's installed package rather than this source tree and was corrected; it is not counted as a source failure.
- Did not rerun broad tests or rely on the reported baseline-equivalence probe as the verdict.

### Declined to judge

- Tests, Makefile, CI, documentation, and deleted nginx configuration/deployment behavior: assigned to the other reviewer, outside this production Python seat.
- Real remote model availability, output quality, latency, billing, and current upstream licenses: require live service/inference or commercial verification; this review was explicitly read-only and prohibited real inference. Catalog declarations do not claim inference verification.
- Compatibility for third-party Python consumers of intentionally deleted private helper/import paths: the specified compatibility contract is the HTTP API and persisted application behavior; no in-repository production consumer or published stable Python API contract was found.
- Recovery from manually corrupted database adapter IDs outside the existing seven-ID contract: not a supported migration/input state in this range; no schema or adapter-ID migration was introduced. Normal owner writes remain validated.

### Assessment

**Ready to merge? Yes** — for the production Python scope.

**Reasoning:** No introduced correctness, compatibility, credential-policy, or durable-operation regression was found. The refactor removes unused paths and reduces cross-stage coupling while preserving the production execution and persistence semantics inspected; the other review seat still owns its independent merge gate.
