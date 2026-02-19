from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from smart_got.llm import LLMProvider
from smart_got.models import (
    AddSiblingMutation,
    BaselineQA,
    DeleteNodeMutation,
    Graph,
    Mutation,
    Node,
    NodeBaseline,
    NodeStatus,
    SMARTFields,
    UpdateNodeMutation,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_node_id(nodes: dict[str, Node]) -> str:
    idx = 1
    while True:
        candidate = f"n{idx}"
        if candidate not in nodes:
            return candidate
        idx += 1


def _merge_smart_fields(current: SMARTFields, patch: SMARTFields) -> SMARTFields:
    data = current.model_dump()
    patch_data = patch.model_dump()
    for key, value in patch_data.items():
        if value != "":
            data[key] = value
    return SMARTFields(**data)


def init_graph(goal: str) -> Graph:
    root_id = "root"
    root = Node(
        id=root_id,
        title=goal,
        workstream="Goal",
        layer=0,
        smart=SMARTFields(specific=goal),
    )
    now = _now_iso()
    return Graph(
        root_id=root_id,
        nodes={root_id: root},
        created_at=now,
        updated_at=now,
        focus_parent_id=root_id,
        active_layer=1,
    )


def layer_complete(graph: Graph, layer: int) -> bool:
    return all(
        node.status in {NodeStatus.BASELINED, NodeStatus.PLANNED}
        for node in graph.nodes.values()
        if node.layer == layer
    )


def _siblings_for_node(graph: Graph, node: Node) -> list[Node]:
    return [
        sibling
        for sibling in graph.nodes.values()
        if sibling.parent_id == node.parent_id and sibling.id != node.id
    ]


def _smart_lines(label: str, smart: SMARTFields) -> list[str]:
    return [
        f"{label} SMART:",
        f"- Specific: {smart.specific or '-'}",
        f"- Measurable: {smart.measurable or '-'}",
        f"- Achievable: {smart.achievable or '-'}",
        f"- Relevant: {smart.relevant or '-'}",
        f"- TimeBound: {smart.time_bound or '-'}",
    ]


def _baseline_summary_lines(label: str, baseline: NodeBaseline | None) -> list[str]:
    lines = [f"{label} Baseline QA Summary:"]
    if baseline is None:
        lines.append("- None")
        return lines

    qa_entries = [qa for qa in baseline.qa if qa.answer.strip()]
    if qa_entries:
        for qa in qa_entries[:5]:
            lines.append(f"- [{qa.category}] {qa.question} => {qa.answer.strip()}")
        if len(qa_entries) > 5:
            lines.append(f"- ... ({len(qa_entries) - 5} more)")
        return lines

    summary_entries: list[str] = []
    summary_entries.extend(baseline.baseline_notes)
    summary_entries.extend(f"assumption: {item}" for item in baseline.assumptions)
    summary_entries.extend(f"constraint: {item}" for item in baseline.constraints)
    summary_entries.extend(f"unknown: {item}" for item in baseline.unknowns)
    if not summary_entries:
        lines.append("- None")
        return lines
    for item in summary_entries[:5]:
        lines.append(f"- {item}")
    if len(summary_entries) > 5:
        lines.append(f"- ... ({len(summary_entries) - 5} more)")
    return lines


def build_context(graph: Graph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    if node is None:
        raise KeyError(f"Node not found: {node_id}")

    root = graph.nodes[graph.root_id]
    parent = graph.nodes.get(node.parent_id) if node.parent_id else None
    parent_node = parent or root

    lines = [
        f"ROOT_TITLE: {root.title}",
        f"PARENT_TITLE: {parent_node.title}",
        f"CURRENT_TITLE: {node.title}",
        "",
        f"Root Goal: {root.title}",
        *_smart_lines("Root", root.smart),
        *_baseline_summary_lines("Root", root.baseline),
        "",
        f"Parent Node: {parent_node.title}",
        *_smart_lines("Parent", parent_node.smart),
        *_baseline_summary_lines("Parent", parent_node.baseline),
        "",
        f"Current Node: {node.title}",
        *_smart_lines("Current", node.smart),
    ]
    return "\n".join(lines)


def provider_context(graph: Graph, node_id: str) -> str:
    # Backward-compatible alias for existing call sites.
    return build_context(graph, node_id)


def layer_children(graph: Graph, parent_id: str) -> list[str]:
    parent = graph.nodes.get(parent_id)
    if parent is None:
        raise KeyError(f"Node not found: {parent_id}")
    return [child_id for child_id in parent.children_ids if child_id in graph.nodes]


def layer_is_complete(graph: Graph, parent_id: str) -> bool:
    return all(
        graph.nodes[child_id].status == NodeStatus.PLANNED
        for child_id in layer_children(graph, parent_id)
    )


def decompose_node(
    graph: Graph,
    node_id: str,
    provider: LLMProvider,
    target_children: int = 7,
    min_children: int = 5,
    max_children: int = 9,
) -> tuple[Graph, list[str]]:
    new_graph = graph.model_copy(deep=True)
    node = new_graph.nodes.get(node_id)
    if node is None:
        raise KeyError(f"Node not found: {node_id}")
    if node.status == NodeStatus.DRAFT and node.parent_id is not None:
        raise ValueError(f"Node {node.id} is not baselined; baseline it first.")
    if node.children_ids:
        return new_graph, []
    if node.parent_id and not layer_is_complete(new_graph, node.parent_id):
        raise ValueError(
            f"Sibling layer for parent {node.parent_id} is not complete; plan siblings first."
        )

    context = build_context(new_graph, node.id)
    drafts = provider.decompose(node, context, target_children, min_children, max_children)
    drafts = drafts[:max_children]
    new_ids: list[str] = []
    for draft in drafts:
        if not (draft.smart.specific and draft.smart.measurable and draft.smart.relevant):
            raise ValueError("Each workstream must include specific, measurable, and relevant.")
        if not draft.workstream:
            raise ValueError("Each workstream must include a short workstream label.")
        child_id = _next_node_id(new_graph.nodes)
        child = Node(
            id=child_id,
            title=draft.title,
            workstream=draft.workstream,
            layer=node.layer + 1,
            parent_id=node.id,
            smart=draft.smart,
        )
        new_graph.nodes[child_id] = child
        node.children_ids.append(child_id)
        new_ids.append(child_id)

    new_graph.updated_at = _now_iso()
    return new_graph, new_ids


def _apply_mutation(graph: Graph, mutation: Mutation) -> None:
    if isinstance(mutation, UpdateNodeMutation):
        node = graph.nodes.get(mutation.node_id)
        if node is None:
            raise KeyError(f"Node not found for update: {mutation.node_id}")
        if mutation.title is not None:
            node.title = mutation.title
        if mutation.smart_patch is not None:
            node.smart = _merge_smart_fields(node.smart, mutation.smart_patch)
        return

    if isinstance(mutation, AddSiblingMutation):
        parent = graph.nodes.get(mutation.parent_id)
        if parent is None:
            raise KeyError(f"Parent node not found for add: {mutation.parent_id}")
        child_id = _next_node_id(graph.nodes)
        graph.nodes[child_id] = Node(
            id=child_id,
            title=mutation.title,
            workstream=mutation.workstream,
            layer=parent.layer + 1,
            parent_id=parent.id,
            smart=mutation.smart,
        )
        parent.children_ids.append(child_id)
        return

    if isinstance(mutation, DeleteNodeMutation):
        node = graph.nodes.get(mutation.node_id)
        if node is None:
            return
        if node.children_ids:
            raise ValueError(f"Cannot delete node with children: {node.id}")
        if node.parent_id:
            parent = graph.nodes.get(node.parent_id)
            if parent:
                parent.children_ids = [
                    child_id for child_id in parent.children_ids if child_id != node.id
                ]
        del graph.nodes[node.id]
        return

    raise TypeError(f"Unsupported mutation type: {type(mutation)!r}")


def _mutation_summary(mutation: Mutation) -> str:
    if isinstance(mutation, UpdateNodeMutation):
        parts = [f"update:{mutation.node_id}"]
        if mutation.title is not None:
            parts.append("title")
        if mutation.smart_patch is not None:
            parts.append("smart")
        return " ".join(parts)
    if isinstance(mutation, AddSiblingMutation):
        return f"add_sibling:{mutation.parent_id}:{mutation.title}"
    if isinstance(mutation, DeleteNodeMutation):
        return f"delete:{mutation.node_id}"
    return f"mutation:{type(mutation).__name__}"


def apply_layer_mutations(
    graph: Graph,
    layer_mutations: list[Mutation],
) -> list[str]:
    summaries: list[str] = []
    for mutation in layer_mutations:
        _apply_mutation(graph, mutation)
        summaries.append(_mutation_summary(mutation))
    return summaries


def baseline_interview(
    graph: Graph,
    node_id: str,
    provider: LLMProvider,
    ask_fn: Callable[[str], str],
) -> tuple[Graph, list[str]]:
    new_graph = graph.model_copy(deep=True)
    node = new_graph.nodes.get(node_id)
    if node is None:
        raise KeyError(f"Node not found: {node_id}")

    siblings = _siblings_for_node(new_graph, node)
    context = build_context(new_graph, node_id)
    questions = provider.baseline_questions(node, context)
    qa_pairs: list[BaselineQA] = []
    for question in questions:
        answer_raw = ask_fn(question.question)
        answer = answer_raw.strip() if isinstance(answer_raw, str) else str(answer_raw or "")
        qa_pairs.append(
            BaselineQA(
                id=question.id,
                question=question.question,
                answer=answer,
                category=question.category,
            )
        )

    output = provider.baseline_apply(node, siblings, context, qa_pairs)
    node.smart = _merge_smart_fields(node.smart, output.smart_patch)
    baseline = output.baseline.model_copy(deep=True)
    baseline.qa = qa_pairs
    node.baseline = baseline
    node.status = NodeStatus.BASELINED
    applied_mutations = apply_layer_mutations(new_graph, output.layer_mutations)
    new_graph.updated_at = _now_iso()
    return new_graph, applied_mutations


def plan_node(
    graph: Graph,
    node_id: str,
    provider: LLMProvider,
) -> Graph:
    new_graph = graph.model_copy(deep=True)
    node = new_graph.nodes.get(node_id)
    if node is None:
        raise KeyError(f"Node not found: {node_id}")

    context = build_context(new_graph, node_id)
    output = provider.plan(node, context)
    node.smart = _merge_smart_fields(node.smart, output.smart_patch)
    node.plan = output.plan
    node.status = NodeStatus.PLANNED
    new_graph.updated_at = _now_iso()
    return new_graph


def apply_baseline(
    graph: Graph,
    node_id: str,
    qa_pairs: list[BaselineQA],
    smart_patch: Optional[SMARTFields] = None,
    baseline_notes: Optional[list[str]] = None,
    assumptions: Optional[list[str]] = None,
    constraints: Optional[list[str]] = None,
    unknowns: Optional[list[str]] = None,
    baseline: Optional[NodeBaseline] = None,
    layer_mutations: Optional[list[Mutation]] = None,
) -> Graph:
    new_graph = graph.model_copy(deep=True)
    if layer_mutations:
        apply_layer_mutations(new_graph, layer_mutations)

    node = new_graph.nodes.get(node_id)
    if node is None:
        raise KeyError(f"Node not found: {node_id}")
    node.baseline = baseline or NodeBaseline(
        qa=qa_pairs,
        baseline_notes=baseline_notes or [],
        assumptions=assumptions or [],
        constraints=constraints or [],
        unknowns=unknowns or [],
    )
    if smart_patch is not None:
        node.smart = _merge_smart_fields(node.smart, smart_patch)
    node.status = NodeStatus.BASELINED
    new_graph.updated_at = _now_iso()
    return new_graph


def status_summary(graph: Graph) -> dict[str, object]:
    layers: dict[int, int] = {}
    baselined: dict[int, int] = {}
    planned: dict[int, int] = {}
    for node in graph.nodes.values():
        layers[node.layer] = layers.get(node.layer, 0) + 1
        if node.status in {NodeStatus.BASELINED, NodeStatus.PLANNED}:
            baselined[node.layer] = baselined.get(node.layer, 0) + 1
        if node.status == NodeStatus.PLANNED:
            planned[node.layer] = planned.get(node.layer, 0) + 1

    layers_out = {str(layer): count for layer, count in sorted(layers.items())}
    baselined_out = {
        str(layer): baselined.get(layer, 0) for layer in sorted(layers.keys())
    }
    planned_out = {str(layer): planned.get(layer, 0) for layer in sorted(layers.keys())}
    return {
        "total_nodes": len(graph.nodes),
        "layers": layers_out,
        "baselined": baselined_out,
        "planned": planned_out,
        "focus_parent_id": graph.focus_parent_id,
        "active_layer": graph.active_layer,
    }
