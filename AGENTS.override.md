# AGENTS.override.md

This override aligns guidance with the lean interactive workflow.

- Primary command: `smartgot run --goal "..."` (interactive).
- Baseline is interactive Q&A (root + parent + current node).
- Keep modules minimal: models/store/engine/llm/cli/prompts only.
- Validate changes with `python -m pytest -q` and `smartgot --help`.
