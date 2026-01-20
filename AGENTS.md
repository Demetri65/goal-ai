# SMART-GoT prototype: Codex working agreements

This repository is a **research prototype scaffold**. Optimize for **clarity** and **small diffs**.

## Hard constraints
- Keep the codebase small and readable; avoid production frameworks.
- Do not add heavyweight dependencies unless explicitly requested.
- Prefer pure functions + typed Pydantic models.

## Validation
- After changes, run:
  - `python -m pytest -q`
  - and (if you modify CLI behavior) run a quick smoke command like:
    - `smartgot stage1 --intent "test" --out /tmp/g.json`

## Output expectations
- When fixing an issue, include:
  1) what you changed,
  2) how you validated (commands + results),
  3) any remaining TODOs (if unavoidable).

## Style
- Use type hints.
- Keep modules <= ~200 lines when possible.
- Favor explicit JSON schemas over clever abstractions.
