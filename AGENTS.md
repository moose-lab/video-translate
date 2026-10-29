# Video Translate

This is the user's approved SaaS project, not a local-model desktop app.

- AI inference goes to remote providers, Hugging Face first. Do not install or download model weights, torch, transformers or local ASR/TTS runtimes in this project.
- Follow the approved spec in docs/superpowers/specs/2026-10-29-video-translate-saas-design.md and the implementation plans.
- Use Superpowers test-driven development: demonstrate the missing behavior with a failing test, implement it, then verify. Record commands and outcomes.
- Keep provider test doubles explicitly in tests; never label them as real inference results or show invented progress in the product.
- Every project, asset, event, task and download is scoped to its workspace. Preserve original transcripts and revision lineage.
- Never log provider tokens, passwords, cookies, complete request headers or signed URLs. Do not return secrets to the frontend.
- Server app and worker are separate processes. Persistent state and remote request IDs must survive restarts.
- Do not replace a failed voice clone with a system voice or silently substitute a model/language.
- Use focused modules, typed contracts and existing patterns. Do not push or publish to an external destination without the owning agent's coordination.
- Subagents are permitted by the active Superpowers subagent-driven-development workflow. The controller assigns one implementation task at a time and runs independent spec and quality reviews.
