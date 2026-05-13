from __future__ import annotations

import json
from typing import TypedDict

from smart_got.models import BaselineQA, BaselineQuestion, Node


class _BaselineQuestionSpec(TypedDict):
    id: str
    category: str
    template: str
    guide: str
    research_basis: str


_BASELINE_QUESTION_SPECS: tuple[_BaselineQuestionSpec, ...] = (
    {
        "id": "achievable_time_budget",
        "category": "achievable",
        "template": "How many hours per week can you commit to '{node_title}'?",
        "guide": "Give one realistic range, such as 3-5 hours/week.",
        "research_basis": "Capacity planning reduces optimism bias.",
    },
    {
        "id": "resources_support",
        "category": "resources",
        "template": "Which single resource is most constrained for '{node_title}'?",
        "guide": "Name the limiting person, budget, tool, or approval.",
        "research_basis": "Constraint mapping improves feasibility estimates.",
    },
    {
        "id": "timebound_deadline",
        "category": "time_bound",
        "template": "What date must '{node_title}' be done by?",
        "guide": "Use YYYY-MM-DD or the closest fixed milestone.",
        "research_basis": "Temporal specificity improves commitment.",
    },
    {
        "id": "timebound_review_cadence",
        "category": "time_bound",
        "template": "How often should progress on '{node_title}' be reviewed?",
        "guide": "Give one cadence, such as weekly or milestone-based.",
        "research_basis": "Feedback loops improve goal attainment.",
    },
    {
        "id": "constraints_dependencies",
        "category": "constraints",
        "template": "What dependency from '{parent_label}' could block '{node_title}' first?",
        "guide": "Name one blocker, handoff, approval, or competing commitment.",
        "research_basis": "Pre-mortem obstacle mapping reduces slippage.",
    },
    {
        "id": "risks_unknowns",
        "category": "unknowns",
        "template": "What one uncertainty could change the scope of '{node_title}'?",
        "guide": "Name the uncertainty most likely to affect scope, timing, or feasibility.",
        "research_basis": "Uncertainty surfacing improves adaptive planning.",
    },
    {
        "id": "definition_of_done",
        "category": "assumptions",
        "template": "What evidence proves '{node_title}' is done?",
        "guide": "Name the observable artifact, decision, metric, or handoff.",
        "research_basis": "Definition of done reduces ambiguity.",
    },
    {
        "id": "execution_skill_gap",
        "category": "achievable",
        "template": "Which skill gap most threatens '{node_title}'?",
        "guide": "Name one capability gap and its severity.",
        "research_basis": "Capability checks improve achievability judgments.",
    },
)


def decompose_instructions() -> str:
    return (
        "You are decomposing a SMART goal node into workstreams.\n"
        "Return only structured output and follow all constraints exactly.\n"
        "Constraints:\n"
        "- Produce 5 to 9 WORKSTREAM children.\n"
        "- Children must be non-overlapping and collectively cover the parent goal.\n"
        "- Return children in chronological display order from earliest prerequisite "
        "to latest outcome.\n"
        "- Reason about which children are sequential and which can run in parallel.\n"
        "- Each child must include:\n"
        "  - workstream: short label\n"
        "  - title: descriptive, concrete, no placeholders\n"
        "  - depends_on: sibling child titles that should feed into or precede this child.\n"
        "  - smart.specific: non-empty\n"
        "  - smart.measurable: non-empty\n"
        "  - smart.relevant: non-empty\n"
        "  - smart.achievable/time_bound may be empty.\n"
        "- depends_on must contain only titles from the same returned children list.\n"
        "- Use depends_on for meaningful dependency/order paths; leave it empty when "
        "a child can start immediately.\n"
        "- Every depends_on title must refer to an earlier child in the returned list, "
        "so the DAG reads left to right with no backward edges or cycles.\n"
        "- Dependencies must be transitive: if A feeds B and B feeds C, then C's "
        "depends_on must include both A and B.\n"
        "- Sequential children should depend on earlier sibling titles.\n"
        "- Parallel children should share the same prerequisite title, or have no "
        "dependency when they can start immediately.\n"
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
        "- Generate 5 to 7 questions; hard bounds are 4 to 8 questions.\n"
        "- Each question object must include: id, category, question, guide, research_basis.\n"
        "- Each question must ask exactly one question and contain at most one question mark.\n"
        "- Keep question text short, explicit, and answerable in one sentence.\n"
        "- Use research-backed methods: goal specificity, capacity planning, implementation "
        "intentions, definition of done, obstacle pre-mortems, and feedback cadence.\n"
        "- Questions must target:\n"
        "  - Achievable: capacity, resource limits, and capability gaps.\n"
        "  - TimeBound: a target date and, when useful, a review cadence.\n"
        "  - Specific and Measurable: deliverable, evidence, or definition of done.\n"
        "  - Relevant: only if the current relevance is unclear or likely wrong.\n"
        "  - Constraints, dependencies, risks, and unknowns that affect feasibility.\n"
        "- Questions must reference parent/root context where relevant.\n"
        "- Keep guide short and action-oriented.\n"
        "- Keep research_basis to a short method tag, not a citation.\n"
        "- Use categories: achievable, time_bound, resources, constraints, unknowns, assumptions."
    )


def build_baseline_questions_input(node: Node, context: str) -> str:
    return f"Node title: {node.title}\nNode workstream: {node.workstream}\nContext:\n{context}"


def baseline_apply_instructions() -> str:
    return (
        "You are applying baseline interview answers to a SMART goal node.\n"
        "Return only structured output and follow all constraints exactly.\n"
        "Constraints:\n"
        "- Fill smart_patch.achievable and smart_patch.time_bound as concretely as possible.\n"
        "- Also patch smart_patch.specific, smart_patch.measurable, and smart_patch.relevant "
        "when answers clarify deliverables, evidence of done, scope, or purpose.\n"
        "- Replace vague SMART fields with sharper wording; leave a field empty only when the "
        "answers do not improve it.\n"
        "- Achievable must reflect capacity, resources, constraints, and capability gaps.\n"
        "- TimeBound must include the target date or review cadence when provided.\n"
        "- Populate NodeBaseline fields: baseline_notes, assumptions, constraints, unknowns.\n"
        "- Keep layer_mutations optional.\n"
        "- If layer_mutations are used, they must ONLY touch siblings in the same parent layer.\n"
        "- Do not mutate nodes outside the provided parent scope.\n"
        "- Rationale must explain the Achievable/TimeBound changes and any other SMART patches."
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
        "- Return 3 to 6 tasks.\n"
        "- Choose the exact task count from the goal scope; do not default to five tasks.\n"
        "- Prefer 3 or 4 tasks unless the goal clearly needs more execution steps.\n"
        "- Use 3 tasks for narrow goals, 4 for moderate goals, 5 only when the goal is complex, and 6 only for broad multi-workstream goals.\n"
        "- Do not pad the plan with administrative filler tasks just to match sibling task counts.\n"
        "- When sibling task counts are present in the context, vary the count when this goal's scope is materially different.\n"
        "- When sibling plan task details are present in the context, treat them as already-owned work and do not create overlapping tasks.\n"
        "- Tasks must be returned in chronological execution order from earliest prerequisite to latest completion step.\n"
        "- If Current SMART TimeBound is filled, every task due/relative_timing must fit within that time boundary.\n"
        "- Use depends_on only for earlier task titles in this same plan; do not point dependencies forward in time.\n"
        "- Parallel tasks may share timing only when their deliverables are clearly distinct and non-overlapping.\n"
        "- Keep output concise for graph cards: title under 54 characters, description under 110 characters, and success_criteria under 100 characters.\n"
        "- Use one compact action phrase per title and one short sentence per description.\n"
        "- Do not repeat the node title in every task.\n"
        "- Each task must include:\n"
        "  - title\n"
        "  - description\n"
        "  - success_criteria\n"
        "  - depends_on\n"
        "  - estimate_hours when possible\n"
        "  - due and relative_timing when possible\n"
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
    by_id = {spec["id"]: spec for spec in _BASELINE_QUESTION_SPECS}

    required_ids = [
        "achievable_time_budget",
        "resources_support",
        "timebound_deadline",
        "constraints_dependencies",
        "risks_unknowns",
        "definition_of_done",
    ]
    picked_specs: list[_BaselineQuestionSpec] = []
    used_ids: set[str] = set()

    # Ensure the streamlined baseline covers capacity, feasibility, timing, and done criteria.
    for spec_id in required_ids:
        selected = by_id.get(spec_id)
        if selected is None or selected["id"] in used_ids:
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
            guide=spec["guide"],
            research_basis=spec["research_basis"],
        )
        for spec in picked_specs[:bounded_max]
    ]
