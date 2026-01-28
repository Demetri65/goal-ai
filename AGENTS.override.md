# AGENTS.override.md

This rewrite overrides existing guidance.

- Delete legacy code; this is a clean rewrite.
- Keep the codebase minimal: only models + store + engine + llm + cli.
- Use Pydantic v2 for schemas.
- Use OpenAI Responses API structured outputs for LLM calls, with a Mock provider fallback.
- Validate changes with `python -m pytest -q` and `smartgot --help`.
