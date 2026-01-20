from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from .llm import generate_json, llm_enabled
from .rubrics import score_plan
from .schema import (
    BaselineEntry,
    ConstraintEntry,
    Edge,
    GoalNodeData,
    Graph,
    Node,
    PlanData,
    RevisionEvent,
    SmrData,
    SmrMetric,
    utcnow,
)


@dataclass(frozen=True)
class Budget:
    # Kept for future "adaptive expansion" work.
    # Prototype uses only small, fixed expansions.
    max_nodes: int = 50
    max_plans: int = 2


STAGE1_SCHEMA = {
    "type": "object",
    "properties": {
        "goal_text": {"type": "string"},
        "rationale": {"type": "string"},
        "metric": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "unit": {"type": "string"},
                "method": {"type": "string"},
                "target_value": {"type": ["number", "null"]},
            },
            "required": ["name", "unit", "method", "target_value"],
            "additionalProperties": False,
        },
        "forcing_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["goal_text", "rationale", "metric", "forcing_questions"],
    "additionalProperties": False,
}

STAGE2_BASELINE_SCHEMA = {
    "type": "object",
    "properties": {
        "time_per_week_hours": {"type": "string"},
        "hard_deadline": {"type": "string"},
        "key_constraints": {"type": "string"},
        "extra": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 0,
            "maxItems": 6,
        },
    },
    "required": ["time_per_week_hours", "hard_deadline", "key_constraints", "extra"],
    "additionalProperties": False,
}

STAGE3_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "time_bound_weeks": {"type": "integer", "minimum": 1, "maximum": 104},
        "steps": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 10},
        "if_then": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["time_bound_weeks", "steps", "if_then", "assumptions"],
    "additionalProperties": False,
}

STAGE1_SUBGOAL_SCHEMA = {
    "type": "object",
    "properties": {
        "subgoals": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 5,
            "maxItems": 9,
        }
    },
    "required": ["subgoals"],
    "additionalProperties": False,
}

STAGE2_REFINEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "goal_text": {"type": "string"},
        "subgoals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "tasks": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 6},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "text", "tasks", "depends_on"],
                "additionalProperties": False,
            },
            "minItems": 5,
            "maxItems": 9,
        },
    },
    "required": ["goal_text", "subgoals"],
    "additionalProperties": False,
}

INITIAL_SUBGOAL_MIN = 5
INITIAL_SUBGOAL_MAX = 9

DEFAULT_INITIAL_SUBGOALS = [
    "Clarify success criteria and scope",
    "Define what counts as measurable progress",
    "Identify key milestones for the goal",
    "Gather the resources needed to start",
    "Surface risks and constraints early",
    "Draft an initial work cadence",
    "Set a lightweight review routine",
]

def construct_stage1(intent: str, rationale: Optional[str] = None) -> Graph:
    g = Graph(meta={"intent": intent, "rationale": rationale or "", "root_goal_id": "goal.v1"})
    goal_text = _draft_goal_text(intent)
    goal_rationale = rationale or ""
    metric_data = {"name": "primary_metric", "unit": "", "method": "", "target_value": None}
    forcing_questions = [
        "What exactly will you do (behavior/outcome) — in concrete terms?",
        "How will you measure progress? (metric, unit, method)",
        "Why is this goal relevant right now?",
    ]
    if llm_enabled():
        stage1 = generate_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are SMART-GoT Stage 1. Draft a concise goal statement, a brief rationale, "
                        "a primary metric, and forcing questions. Do not invent numeric targets, deadlines, "
                        "or scope details unless explicitly in the user's intent. Keep the goal as a single sentence "
                        "without enumerating subgoals or logistics; those belong in later stages. "
                        "If the metric target is unknown, set target_value to null."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Intent: {intent}\nRationale: {rationale or ''}",
                },
            ],
            schema=STAGE1_SCHEMA,
            name="stage1_output",
        )
        goal_text = stage1["goal_text"]
        goal_rationale = stage1["rationale"]
        metric_data = stage1["metric"]
        forcing_questions = stage1["forcing_questions"]
        g.meta["rationale"] = goal_rationale

    smr = SmrData(
        rationale=goal_rationale,
        metric=SmrMetric(**metric_data),
        forcing_questions=forcing_questions,
    )
    goal = Node(
        id="goal.v1",
        type="goal",
        stage=1,
        status="draft",
        text=goal_text,
        provenance="llm",
        confidence=0.4,
        data=GoalNodeData(smr=smr),
    )
    g.add_node(goal)
    _add_initial_subgoals(g, goal)

    g.upsert_gate(1).status = "pending"
    return g


def expand_stage2(graph: Graph, budget: Budget = Budget()) -> Graph:
    goal = _require_root_goal(graph)

    if not llm_enabled():
        raise RuntimeError("Stage 2 requires LLM baseline questions. Set SMARTGOT_LLM_MODE=openai (or mock for tests).")

    baseline_questions = {}
    extra_questions: list[str] = []
    baseline_questions, extra_questions = _llm_baseline_questions(goal)

    _ensure_baseline_slot(
        goal,
        "time_per_week_hours",
        _question_text(baseline_questions, "time_per_week_hours"),
        unit="hours/week",
    )
    _ensure_baseline_slot(
        goal,
        "hard_deadline",
        _question_text(baseline_questions, "hard_deadline"),
        unit="date",
    )
    _ensure_baseline_slot(
        goal,
        "key_constraints",
        _question_text(baseline_questions, "key_constraints"),
        unit="text",
    )

    if extra_questions:
        _add_extra_baselines(goal, extra_questions)

    _ensure_constraint(goal, "constraint.time_budget", "Time budget constraint", source="baseline.time_per_week_hours")
    _ensure_constraint(goal, "constraint.hard_deadline", "Hard deadline constraint", source="baseline.hard_deadline")
    _ensure_constraint(goal, "constraint.key_constraints", "Key constraints", source="baseline.key_constraints")

    _ensure_risks(
        goal,
        [
            "Overcommitment (plan doesn't fit weekly time budget)",
            "Missing baseline data (fantasy deadlines)",
            "Context shifts (schedule changes, priorities change)",
        ],
    )

    _ensure_subgoal(graph, goal, "goal.subgoal.collect_baseline", "Collect baseline answers")
    _ensure_subgoal(graph, goal, "goal.subgoal.identify_constraints", "Identify constraints")
    _ensure_subgoal(graph, goal, "goal.subgoal.find_resources", "Find resources")

    goal.touch()
    graph.upsert_gate(2).status = "pending"
    return graph


def refine_after_baseline(graph: Graph) -> Graph:
    goal = _require_root_goal(graph)
    baseline_lines = _baseline_context_lines(goal)
    if not baseline_lines:
        raise RuntimeError("No baseline values provided. Answer baseline questions before refinement.")

    metric = goal.data.smr.metric
    current_subgoals = _current_subgoal_descriptions(graph)
    user_content = (
        f"Intent: {graph.meta.get('intent','')}\n"
        f"Current goal: {goal.text}\n"
        f"Metric: name={metric.name}, unit={metric.unit}, method={metric.method}, target={metric.target_value}\n"
        f"Current subgoals:\n{current_subgoals}\n"
        "Baseline answers:\n"
        + "\n".join(baseline_lines)
    )
    payload = generate_json(
        [
            {
                "role": "system",
                "content": (
                    "You are SMART-GoT Stage 2 refinement. Rewrite the goal statement using only information "
                    "supported by the intent and baseline answers. Do not invent new numeric targets or deadlines. "
                    "Also provide 5-9 refined subgoals aligned with the updated goal.\n"
                    "- Reuse existing subgoal ids when possible.\n"
                    "- For new subgoals, use ids like \"new.1\", \"new.2\", etc.\n"
                    "- Provide 1-6 concrete tasks for every subgoal.\n"
                    "- Use depends_on to express subgoal dependencies by id.\n"
                    "- Do not include the root goal id in subgoals."
                ),
            },
            {"role": "user", "content": user_content},
        ],
        schema=STAGE2_REFINEMENT_SCHEMA,
        name="stage2_refine",
    )
    goal_text = str(payload.get("goal_text", "")).strip()
    if not goal_text:
        raise RuntimeError("LLM returned empty refined goal text.")
    goal.text = goal_text
    goal.touch()

    subgoals = payload.get("subgoals", [])
    if not isinstance(subgoals, list) or not subgoals:
        raise RuntimeError("LLM returned no subgoals for refinement.")
    _apply_refined_subgoals(graph, goal, subgoals)
    graph.meta["refined_with_baseline"] = True
    graph.revisions.append(RevisionEvent(kind="refine_after_baseline", detail={"goal_id": goal.id}))
    return graph


def evaluate_and_plan_stage3(graph: Graph, budget: Budget = Budget()) -> Graph:
    goal = _require_root_goal(graph)
    # Create two lightweight plan options (conservative vs aggressive)
    plans = []
    for i in range(min(budget.max_plans, 2)):
        pid = f"goal.plan.option{i+1}"
        if pid in graph.nodes:
            _ensure_subgoal_edge(graph, pid, goal.id)
            plans.append(graph.nodes[pid])
            continue
        flavor = "conservative" if i == 0 else "aggressive"
        plan_data = _llm_plan(graph, flavor=flavor) if llm_enabled() else _draft_plan(graph, flavor=flavor)
        plan_payload = PlanData(**plan_data)
        plan = Node(
            id=pid,
            type="goal",
            stage=3,
            status="proposed",
            text=f"Plan option {i+1}",
            provenance="llm",
            confidence=0.5,
            data=_goal_plan_data(plan_payload),
        )
        graph.add_node(plan)
        _ensure_subgoal_edge(graph, plan.id, goal.id)
        plans.append(plan)

    # Evaluate plans
    for p in plans:
        ev = score_plan(p, graph)
        ev.last_updated = utcnow().isoformat()
        p.data.eval = ev
        p.touch()
        graph.revisions.append(
            RevisionEvent(
                kind="score_plan",
                detail={"id": p.id, "score": p.data.eval.score},
            )
        )

    # Stage 3 evaluates options but does not choose a plan.
    goal.data.decision.plan_options = [p.id for p in plans]
    if goal.data.decision.chosen_plan_id not in goal.data.decision.plan_options:
        goal.data.decision.chosen_plan_id = None
    goal.touch()

    graph.upsert_gate(3).status = "pending"
    return graph


def adapt_stage4(
    graph: Graph,
    progress: float,
    friction: str = "",
    completed_goal_ids: Optional[list[str]] = None,
    missed_goal_ids: Optional[list[str]] = None,
    reflection: str = "",
    plan_add_steps: Optional[list[str]] = None,
    plan_remove_steps: Optional[list[str]] = None,
    plan_add_if_then: Optional[list[str]] = None,
    time_bound_weeks: Optional[int] = None,
) -> Graph:
    # Toy adaptation: if progress is low, soften plan by extending time bound or reducing steps.
    completed = _normalize_id_list(completed_goal_ids)
    missed = _normalize_id_list(missed_goal_ids)
    _apply_checkin_statuses(graph, completed, missed)

    chosen = _chosen_plan(graph)
    graph.revisions.append(
        RevisionEvent(
            kind="checkin",
            detail={
                "progress": progress,
                "friction": friction,
                "completed_goals": completed,
                "missed_goals": missed,
                "reflection": reflection,
            },
        )
    )
    if chosen is None:
        return graph

    chosen = graph.nodes[chosen.id]  # ensure we have the stored instance
    _apply_plan_updates(
        chosen,
        plan_add_steps=plan_add_steps,
        plan_remove_steps=plan_remove_steps,
        plan_add_if_then=plan_add_if_then,
        time_bound_weeks=time_bound_weeks,
    )

    tb = chosen.data.plan.time_bound_weeks
    if progress < 0.5 and time_bound_weeks is None:
        if isinstance(tb, int) and tb > 0:
            chosen.data.plan.time_bound_weeks = tb + 2

    _append_checkin_note(chosen, progress, friction, reflection, completed, missed)
    chosen.touch()

    _rescore_plans(graph)

    graph.upsert_gate(4).status = "pending"
    return graph


# -------------------------
# Helpers
# -------------------------

def _draft_goal_text(intent: str) -> str:
    # Keep it simple: user is expected to edit.
    intent = intent.strip().rstrip(".")
    return f"I will {intent}."


def _require_root_goal(graph: Graph) -> Node:
    goal = graph.root_goal()
    if goal is None:
        raise RuntimeError("goal.v1 not found in graph.")
    return goal


def _normalize_id_list(values: Optional[list[str]]) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    for value in values:
        if not value:
            continue
        for item in value.split(","):
            item = item.strip()
            if item and item not in out:
                out.append(item)
    return out


def _apply_checkin_statuses(graph: Graph, completed: list[str], missed: list[str]) -> None:
    overlap = set(completed) & set(missed)
    if overlap:
        raise RuntimeError(f"Check-in ids cannot be both completed and missed: {', '.join(sorted(overlap))}")

    for node_id in completed:
        node = graph.nodes.get(node_id)
        if node is None or node.type != "goal":
            raise RuntimeError(f"Completed goal id not found: {node_id}")
        node.status = "accepted"
        node.touch()

    for node_id in missed:
        node = graph.nodes.get(node_id)
        if node is None or node.type != "goal":
            raise RuntimeError(f"Missed goal id not found: {node_id}")
        if node.status != "deprecated":
            node.status = "rejected"
            node.touch()


def _apply_plan_updates(
    plan_node: Node,
    plan_add_steps: Optional[list[str]] = None,
    plan_remove_steps: Optional[list[str]] = None,
    plan_add_if_then: Optional[list[str]] = None,
    time_bound_weeks: Optional[int] = None,
) -> None:
    plan = plan_node.data.plan
    if time_bound_weeks is not None:
        plan.time_bound_weeks = time_bound_weeks

    if plan_add_steps:
        for step in plan_add_steps:
            if step and step not in plan.steps:
                plan.steps.append(step)

    if plan_remove_steps:
        remove = {s for s in plan_remove_steps if s}
        if remove:
            plan.steps = [s for s in plan.steps if s not in remove]

    if plan_add_if_then:
        for item in plan_add_if_then:
            if item and item not in plan.if_then:
                plan.if_then.append(item)


def _append_checkin_note(
    plan_node: Node,
    progress: float,
    friction: str,
    reflection: str,
    completed: list[str],
    missed: list[str],
) -> None:
    parts: list[str] = [f"progress={progress:.2f}"]
    if completed:
        parts.append(f"completed={', '.join(completed)}")
    if missed:
        parts.append(f"missed={', '.join(missed)}")
    if reflection:
        parts.append(f"reflection={reflection}")
    if friction:
        parts.append(f"friction={friction}")
    note = "Check-in: " + " | ".join(parts)
    if plan_node.data.plan.notes is None:
        plan_node.data.plan.notes = []
    plan_node.data.plan.notes.append(note)


def _ensure_baseline_slot(goal: Node, key: str, question: str, unit: str = "", source: str | None = None) -> None:
    entry = goal.data.baseline.get(key)
    if entry is None:
        goal.data.baseline[key] = BaselineEntry(question=question, unit=unit, source=source)
        return
    if question and not entry.question:
        entry.question = question
    if unit and not entry.unit:
        entry.unit = unit
    if source and entry.source is None:
        entry.source = source


def _ensure_constraint(goal: Node, constraint_id: str, text: str, source: str | None = None) -> None:
    for c in goal.data.constraints:
        if c.id == constraint_id:
            if text and not c.text:
                c.text = text
            if source and c.source is None:
                c.source = source
            return
    goal.data.constraints.append(ConstraintEntry(id=constraint_id, text=text, source=source))


def _ensure_risks(goal: Node, risks: list[str]) -> None:
    for risk in risks:
        if risk not in goal.data.risks:
            goal.data.risks.append(risk)


def _ensure_subgoal(graph: Graph, goal: Node, subgoal_id: str, text: str, stage: int = 2) -> None:
    if subgoal_id not in graph.nodes:
        graph.add_node(
            Node(
                id=subgoal_id,
                type="goal",
                stage=stage,
                status="proposed",
                text=text,
                provenance="llm",
                confidence=0.5,
                data=GoalNodeData(),
            )
        )
    else:
        node = graph.nodes[subgoal_id]
        if node.text == "" and text:
            node.text = text
    _ensure_subgoal_edge(graph, subgoal_id, goal.id)


def _ensure_subgoal_edge(graph: Graph, src: str, dst: str) -> None:
    for edge in graph.edges:
        if edge.src == src and edge.dst == dst and edge.type == "subgoal_of":
            return
    graph.add_edge(Edge(src=src, dst=dst, type="subgoal_of"))


def _goal_plan_data(plan: PlanData) -> GoalNodeData:
    data = GoalNodeData()
    data.plan = plan
    return data


def _question_text(baseline_questions: dict[str, str], key: str) -> str:
    candidate = baseline_questions.get(key, "").strip()
    if not candidate:
        raise RuntimeError(f"LLM returned empty baseline question for {key}.")
    return candidate


def _llm_baseline_questions(goal: Node) -> tuple[dict[str, str], list[str]]:
    metric = goal.data.smr.metric
    user_content = (
        f"Goal: {goal.text}\n"
        f"Metric: name={metric.name}, unit={metric.unit}, method={metric.method}, target={metric.target_value}"
    )
    payload = generate_json(
        [
            {
                "role": "system",
                "content": (
                    "You are SMART-GoT Stage 2. Generate baseline questions tailored to the goal. "
                    "Provide concrete question text for time budget, deadline, and constraints, plus 0-6 extras."
                ),
            },
            {"role": "user", "content": user_content},
        ],
        schema=STAGE2_BASELINE_SCHEMA,
        name="stage2_baselines",
    )
    extras = payload.get("extra", [])
    extra_questions = [q.strip() for q in extras if isinstance(q, str) and q.strip()]
    def _pick(key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str):
            return ""
        return value.strip()
    baseline_questions = {
        "time_per_week_hours": _pick("time_per_week_hours"),
        "hard_deadline": _pick("hard_deadline"),
        "key_constraints": _pick("key_constraints"),
    }
    missing = [k for k, v in baseline_questions.items() if not v]
    if missing:
        detail = ", ".join(missing)
        debug = os.getenv("SMARTGOT_LLM_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
        if debug:
            raise RuntimeError(
                f"LLM returned empty baseline questions for: {detail}. Payload: {json.dumps(payload, indent=2)}"
            )
        raise RuntimeError(
            f"LLM returned empty baseline questions for: {detail}. Set SMARTGOT_LLM_DEBUG=1 to inspect the payload."
        )
    return baseline_questions, extra_questions


def _add_initial_subgoals(graph: Graph, goal: Node) -> None:
    subgoals = _initial_subgoal_texts(goal)
    _apply_initial_subgoals(graph, goal, subgoals)


def _initial_subgoal_texts(goal: Node) -> list[str]:
    if llm_enabled():
        metric = goal.data.smr.metric
        user_content = (
            f"Goal: {goal.text}\n"
            f"Metric: name={metric.name}, unit={metric.unit}, method={metric.method}, target={metric.target_value}"
        )
        payload = generate_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are SMART-GoT Stage 1. Decompose the main goal into 5-9 concrete subgoals. "
                        "Each subgoal should be an actionable phrase. Do not introduce new numeric targets "
                        "or deadlines unless they are already in the goal."
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            schema=STAGE1_SUBGOAL_SCHEMA,
            name="stage1_subgoals",
        )
        items = payload.get("subgoals", [])
        subgoals = [s.strip() for s in items if isinstance(s, str) and s.strip()]
        if subgoals:
            return _normalize_subgoals(subgoals)
    return _normalize_subgoals(DEFAULT_INITIAL_SUBGOALS)


def _slugify(text: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:40]


def _unique_subgoal_id(graph: Graph) -> str:
    idx = 1
    while f"goal.subgoal.init.{idx}" in graph.nodes:
        idx += 1
    return f"goal.subgoal.init.{idx}"


def _apply_initial_subgoals(graph: Graph, goal: Node, subgoals: list[str]) -> None:
    desired_ids: list[str] = []
    for text in subgoals:
        slug = _slugify(text)
        subgoal_id = f"goal.subgoal.init.{slug}" if slug else None
        if subgoal_id and subgoal_id in graph.nodes:
            node = graph.nodes[subgoal_id]
            node.text = text
            node.status = "proposed"
            node.touch()
        else:
            if subgoal_id is None or subgoal_id in graph.nodes:
                subgoal_id = _unique_subgoal_id(graph)
            _ensure_subgoal(graph, goal, subgoal_id, text, stage=1)
        desired_ids.append(subgoal_id)

    existing_ids = [nid for nid in graph.nodes if nid.startswith("goal.subgoal.init.")]
    deprecated = [nid for nid in existing_ids if nid not in desired_ids]
    for nid in deprecated:
        node = graph.nodes[nid]
        node.status = "deprecated"
        node.touch()
    _prune_subgoal_edges(graph, goal.id, deprecated)


def _prune_subgoal_edges(graph: Graph, goal_id: str, subgoal_ids: list[str]) -> None:
    if not subgoal_ids:
        return
    graph.edges = [
        edge
        for edge in graph.edges
        if not (edge.type == "subgoal_of" and edge.dst == goal_id and edge.src in subgoal_ids)
    ]


def _apply_refined_subgoals(graph: Graph, goal: Node, subgoals: list[dict[str, Any]]) -> None:
    existing_ids = {nid for nid in graph.nodes if nid.startswith("goal.subgoal.init.")}
    id_map: dict[str, str] = {}
    desired_ids: list[str] = []

    for item in subgoals:
        if not isinstance(item, dict):
            raise RuntimeError("Refined subgoals payload must be a list of objects.")
        raw_id = str(item.get("id", "")).strip()
        text = str(item.get("text", "")).strip()
        tasks = item.get("tasks", [])
        depends_on = item.get("depends_on", [])
        if not raw_id or not text:
            raise RuntimeError("Each refined subgoal must include id and text.")
        if not isinstance(tasks, list) or not any(isinstance(t, str) and t.strip() for t in tasks):
            raise RuntimeError(f"Refined subgoal {raw_id} is missing tasks.")
        if not isinstance(depends_on, list):
            raise RuntimeError(f"Refined subgoal {raw_id} depends_on must be a list.")

        if raw_id in existing_ids:
            subgoal_id = raw_id
        elif raw_id.startswith("new."):
            slug = _slugify(text)
            subgoal_id = f"goal.subgoal.refined.{slug}" if slug else _unique_subgoal_id(graph)
            if subgoal_id in graph.nodes:
                subgoal_id = _unique_subgoal_id(graph)
        else:
            subgoal_id = raw_id
            if subgoal_id in graph.nodes and subgoal_id not in existing_ids:
                raise RuntimeError(f"Refined subgoal id conflicts with existing node: {subgoal_id}")

        id_map[raw_id] = subgoal_id
        desired_ids.append(subgoal_id)

        if subgoal_id in graph.nodes:
            node = graph.nodes[subgoal_id]
            node.text = text
            node.status = "proposed"
            node.data.tasks = [t.strip() for t in tasks if isinstance(t, str) and t.strip()]
            node.touch()
        else:
            node = Node(
                id=subgoal_id,
                type="goal",
                stage=2,
                status="proposed",
                text=text,
                provenance="llm",
                confidence=0.5,
                data=GoalNodeData(tasks=[t.strip() for t in tasks if isinstance(t, str) and t.strip()]),
            )
            graph.add_node(node)
        _ensure_subgoal_edge(graph, subgoal_id, goal.id)

    deprecated = [nid for nid in existing_ids if nid not in desired_ids]
    for nid in deprecated:
        node = graph.nodes[nid]
        node.status = "deprecated"
        node.touch()
    _prune_subgoal_edges(graph, goal.id, deprecated)
    _apply_subgoal_dependencies(graph, desired_ids, id_map, subgoals)


def _apply_subgoal_dependencies(
    graph: Graph,
    desired_ids: list[str],
    id_map: dict[str, str],
    subgoals: list[dict[str, Any]],
) -> None:
    allowed = set(desired_ids)
    desired_edges: set[tuple[str, str]] = set()
    for item in subgoals:
        raw_id = str(item.get("id", "")).strip()
        src_id = id_map.get(raw_id)
        depends_on = item.get("depends_on", [])
        if not src_id or not isinstance(depends_on, list):
            continue
        for dep in depends_on:
            dep_id = id_map.get(str(dep).strip(), str(dep).strip())
            if dep_id in allowed and dep_id != src_id:
                desired_edges.add((src_id, dep_id))

    graph.edges = [
        edge
        for edge in graph.edges
        if not (edge.type == "subgoal_of" and edge.src in allowed and edge.dst in allowed)
    ]
    for src, dst in sorted(desired_edges):
        _ensure_subgoal_edge(graph, src, dst)


def _normalize_subgoals(subgoals: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in subgoals:
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)

    if len(cleaned) < INITIAL_SUBGOAL_MIN:
        for fallback in DEFAULT_INITIAL_SUBGOALS:
            if fallback not in seen:
                cleaned.append(fallback)
                seen.add(fallback)
            if len(cleaned) >= INITIAL_SUBGOAL_MIN:
                break

    if len(cleaned) > INITIAL_SUBGOAL_MAX:
        cleaned = cleaned[:INITIAL_SUBGOAL_MAX]

    return cleaned


def _baseline_context_lines(goal: Node) -> list[str]:
    lines: list[str] = []
    for key, entry in goal.data.baseline.items():
        if entry.value in (None, ""):
            continue
        unit = f" {entry.unit}".rstrip() if entry.unit else ""
        lines.append(f"- {key}: {entry.value}{unit} (q: {entry.question})")
    return lines


def _current_subgoal_descriptions(graph: Graph) -> str:
    items = []
    for node_id, node in sorted(graph.nodes.items()):
        if node_id.startswith("goal.subgoal.init."):
            items.append(f"- {node_id}: {node.text}")
    return "\n".join(items) if items else "- (none)"


def _add_extra_baselines(goal: Node, questions: list[str]) -> None:
    idx = 1
    for q in questions:
        while f"extra.{idx}" in goal.data.baseline:
            idx += 1
        _ensure_baseline_slot(goal, f"extra.{idx}", q)
        idx += 1


def _llm_plan(graph: Graph, flavor: str) -> dict[str, Any]:
    context = _plan_context(graph)
    user_content = f"Flavor: {flavor}\nContext:\n{json.dumps(context, indent=2)}"
    return generate_json(
        [
            {
                "role": "system",
                "content": "You are SMART-GoT Stage 3. Produce a plan that fits the baseline values and constraints.",
            },
            {"role": "user", "content": user_content},
        ],
        schema=STAGE3_PLAN_SCHEMA,
        name=f"stage3_plan_{flavor}",
    )


def _plan_context(graph: Graph) -> dict[str, Any]:
    goal = _require_root_goal(graph)
    metric = goal.data.smr.metric
    baselines = []
    for key, entry in goal.data.baseline.items():
        baselines.append(
            {
                "id": f"baseline.{key}",
                "question": entry.question,
                "value": entry.value,
                "unit": entry.unit,
            }
        )
    constraints = []
    for c in goal.data.constraints:
        constraints.append({"id": c.id, "text": c.text, "source": c.source})
    metrics = [
        {
            "id": "goal.v1.metric",
            "name": metric.name,
            "unit": metric.unit,
            "method": metric.method,
            "target_value": metric.target_value,
        }
    ]
    return {"goal": goal.text, "metrics": metrics, "baselines": baselines, "constraints": constraints}


def _draft_plan(graph: Graph, flavor: str) -> dict[str, Any]:
    # Uses only baseline time budget if provided.
    hours = _get_baseline_number(graph, "time_per_week_hours")
    time_bound_weeks = 6 if flavor == "conservative" else 4
    if hours is not None and hours < 2:
        time_bound_weeks += 2  # less time => longer horizon

    steps = [
        "Rewrite the goal so it is Specific + Measurable + Relevant (edit goal.v1 + smr.metric).",
        "Collect baseline values for constraints (fill goal.v1.data.baseline.*).",
        "Schedule 2–3 recurring work blocks per week dedicated to this goal.",
        "Do the smallest next action within each work block; log completion.",
        "Weekly review: compare metric vs baseline and adjust next week's plan.",
    ]
    if flavor == "aggressive":
        steps.insert(3, "Add a mid-week checkpoint to catch drift early.")

    if_then = [
        "If it's the start of a work block, then I will do a 2-minute setup and start the smallest step.",
        "If I miss a session, then I will reschedule within 48 hours (no guilt, just logistics).",
    ]
    if flavor == "aggressive":
        if_then.append("If I feel stuck for 10 minutes, then I will reduce scope and finish a tiny version.")

    return {
        "time_bound_weeks": time_bound_weeks,
        "steps": steps,
        "if_then": if_then,
    }


def _get_baseline_number(graph: Graph, key: str) -> Optional[float]:
    goal = graph.root_goal()
    if goal is None:
        return None
    entry = goal.data.baseline.get(key)
    if entry is None:
        return None
    v = entry.value
    try:
        if v in (None, ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _chosen_plan(graph: Graph) -> Optional[Node]:
    goal = graph.root_goal()
    if goal is None:
        return None
    chosen_id = goal.data.decision.chosen_plan_id
    if isinstance(chosen_id, str) and chosen_id in graph.nodes:
        return graph.nodes[chosen_id]
    accepted = [n for n in graph.nodes.values() if n.type == "goal" and n.status == "accepted" and n.data.plan.steps]
    return accepted[0] if accepted else None


def _plan_goals(graph: Graph) -> list[Node]:
    return [n for n in graph.nodes.values() if n.type == "goal" and _is_plan_goal(n)]


def _is_plan_goal(node: Node) -> bool:
    plan = node.data.plan
    return bool(plan.steps or plan.if_then or plan.time_bound_weeks is not None or plan.assumptions or plan.milestones)


def _rescore_plans(graph: Graph) -> None:
    plans = _plan_goals(graph)
    for plan in plans:
        ev = score_plan(plan, graph)
        ev.last_updated = utcnow().isoformat()
        plan.data.eval = ev
        plan.touch()
        graph.revisions.append(RevisionEvent(kind="score_plan", detail={"id": plan.id, "score": ev.score}))
