from __future__ import annotations

from typing import Any

from .schema import (
    BaselineEntry,
    ConstraintEntry,
    DecisionData,
    Edge,
    EvalData,
    GoalNodeData,
    Graph,
    Node,
    PlanData,
    SmrData,
    SmrMetric,
)


def migrate_graph(payload: dict[str, Any]) -> Graph:
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object for graph payload.")

    nodes_in = payload.get("nodes", {})
    if not isinstance(nodes_in, dict):
        raise ValueError("Invalid graph payload: nodes must be an object.")

    meta = dict(payload.get("meta", {}) or {})
    meta["root_goal_id"] = "goal.v1"

    root_raw = nodes_in.get("goal.v1")
    if not isinstance(root_raw, dict):
        raise ValueError("goal.v1 not found in graph payload.")

    root_data_raw = root_raw.get("data", {})
    if not isinstance(root_data_raw, dict):
        root_data_raw = {}

    metric_raw = nodes_in.get("metric.primary", {})
    metric_data = {}
    if isinstance(metric_raw, dict):
        metric_data = metric_raw.get("data", {}) or {}
    if not isinstance(metric_data, dict):
        metric_data = {}

    forcing_questions: list[str] = []
    review_raw = nodes_in.get("review.stage1")
    if isinstance(review_raw, dict):
        review_data = review_raw.get("data", {})
        if isinstance(review_data, dict):
            questions = review_data.get("questions", [])
            if isinstance(questions, list):
                forcing_questions = [q for q in questions if isinstance(q, str)]

    smr = SmrData(
        rationale=str(root_data_raw.get("rationale", meta.get("rationale", "")) or ""),
        metric=SmrMetric(
            name=str(metric_data.get("name", "")),
            unit=str(metric_data.get("unit", "")),
            method=str(metric_data.get("method", "")),
            target_value=metric_data.get("target_value"),
        ),
        forcing_questions=forcing_questions,
    )
    root_data = GoalNodeData(smr=smr)

    for node_id, raw in nodes_in.items():
        if not isinstance(node_id, str) or not node_id.startswith("baseline."):
            continue
        if not isinstance(raw, dict):
            continue
        raw_data = raw.get("data", {})
        if not isinstance(raw_data, dict):
            raw_data = {}
        key = node_id[len("baseline.") :]
        if not key:
            continue
        question = raw_data.get("question") or raw.get("text", "")
        unit = raw_data.get("unit", "")
        value = raw_data.get("value")
        root_data.baseline[key] = BaselineEntry(
            question=str(question or ""),
            unit=str(unit or ""),
            value=value,
        )

    for node_id, raw in nodes_in.items():
        if not isinstance(node_id, str) or not node_id.startswith("constraint."):
            continue
        if not isinstance(raw, dict):
            continue
        raw_data = raw.get("data", {})
        if not isinstance(raw_data, dict):
            raw_data = {}
        root_data.constraints.append(
            ConstraintEntry(
                id=node_id,
                text=str(raw.get("text", "")),
                source=raw_data.get("source"),
            )
        )

    for node_id, raw in nodes_in.items():
        if not isinstance(node_id, str) or not node_id.startswith("risk."):
            continue
        if not isinstance(raw, dict):
            continue
        raw_data = raw.get("data", {})
        if not isinstance(raw_data, dict):
            raw_data = {}
        items = raw_data.get("items", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str) and item not in root_data.risks:
                    root_data.risks.append(item)

    plan_id_map: dict[str, str] = {}
    plan_nodes: list[Node] = []
    for node_id, raw in nodes_in.items():
        if not isinstance(node_id, str) or not node_id.startswith("plan."):
            continue
        if not isinstance(raw, dict):
            continue
        new_id = f"goal.{node_id}"
        plan_id_map[node_id] = new_id
        raw_data = raw.get("data", {})
        if not isinstance(raw_data, dict):
            raw_data = {}

        plan_data = PlanData(
            steps=raw_data.get("steps", []) or [],
            if_then=raw_data.get("if_then", []) or [],
            milestones=raw_data.get("milestones"),
            time_bound_weeks=raw_data.get("time_bound_weeks"),
            assumptions=raw_data.get("assumptions"),
        )
        eval_data = EvalData()
        score = raw.get("score")
        if isinstance(score, (int, float)):
            eval_data.score = float(score)
        raw_eval = raw.get("eval")
        if isinstance(raw_eval, dict):
            if eval_data.score is None and isinstance(raw_eval.get("overall"), (int, float)):
                eval_data.score = float(raw_eval.get("overall"))
            dims = raw_eval.get("dimensions")
            if isinstance(dims, dict):
                eval_data.rubric = dims
                eval_data.reasons = [f"{k}={dims[k]}" for k in sorted(dims.keys())]

        plan_nodes.append(
            Node(
                id=new_id,
                type="goal",
                stage=int(raw.get("stage", 3)),
                status=str(raw.get("status", "proposed")),
                text=str(raw.get("text", new_id)),
                provenance=str(raw.get("provenance", "llm")),
                confidence=raw.get("confidence"),
                data=GoalNodeData(plan=plan_data, eval=eval_data),
                created_at=raw.get("created_at"),
                updated_at=raw.get("updated_at"),
            )
        )

    decision_raw = nodes_in.get("decision.plan_choice", {})
    decision_data = {}
    if isinstance(decision_raw, dict):
        decision_data = decision_raw.get("data", {}) or {}
    if not isinstance(decision_data, dict):
        decision_data = {}
    plan_options = decision_data.get("options", [])
    if not isinstance(plan_options, list):
        plan_options = []
    chosen_plan_id = decision_data.get("chosen_plan_id")
    mapped_options = [plan_id_map.get(pid) for pid in plan_options if isinstance(pid, str)]
    mapped_options = [pid for pid in mapped_options if pid]
    if not mapped_options:
        mapped_options = [p.id for p in plan_nodes]
    mapped_chosen = plan_id_map.get(chosen_plan_id) if isinstance(chosen_plan_id, str) else None

    root_data.decision = DecisionData(plan_options=mapped_options, chosen_plan_id=mapped_chosen)

    root = Node(
        id="goal.v1",
        type="goal",
        stage=int(root_raw.get("stage", 1)),
        status=str(root_raw.get("status", "draft")),
        text=str(root_raw.get("text", "")),
        provenance=str(root_raw.get("provenance", "llm")),
        confidence=root_raw.get("confidence"),
        data=root_data,
        created_at=root_raw.get("created_at"),
        updated_at=root_raw.get("updated_at"),
    )

    nodes_out = {root.id: root}
    for plan in plan_nodes:
        nodes_out[plan.id] = plan

    edges_out = [Edge(src=plan.id, dst=root.id, type="subgoal_of") for plan in plan_nodes]

    return Graph(
        nodes=nodes_out,
        edges=edges_out,
        gates=payload.get("gates", []) or [],
        meta=meta,
    )
