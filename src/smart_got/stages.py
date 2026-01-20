from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .ops import Budget, adapt_stage4, construct_stage1, evaluate_and_plan_stage3, expand_stage2, refine_after_baseline
from .schema import BaselineEntry, Graph, Node


class StageError(RuntimeError):
    pass


def approve_gate(graph: Graph, stage: int, note: str = "") -> None:
    if stage == 1:
        _auto_accept_stage1_nodes(graph)
    g = graph.upsert_gate(stage)
    g.status = "approved"
    g.approved_at = g.approved_at or datetime.now(timezone.utc)
    g.note = note


def require_gate(graph: Graph, stage: int) -> None:
    g = graph.gate(stage)
    if g is None or g.status != "approved":
        raise StageError(f"Stage {stage} gate is not approved. Run: smartgot approve --stage {stage} ...")


def run_stage1(intent: str, rationale: Optional[str] = None) -> Graph:
    return construct_stage1(intent=intent, rationale=rationale)


def run_stage2(graph: Graph, budget: Budget = Budget()) -> Graph:
    require_gate(graph, 1)
    _require_stage1_acceptance(graph)
    return expand_stage2(graph, budget=budget)


def run_stage3(graph: Graph, budget: Budget = Budget()) -> Graph:
    require_gate(graph, 2)
    _require_some_baseline(graph)
    if not graph.meta.get("refined_with_baseline"):
        refine_after_baseline(graph)
    return evaluate_and_plan_stage3(graph, budget=budget)


def run_stage4(
    graph: Graph,
    progress: float,
    friction: str = "",
    completed_goal_ids: list[str] | None = None,
    missed_goal_ids: list[str] | None = None,
    reflection: str = "",
    plan_add_steps: list[str] | None = None,
    plan_remove_steps: list[str] | None = None,
    plan_add_if_then: list[str] | None = None,
    time_bound_weeks: int | None = None,
) -> Graph:
    require_gate(graph, 3)
    return adapt_stage4(
        graph,
        progress=progress,
        friction=friction,
        completed_goal_ids=completed_goal_ids,
        missed_goal_ids=missed_goal_ids,
        reflection=reflection,
        plan_add_steps=plan_add_steps,
        plan_remove_steps=plan_remove_steps,
        plan_add_if_then=plan_add_if_then,
        time_bound_weeks=time_bound_weeks,
    )


def _require_some_baseline(graph: Graph) -> None:
    goal = graph.root_goal()
    if goal is None:
        raise StageError("goal.v1 not found. Did you run stage1?")
    baselines = list(goal.data.baseline.values())
    if not baselines:
        raise StageError("No baseline entries found. Did you run stage2?")
    answered = [b for b in baselines if b.value not in (None, "")]
    if len(answered) == 0:
        raise StageError("Baseline values are all empty. Fill goal.v1.data.baseline.*.value fields before stage3.")


def _auto_accept_stage1_nodes(graph: Graph) -> None:
    node = graph.nodes.get("goal.v1")
    if node and node.status != "rejected":
        node.status = "accepted"
        node.touch()


def _require_stage1_acceptance(graph: Graph) -> None:
    node = graph.nodes.get("goal.v1")
    if node is None:
        raise StageError("Stage 2 requires goal.v1 to exist.")
    if node.status != "accepted":
        raise StageError(
            f"Stage 2 requires goal.v1 to be accepted (current: {node.status}). "
            "Approve stage 1 or edit its status."
        )


def answer_value(graph: Graph, node_id: str, raw_value: str) -> None:
    if node_id.startswith("baseline."):
        goal = graph.root_goal()
        if goal is None:
            raise StageError("goal.v1 not found. Did you run stage1?")
        key = node_id[len("baseline."):]
        if not key:
            raise StageError("Baseline id must be baseline.<key>.")
        entry = goal.data.baseline.get(key)
        if entry is None:
            entry = goal.data.baseline.setdefault(key, BaselineEntry())
        entry.value = _parse_value(raw_value)
        goal.touch()
        return
    raise StageError("Only baseline.* ids are supported. Edit the JSON for other fields.")


def choose_plan(graph: Graph, plan_id: str) -> None:
    goal = graph.root_goal()
    if goal is None:
        raise StageError("goal.v1 not found. Run stage1 first.")
    plans = [n for n in graph.nodes.values() if _is_plan_goal(n)]
    if not plans:
        raise StageError("No plan goal nodes found. Run stage3 first.")
    chosen = graph.nodes.get(plan_id)
    if chosen is None or not _is_plan_goal(chosen):
        available = ", ".join(sorted(p.id for p in plans))
        raise StageError(f"Plan {plan_id} not found. Available: {available}")
    if plan_id not in goal.data.decision.plan_options:
        goal.data.decision.plan_options = [p.id for p in plans]
    goal.data.decision.chosen_plan_id = plan_id
    goal.touch()
    for plan in plans:
        plan.status = "accepted" if plan.id == plan_id else "proposed"
        plan.touch()


def _parse_value(raw_value: str) -> int | float | str:
    text = raw_value.strip()
    if text == "":
        return ""
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _is_plan_goal(node: Node) -> bool:
    if node.type != "goal":
        return False
    plan = node.data.plan
    return bool(plan.steps or plan.if_then or plan.time_bound_weeks is not None or plan.assumptions or plan.milestones)
