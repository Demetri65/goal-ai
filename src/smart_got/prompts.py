from __future__ import annotations


def build_baseline_questions(
    root_title: str, parent_title: str | None, node_title: str
) -> list[str]:
    parent_label = parent_title or root_title
    return [
        f"What is the current state for '{node_title}' relative to '{root_title}'?",
        f"What measurable outcome confirms progress on '{node_title}'?",
        f"What constraints or dependencies from '{parent_label}' affect this work?",
        f"What assumptions need validation for '{node_title}'?",
        f"What risks or unknowns could block '{node_title}'?",
    ]
