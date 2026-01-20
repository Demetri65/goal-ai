from __future__ import annotations

import textwrap

from .schema import Graph, Node


def render_summary(graph: Graph) -> str:
    lines: list[str] = []
    lines.append("SMART-GoT graph summary")
    lines.append("=" * 24)

    goal = graph.root_goal()
    if goal:
        lines.append(f"Goal ({goal.status}): {goal.text}")
        metric = goal.data.smr.metric
        lines.append(
            f"Metric: {metric.name or '(unnamed)'} target={metric.target_value} unit={metric.unit} method={metric.method}"
        )

        baselines = goal.data.baseline
        lines.append("")
        if baselines:
            answered = sum(1 for b in baselines.values() if b.value not in (None, ""))
            lines.append(f"Baseline: answered {answered}/{len(baselines)}")
            for key in ("time_per_week_hours", "hard_deadline", "key_constraints"):
                entry = baselines.get(key)
                if entry is None:
                    continue
                unit = entry.unit or ""
                lines.append(f"  - {key}: value={entry.value!r} {unit}".rstrip())
        else:
            lines.append("Baseline: none")

        chosen_id = goal.data.decision.chosen_plan_id
        lines.append("")
        lines.append(f"Chosen plan: {chosen_id or '(none)'}")
        if chosen_id and chosen_id in graph.nodes:
            plan_node = graph.nodes[chosen_id]
            plan = plan_node.data.plan
            lines.append(
                f"  - {plan_node.id} ({plan_node.status}) weeks={plan.time_bound_weeks} steps={len(plan.steps)}"
            )
            if plan_node.data.eval.score is not None:
                lines.append(f"  - score={plan_node.data.eval.score:.2f}")
            if plan_node.data.eval.reasons:
                lines.append("  - reasons: " + "; ".join(plan_node.data.eval.reasons))

    lines.append("")
    lines.append("Goal tree:")
    root_id = graph.root_goal_id()
    if root_id in graph.nodes:
        children = _children_map(graph)
        _render_tree(lines, graph, root_id, children, "", set())
    else:
        lines.append("  (no root goal)")

    if graph.gates:
        lines.append("")
        lines.append("Stage gates:")
        for g in sorted(graph.gates, key=lambda x: x.stage):
            lines.append(f"  - Stage {g.stage}: {g.status} note={g.note!r}")

    return "\n".join(lines)


def render_bash_tree(graph: Graph) -> str:
    root_id = graph.root_goal_id()
    if root_id not in graph.nodes:
        return "(no root goal)"
    children = _children_map(graph)
    lines: list[str] = []
    _render_bash(lines, graph, root_id, "", "", children, set())
    return "\n".join(lines)


def _children_map(graph: Graph) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.type != "subgoal_of":
            continue
        out.setdefault(edge.dst, []).append(edge.src)
    for parent in out:
        out[parent] = sorted(out[parent])
    return out


def _render_bash(
    lines: list[str],
    graph: Graph,
    node_id: str,
    line_prefix: str,
    child_prefix: str,
    children: dict[str, list[str]],
    seen: set[str],
) -> None:
    node = graph.nodes.get(node_id)
    if node is None:
        return
    box = _box_lines(node)
    lines.append(f"{line_prefix}{box[0]}")
    for line in box[1:]:
        lines.append(f"{child_prefix}{line}")
    if node_id in seen:
        return
    seen.add(node_id)
    kids = children.get(node_id, [])
    for idx, child_id in enumerate(kids):
        is_last = idx == len(kids) - 1
        branch = "`-- " if is_last else "|-- "
        next_line_prefix = child_prefix + branch
        next_child_prefix = child_prefix + ("    " if is_last else "|   ")
        _render_bash(lines, graph, child_id, next_line_prefix, next_child_prefix, children, seen)


def _box_lines(node: Node) -> list[str]:
    content: list[str] = []
    content.extend(_wrap_line(f"{node.id} ({node.status})"))
    if node.text:
        content.extend(_wrap_line(node.text))
    tasks = _node_tasks(node)
    if tasks:
        content.append("tasks:")
        for task in tasks:
            content.extend(_wrap_line(f"- {task}"))
    else:
        content.append("tasks: (none)")
    width = max(len(line) for line in content) if content else 0
    top = "+" + "-" * (width + 2) + "+"
    lines = [top]
    for line in content:
        lines.append(f"| {line.ljust(width)} |")
    lines.append(top)
    return lines


def _wrap_line(text: str, limit: int = 64) -> list[str]:
    lines = textwrap.wrap(text, width=limit) if text else []
    return lines or [""]


def _node_tasks(node: Node) -> list[str]:
    if node.data.tasks:
        return list(node.data.tasks)
    plan = node.data.plan
    if plan.steps:
        return list(plan.steps)
    return []


def _render_tree(
    lines: list[str],
    graph: Graph,
    node_id: str,
    children: dict[str, list[str]],
    prefix: str,
    seen: set[str],
) -> None:
    node = graph.nodes.get(node_id)
    if node is None:
        return
    if node_id in seen:
        lines.append(f"{prefix}- {node.id} ({node.status}) [see above]")
        return
    seen.add(node_id)
    suffix = " [plan]" if _is_plan_goal(node) else ""
    score = node.data.eval.score
    score_text = f" score={score:.2f}" if score is not None else ""
    lines.append(f"{prefix}- {node.id} ({node.status}){suffix}{score_text}")
    if node.data.eval.reasons:
        lines.append(f"{prefix}  reasons: " + "; ".join(node.data.eval.reasons))
    for child_id in children.get(node_id, []):
        _render_tree(lines, graph, child_id, children, prefix + "  ", seen)


def _is_plan_goal(node: Node) -> bool:
    plan = node.data.plan
    return bool(plan.steps or plan.if_then or plan.time_bound_weeks is not None or plan.assumptions or plan.milestones)
