# AGENTS.override.md

This override aligns guidance with the lean interactive workflow.

- Primary workflow: `pnpm dev`.
- Baseline is driven through the API/web staged flow.
- Keep modules minimal: models/store/engine/llm/prompts plus the API entrypoint.
- Validate changes with `python -m pytest -q`, `pnpm lint`, `pnpm typecheck`, and `pnpm build`.
