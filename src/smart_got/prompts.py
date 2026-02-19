from __future__ import annotations

import json
from typing import TypedDict

from smart_got.models import BaselineQA, BaselineQuestion, Node


class _BaselineQuestionSpec(TypedDict):
    id: str
    category: str
    template: str


_BASELINE_QUESTION_SPECS: tuple[_BaselineQuestionSpec, ...] = (
    {
        "id": "achievable_time_budget",
        "category": "achievable",
        "template": (
            "How much time can you reliably commit each week to '{node_title}' "
            "(hours/week)?"
        ),
    },
    {
        "id": "achievable_skill_gaps",
        "category": "achievable",
        "template": (
            "Which skill gaps or capability limits could make '{node_title}' hard to execute?"
        ),
    },
    {
        "id": "resources_available",
        "category": "resources",
        "template": (
            "What resources (people, budget, tools) are already available "
            "for '{node_title}' under '{parent_label}'?"
        ),
    },
    {
        "id": "timebound_deadline",
        "category": "time_bound",
        "template": (
            "What hard deadline or target date should '{node_title}' meet "
            "to stay aligned with '{root_title}'?"
        ),
    },
    {
        "id": "timebound_milestone_cadence",
        "category": "time_bound",
        "template": (
            "What milestone cadence (for example weekly/biweekly checkpoints) is realistic "
            "for '{node_title}' before the target date?"
        ),
    },
    {
        "id": "constraints_dependencies",
        "category": "constraints",
        "template": (
            "What constraints or dependencies from '{parent_label}' could limit "
            "'{node_title}'?"
        ),
    },
    {
        "id": "risks_unknowns",
        "category": "unknowns",
        "template": "What risks or unknowns are most likely to block '{node_title}'?",
    },
    {
        "id": "definition_of_done",
        "category": "assumptions",
        "template": (
            "What concrete output would make '{node_title}' realistically "
            "achievable in this phase?"
        ),
    },
)


def decompose_instructions() -> str:
    return (
        "You are decomposing a SMART goal node into workstreams.\n"
        "Return only structured output and follow all constraints exactly.\n"
        "Constraints:\n"
        "- Produce 5 to 9 WORKSTREAM children.\n"
        "- Children must be non-overlapping and collectively cover the parent goal.\n"
        "- Each child must include:\n"
        "  - workstream: short label\n"
        "  - title: descriptive, concrete, no placeholders\n"
        "  - smart.specific: non-empty\n"
        "  - smart.measurable: non-empty\n"
        "  - smart.relevant: non-empty\n"
        "  - smart.achievable/time_bound may be empty.\n"
        "- Do not use ampersands in workstream or title. Use the word 'and'.\n"
        "- Avoid generic titles such as 'Subgoal N', 'Task N', 'Workstream N', or placeholders.\n"
        "- Keep workstreams scoped to execution domains, not vague activities."
    )


def build_decompose_input(
    node: Node,
    context: str,
    target_children: int,
    min_children: int,
    max_children: int,
) -> str:
    return (
        f"Target child count: {target_children} (allowed range {min_children}-{max_children}).\n"
        f"Parent node title: {node.title}\n"
        f"Parent node workstream: {node.workstream}\n"
        "Context:\n"
        f"{context}"
    )


def baseline_questions_instructions() -> str:
    return (
        "You are generating baseline interview questions for a SMART goal node.\n"
        "Return only structured output and follow all constraints exactly.\n"
        "Constraints:\n"
        "- Generate 4 to 8 questions.\n"
        "- Questions must target:\n"
        "  - Achievable: resources, weekly time budget, skill gaps, and constraints.\n"
        "  - TimeBound: hard deadline, target date, milestone cadence.\n"
        "  - Constraints and risks.\n"
        "- Questions must reference parent/root context where relevant.\n"
        "- Keep questions specific and answerable in one response.\n"
        "- Use categories: achievable, time_bound, resources, constraints, unknowns, assumptions."
    )


def build_baseline_questions_input(node: Node, context: str) -> str:
    return (
        f"Node title: {node.title}\n"
        f"Node workstream: {node.workstream}\n"
        "Context:\n"
        f"{context}"
    )


def baseline_apply_instructions() -> str:
    return (
        "You are applying baseline interview answers to a SMART goal node.\n"
        "Return only structured output and follow all constraints exactly.\n"
        "Constraints:\n"
        "- Fill smart_patch.achievable and smart_patch.time_bound as concretely as possible.\n"
        "- Populate NodeBaseline fields: baseline_notes, assumptions, constraints, unknowns.\n"
        "- Keep layer_mutations optional.\n"
        "- If layer_mutations are used, they must ONLY touch siblings in the same parent layer.\n"
        "- Do not mutate nodes outside the provided parent scope.\n"
        "- Rationale must explain how answers changed achievable/time_bound."
    )


def build_baseline_apply_input(
    node: Node,
    context: str,
    siblings: list[Node],
    qa_pairs: list[BaselineQA],
) -> str:
    siblings_payload = [
        {
            "id": sibling.id,
            "title": sibling.title,
            "workstream": sibling.workstream,
            "smart": sibling.smart.model_dump(mode="json"),
        }
        for sibling in siblings
    ]
    qa_payload = [qa.model_dump(mode="json") for qa in qa_pairs]
    return (
        f"Node title: {node.title}\n"
        f"Node id: {node.id}\n"
        f"Parent id: {node.parent_id or ''}\n"
        "Context:\n"
        f"{context}\n\n"
        "Sibling nodes (same parent only):\n"
        f"{json.dumps(siblings_payload, indent=2)}\n\n"
        "Baseline Q&A:\n"
        f"{json.dumps(qa_payload, indent=2)}"
    )


def plan_instructions() -> str:
    return (
        "You are generating an execution plan for a SMART goal node.\n"
        "Return only structured output and follow all constraints exactly.\n"
        "Constraints:\n"
        "- Return 3 to 6 tasks and 1 to 3 milestones.\n"
        "- Each task must include:\n"
        "  - title\n"
        "  - description\n"
        "  - success_criteria\n"
        "  - depends_on\n"
        "  - estimate_hours when possible\n"
        "  - due and relative_timing when possible\n"
        "- Milestones should tie back to the node time_bound target.\n"
        "- smart_patch may be empty strings if no SMART changes are needed.\n"
        "- Avoid placeholder task names."
    )


def build_plan_input(node: Node, context: str) -> str:
    return (
        f"Node title: {node.title}\n"
        f"Node id: {node.id}\n"
        f"Node workstream: {node.workstream}\n"
        f"Node SMART: {json.dumps(node.smart.model_dump(mode='json'))}\n"
        "Context:\n"
        f"{context}"
    )


def build_baseline_questions(
    root_title: str,
    parent_title: str | None,
    node_title: str,
    min_questions: int = 4,
    max_questions: int = 8,
) -> list[BaselineQuestion]:
    parent_label = parent_title or root_title
    bounded_min = max(4, min_questions)
    bounded_max = max(bounded_min, min(8, max_questions))
    target_count = max(bounded_min, min(6, bounded_max))

    seed = sum(ord(ch) for ch in f"{root_title}|{parent_label}|{node_title}")
    by_category: dict[str, list[_BaselineQuestionSpec]] = {}
    for spec in _BASELINE_QUESTION_SPECS:
        by_category.setdefault(spec["category"], []).append(spec)

    required_categories = ["achievable", "resources", "time_bound", "constraints", "unknowns"]
    picked_specs: list[_BaselineQuestionSpec] = []
    used_ids: set[str] = set()

    # Ensure required coverage across Achievable, TimeBound, constraints, and risks.
    for idx, category in enumerate(required_categories):
        candidates = by_category.get(category, [])
        if not candidates:
            continue
        selected = candidates[(seed + idx) % len(candidates)]
        if selected["id"] in used_ids:
            continue
        picked_specs.append(selected)
        used_ids.add(selected["id"])

    # Fill remaining slots deterministically while respecting limits.
    for offset, spec in enumerate(_BASELINE_QUESTION_SPECS):
        if len(picked_specs) >= target_count:
            break
        if spec["id"] in used_ids:
            continue
        if (seed + offset) % 2 == 0 or len(picked_specs) < bounded_min:
            picked_specs.append(spec)
            used_ids.add(spec["id"])

    while len(picked_specs) < bounded_min:
        for spec in _BASELINE_QUESTION_SPECS:
            if spec["id"] in used_ids:
                continue
            picked_specs.append(spec)
            used_ids.add(spec["id"])
            if len(picked_specs) >= bounded_min:
                break

    return [
        BaselineQuestion(
            id=spec["id"],
            category=spec["category"],
            question=spec["template"].format(
                node_title=node_title,
                root_title=root_title,
                parent_label=parent_label,
            ),
        )
        for spec in picked_specs[:bounded_max]
    ]
