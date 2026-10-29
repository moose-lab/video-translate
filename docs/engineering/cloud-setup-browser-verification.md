# Cloud setup: independent browser verification

Verified2026-10-29 through the running local API and React interface using CUA. This is development-preview evidence, not a deployed SaaS or completed dubbing sample.

The workspace credential changed from unconfigured to configured through the protected page. The controller did not copy the token supplied in chat into code, commands, tests or configuration. Only the configured badge and a read-only database aggregate were inspected; one configured credential was present. Secret content was neither returned nor decrypted by the controller.

The controller saved the five preset connections through the interface. Translation was explicitly configured as `Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra`. The official public model API reported a live conversational DeepInfra mapping when selected. The full selection is retained for inference while metadata checks use the Hub repository component. Sources: [model metadata](https://huggingface.co/api/models/Qwen/Qwen3-235B-A22B-Instruct-2507?expand=inferenceProviderMapping), [HF chat API](https://huggingface.co/docs/inference-providers/tasks/chat-completion).

The original preview database and server key were preserved during the API restart. The explicit administrator proxy and trusted DNS configuration were enabled without weakening TLS verification. Five real metadata checks were then invoked through the browser, with authoritative persisted check summaries inspected read-only:

| Slot | Connection revision | Reachable | Credential validation | Inference verified |
| --- | --- | --- | --- | --- |
| Separation | 1 | true | not required/untested | false |
| Transcription | 1 | true | not required/untested | false |
| Translation | 2 | true | true | false |
| Synthesis | 1 | true | true | false |
| Verification | 1 | true | true | false |

Checks occurred between15:53 and15:55UTC. These are actual service schema/health/model metadata and HF account checks. No source audio or model inference request was submitted. Valid HF account authentication does not prove Inference Providers permission, available credit, successful synthesis, language quality or final export.

The protected token input remained empty after save. A screenshot of the service page is saved outside the repository in the parent outputs directory, `../../../VideoTranslate-service-setup.png` relative to this document. The browser exposes only configuration state; no token prefix, suffix, ciphertext, account response or signed media URL was placed in this evidence.

The current preview was restarted during the review-fix work; a few subsequent metadata-only fixes were committed after that restart. Code review and automated verification target the committed code, independently of these live network observations. Later domain and end-to-end tests must use the current build with the same protected state.

After reloading the browser, all five saved connections, checks and the configured credential badge were restored from the API; the token input remained blank. A later actual608-pixel viewport inspection found that the mobile service grid placed its action container in the narrow index column. Fix`c20ef3e` places whole buttons in the content column and details on a separate row. The controller verified the same actual viewport after hot reload: readable horizontal buttons, no overlap, and persisted check text. Result screenshot: `../../../VideoTranslate-cloud-checks.png`. This establishes the observed608-pixel layout only; smaller viewports were not independently exercised.

## Independent PostgreSQL check

The controller also verified the cloud-services database path independently against an isolated archive of code`67ff839`, so the subsequent in-progress domain changes did not alter the verification target. A live PostgreSQL14.18 server was confirmed before creating a new temporary database. Alembic upgrade to0003, metadata parity check, downgrade to0002, re-upgrade to0003 and a second parity check all exited0 with no pending upgrade operations.

The same isolated application saved an explicitly fake HF credential, created a separation connection, and submitted two simultaneous updates with the same expected connection revision. Responses were exactly200 and409. A second registered workspace saw no configured credential and no saved separation connection. No provider request or real user credential was involved. The controller closed the application, dropped only its temporary database successfully, and removed its temporary archive. The development PostgreSQL server remains available for the next domain migration tests.

## Preview process recovery,2026-10-30

During task4B verification the old API/frontend execution handles were authoritatively absent and direct localhost connections to8000/5173 failed. The controller did not treat an observation timeout alone as evidence to restart. The browser had retained the prior page, so its visible configured badge alone did not prove either process was alive.

Before restoring service, the controller used SQLite's backup API to make a consistent private database backup and preserved the existing server key under`/tmp/videotranslate-setup-preview/backups/before-stable-restart/`; both files retain mode600 and the directory is mode700. No credential value was displayed. A temporary archive of`67ff839` was extracted, and read-only schema comparison against that pinned metadata returned no differences before its application factory was allowed to start. This restores the verified increment3 preview without prematurely applying in-progress4A/4B tables through development`create_all`.

The API and Vite server were restarted on their original loopback ports. Direct no-proxy HTTP to5173 returned200. CUA reloaded the existing page and confirmed the saved session, configured/blank token input, all five saved connection states and earlier metadata-check summaries. No configuration-save, provider-check or inference button was clicked. The restored image is in the parent outputs directory as`../../../VideoTranslate-preview-restored.png`. The temporary stable-source path is recorded in`/tmp/videotranslate-stable-preview-root`; the protected database and key remain at their original paths.

The new analysis/reference implementation is not running against the user preview yet. After both4B gates pass, stop/reuse the actual current processes, take a fresh protected backup, recheck the baseline and explicitly stamp/upgrade the verified schema before starting the current application. Preserve the same database/key and user credential; do not request or copy another token.
