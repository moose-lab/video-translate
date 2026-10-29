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
