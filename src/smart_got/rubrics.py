from __future__ import annotations

from typing import Any

from .schema import EvalData, Graph, Node


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def baseline_answer_ratio(graph: Graph) -> float:
    goal = graph.root_goal()
    if goal is None:
        return 0.0
    baselines = list(goal.data.baseline.values())
    if not baselines:
        return 0.0
    answered = 0
    for b in baselines:
        if b.value not in (None, ""):
            answered += 1
    return answered / max(1, len(baselines))


def count_if_then(plan: Node) -> int:
    if plan.type != "goal":
        return 0
    items = plan.data.plan.if_then
    return len(items) if isinstance(items, list) else 0


def has_time_bound(plan: Node) -> bool:
    if plan.type != "goal":
        return False
    return plan.data.plan.time_bound_weeks is not None


def score_plan(plan: Node, graph: Graph) -> EvalData:
    # Cheap, auditable heuristics (prototype-level).
    # Combine: baseline coverage + implementation intentions + time-bound presence + step granularity.
    base = baseline_answer_ratio(graph)
    ii = _clamp01(count_if_then(plan) / 3.0)  # 3+ is "good enough" for prototype
    tb = 1.0 if has_time_bound(plan) else 0.0

    steps = plan.data.plan.steps
    step_score = 0.0
    if isinstance(steps, list):
        step_score = _clamp01(len(steps) / 6.0)  # 6+ steps => saturated

    overall = 0.4 * base + 0.25 * ii + 0.2 * tb + 0.15 * step_score

    reasons = [
        f"baseline_coverage={base:.2f}",
        f"implementation_intentions={ii:.2f}",
        f"time_bound_present={tb:.2f}",
        f"step_granularity={step_score:.2f}",
    ]
    rubric: dict[str, Any] = {
        "baseline_coverage": base,
        "implementation_intentions": ii,
        "time_bound_present": tb,
        "step_granularity": step_score,
        "notes": "Prototype heuristic rubric. Replace with explicit LLM-judge rubric later.",
    }
    return EvalData(score=_clamp01(overall), reasons=reasons, rubric=rubric)
