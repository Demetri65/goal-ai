from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from smart_got.llm import LLMProvider
from smart_got.models import (
    AddSiblingMutation,
    BaselineQA,
    BaselineQuestion,
    CheckState,
    ChildDraft,
    DeleteNodeMutation,
    Graph,
    LayoutMode,
    Mutation,
    Node,
    NodeBaseline,
    NodePlan,
    NodePosition,
    NodeStatus,
    NodeUI,
    SMARTFields,
    SuggestedConnection,
    Task,
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


def _require_node(graph: Graph, node_id: str) -> Node:
    node = graph.nodes.get(node_id)
    if node is None:
        raise KeyError(f"Node not found: {node_id}")
    return node


def _iter_subtree_ids(graph: Graph, node_id: str) -> list[str]:
    node = _require_node(graph, node_id)
    node_ids = [node_id]
    for child_id in node.children_ids:
        if child_id in graph.nodes:
            node_ids.extend(_iter_subtree_ids(graph, child_id))
    return node_ids


def _path_ids_for_node(graph: Graph, node_id: str) -> list[str]:
    path_ids: list[str] = []
    current_id: Optional[str] = node_id
    visited: set[str] = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        node = _require_node(graph, current_id)
        path_ids.append(node.id)
        current_id = node.parent_id
    return list(reversed(path_ids))


def _node_title_key(title: str) -> str:
    return " ".join(title.casefold().split())


def _display_title(title: str) -> str:
    return title.strip() or "Untitled node"


def _compact_context_text(value: str, max_chars: int = 120) -> str:
    text = " ".join(value.split())
    if len(text) <= max_chars:
        return text
    clipped = text[: max_chars - 3].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return f"{clipped or text[: max_chars - 3]}..."


def _prune_suggested_connections(graph: Graph) -> None:
    graph.suggested_connections = [
        connection
        for connection in graph.suggested_connections
        if connection.source_id in graph.nodes
        and connection.target_id in graph.nodes
        and connection.source_id != connection.target_id
    ]


def _enforce_ordered_suggested_connections(graph: Graph, node_ids: list[str]) -> bool:
    order_by_id = {node_id: index for index, node_id in enumerate(node_ids)}
    next_connections: list[SuggestedConnection] = []
    changed = False

    for connection in graph.suggested_connections:
        source_order = order_by_id.get(connection.source_id)
        target_order = order_by_id.get(connection.target_id)
        if source_order is not None and target_order is not None:
            if source_order < target_order:
                next_connections.append(connection)
            else:
                changed = True
            continue
        next_connections.append(connection)

    graph.suggested_connections = next_connections
    return changed


def _ensure_transitive_suggested_connections(graph: Graph, node_ids: list[str]) -> bool:
    order_by_id = {node_id: index for index, node_id in enumerate(node_ids)}
    connection_keys = {
        (connection.source_id, connection.target_id)
        for connection in graph.suggested_connections
        if connection.source_id in order_by_id
        and connection.target_id in order_by_id
        and order_by_id[connection.source_id] < order_by_id[connection.target_id]
    }
    added = False

    while True:
        transitive_keys = {
            (source_id, target_id)
            for source_id, middle_id in connection_keys
            for other_middle_id, target_id in connection_keys
            if middle_id == other_middle_id
            and order_by_id[source_id] < order_by_id[target_id]
        }
        missing_keys = sorted(transitive_keys - connection_keys)
        if not missing_keys:
            break

        for source_id, target_id in missing_keys:
            source = graph.nodes[source_id]
            target = graph.nodes[target_id]
            connection_keys.add((source_id, target_id))
            graph.suggested_connections.append(
                SuggestedConnection(
                    source_id=source_id,
                    target_id=target_id,
                    label="AI transitive path",
                    rationale=(
                        f"{_display_title(source.title)} indirectly feeds into "
                        f"{_display_title(target.title)} through another workstream."
                    ),
                )
            )
            added = True

    return added


def sync_suggested_connections_for_drafts(
    graph: Graph,
    drafts: list[ChildDraft],
    child_ids: list[str],
) -> Graph:
    new_graph = graph.model_copy(deep=True)
    draft_id_by_title = {
        _node_title_key(draft.title): child_id
        for draft, child_id in zip(drafts, child_ids)
        if child_id in new_graph.nodes
    }
    order_by_child_id = {child_id: index for index, child_id in enumerate(child_ids)}
    connection_keys = {
        (connection.source_id, connection.target_id)
        for connection in new_graph.suggested_connections
    }
    added = False

    for draft, target_id in zip(drafts, child_ids):
        target = new_graph.nodes.get(target_id)
        if target is None:
            continue
        for dependency_title in draft.depends_on:
            source_id = draft_id_by_title.get(_node_title_key(dependency_title))
            source = new_graph.nodes.get(source_id or "")
            if (
                source is None
                or source.id == target.id
                or source.parent_id != target.parent_id
                or order_by_child_id[source.id] >= order_by_child_id[target.id]
            ):
                continue
            key = (source.id, target.id)
            if key in connection_keys:
                continue
            connection_keys.add(key)
            added = True
            new_graph.suggested_connections.append(
                SuggestedConnection(
                    source_id=source.id,
                    target_id=target.id,
                    rationale=(
                        f"{_display_title(source.title)} should feed into "
                        f"{_display_title(target.title)}."
                    ),
                )
            )

    added = _enforce_ordered_suggested_connections(new_graph, child_ids) or added
    added = _ensure_transitive_suggested_connections(new_graph, child_ids) or added
    if added:
        new_graph.updated_at = _now_iso()
    return new_graph


def _reindex_subtree_layers(graph: Graph, node_id: str, layer: int) -> None:
    node = _require_node(graph, node_id)
    node.layer = layer
    for child_id in node.children_ids:
        if child_id in graph.nodes:
            _reindex_subtree_layers(graph, child_id, layer + 1)


def _rebuild_baseline(
    node: Node,
    baseline: Optional[NodeBaseline] = None,
    qa_pairs: Optional[list[BaselineQA]] = None,
    baseline_notes: Optional[list[str]] = None,
    assumptions: Optional[list[str]] = None,
    constraints: Optional[list[str]] = None,
    unknowns: Optional[list[str]] = None,
) -> Optional[NodeBaseline]:
    if baseline is not None:
        return baseline.model_copy(deep=True)

    has_explicit_fields = any(
        value is not None
        for value in (qa_pairs, baseline_notes, assumptions, constraints, unknowns)
    )
    if not has_explicit_fields:
        return node.baseline.model_copy(deep=True) if node.baseline is not None else None

    current = node.baseline.model_copy(deep=True) if node.baseline is not None else NodeBaseline()
    if qa_pairs is not None:
        current.qa = qa_pairs
    if baseline_notes is not None:
        current.baseline_notes = baseline_notes
    if assumptions is not None:
        current.assumptions = assumptions
    if constraints is not None:
        current.constraints = constraints
    if unknowns is not None:
        current.unknowns = unknowns
    return current


def changed_node_ids(before: Graph, after: Graph) -> list[str]:
    changed: list[str] = []
    for node_id in before.nodes.keys() | after.nodes.keys():
        if before.nodes.get(node_id) != after.nodes.get(node_id):
            changed.append(node_id)
    return sorted(changed)


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
    node = _require_node(graph, node_id)

    root = graph.nodes[graph.root_id]
    parent = graph.nodes.get(node.parent_id) if node.parent_id else None
    parent_node = parent or root
    sibling_plan_lines: list[str] = []
    sibling_plan_detail_lines: list[str] = []
    if node.parent_id:
        for sibling_id in parent_node.children_ids:
            if sibling_id == node.id:
                continue
            sibling = graph.nodes.get(sibling_id)
            if sibling is None or sibling.plan is None:
                continue
            sibling_plan_lines.append(
                f"- {sibling.title}: {len(sibling.plan.tasks)} tasks"
            )
            for task in sibling.plan.tasks[:4]:
                timing = task.relative_timing or "unscheduled"
                due = task.due or "no due date"
                description = f": {task.description}" if task.description.strip() else ""
                sibling_plan_detail_lines.append(
                    "- "
                    f"{_compact_context_text(sibling.title, 48)} / "
                    f"{_compact_context_text(task.title, 56)} "
                    f"({timing}; due {due})"
                    f"{_compact_context_text(description, 110)}"
                )

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
    if sibling_plan_lines:
        lines.extend(["", "Sibling plan task counts:", *sibling_plan_lines])
    if sibling_plan_detail_lines:
        lines.extend(
            [
                "",
                "Sibling plan task details (avoid overlapping these tasks):",
                *sibling_plan_detail_lines[:12],
            ]
        )
    return "\n".join(lines)


def provider_context(graph: Graph, node_id: str) -> str:
    # Backward-compatible alias for existing call sites.
    return build_context(graph, node_id)


def layer_children(graph: Graph, parent_id: str) -> list[str]:
    parent = _require_node(graph, parent_id)
    return [child_id for child_id in parent.children_ids if child_id in graph.nodes]


def layer_is_complete(graph: Graph, parent_id: str) -> bool:
    return all(
        graph.nodes[child_id].status == NodeStatus.PLANNED
        for child_id in layer_children(graph, parent_id)
    )


def layer_draft_ids(graph: Graph, parent_id: str) -> list[str]:
    return [
        child_id
        for child_id in layer_children(graph, parent_id)
        if graph.nodes[child_id].status == NodeStatus.DRAFT
    ]


def layer_pending_plan_ids(graph: Graph, parent_id: str) -> list[str]:
    return [
        child_id
        for child_id in layer_children(graph, parent_id)
        if graph.nodes[child_id].status != NodeStatus.PLANNED
    ]


def ensure_layer_children(
    graph: Graph,
    parent_id: str,
    provider: LLMProvider,
    target_children: int = 7,
    min_children: int = 5,
    max_children: int = 9,
) -> tuple[Graph, list[str], bool]:
    child_ids = layer_children(graph, parent_id)
    if child_ids:
        return graph, child_ids, False

    updated_graph, child_ids = decompose_node(
        graph,
        parent_id,
        provider,
        target_children=target_children,
        min_children=min_children,
        max_children=max_children,
    )
    return updated_graph, child_ids, True


def layer_baseline_questions(
    graph: Graph,
    parent_id: str,
    provider: LLMProvider,
) -> list[BaselineQuestion]:
    parent = _require_node(graph, parent_id)
    context = build_context(graph, parent_id)
    return provider.baseline_questions(parent, context)


def collect_baseline_answers(
    questions: list[BaselineQuestion],
    ask_fn: Callable[[str], str],
) -> list[BaselineQA]:
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
    return qa_pairs


def map_layer_answers_to_node(
    layer_answers: list[BaselineQA],
    node_questions: list[BaselineQuestion],
) -> list[BaselineQA]:
    by_id = {item.id: item.answer for item in layer_answers if item.id and item.answer.strip()}
    by_category = {
        item.category: item.answer
        for item in layer_answers
        if item.category and item.answer.strip()
    }
    return [
        BaselineQA(
            id=question.id,
            question=question.question,
            answer=by_id.get(question.id, by_category.get(question.category, "")),
            category=question.category,
        )
        for question in node_questions
    ]


def apply_baseline_answers(
    graph: Graph,
    node_id: str,
    provider: LLMProvider,
    qa_pairs: list[BaselineQA],
) -> tuple[Graph, list[str]]:
    node = _require_node(graph, node_id)
    siblings = _siblings_for_node(graph, node)
    context = build_context(graph, node_id)
    output = provider.baseline_apply(node, siblings, context, qa_pairs)
    mutation_summaries = [_mutation_summary(item) for item in output.layer_mutations]
    updated_graph = apply_baseline(
        graph,
        node_id,
        qa_pairs,
        smart_patch=output.smart_patch,
        baseline=output.baseline,
        layer_mutations=output.layer_mutations,
    )
    return updated_graph, mutation_summaries


def apply_layer_baseline(
    graph: Graph,
    parent_id: str,
    provider: LLMProvider,
    layer_answers: list[BaselineQA],
) -> tuple[Graph, list[str], list[str]]:
    draft_ids = layer_draft_ids(graph, parent_id)
    if not draft_ids:
        return graph, [], []
    if not layer_answers:
        raise ValueError("layer build requires layer_qa_pairs before planning draft nodes")

    updated_graph = graph
    baselined_ids: list[str] = []
    mutation_summaries: list[str] = []
    for child_id in draft_ids:
        node = _require_node(updated_graph, child_id)
        context = build_context(updated_graph, child_id)
        node_questions = provider.baseline_questions(node, context)
        qa_pairs = map_layer_answers_to_node(layer_answers, node_questions)
        updated_graph, summaries = apply_baseline_answers(
            updated_graph,
            child_id,
            provider,
            qa_pairs,
        )
        baselined_ids.append(child_id)
        mutation_summaries.extend(summaries)
    return updated_graph, baselined_ids, mutation_summaries


def plan_layer(
    graph: Graph,
    parent_id: str,
    provider: LLMProvider,
) -> tuple[Graph, list[str]]:
    updated_graph = graph
    planned_ids: list[str] = []

    while not layer_is_complete(updated_graph, parent_id):
        progressed = False
        for child_id in list(layer_children(updated_graph, parent_id)):
            node = updated_graph.nodes.get(child_id)
            if node is None or node.status == NodeStatus.PLANNED:
                continue
            updated_graph = plan_node(updated_graph, child_id, provider)
            planned_ids.append(child_id)
            progressed = True
        if not progressed:
            break

    return updated_graph, planned_ids


def build_layer(
    graph: Graph,
    parent_id: str,
    provider: LLMProvider,
    layer_answers: list[BaselineQA],
    target_children: int = 7,
    min_children: int = 5,
    max_children: int = 9,
) -> tuple[Graph, dict[str, Any]]:
    updated_graph, child_ids, decomposed = ensure_layer_children(
        graph,
        parent_id,
        provider,
        target_children=target_children,
        min_children=min_children,
        max_children=max_children,
    )
    updated_graph, baselined_ids, mutation_summaries = apply_layer_baseline(
        updated_graph,
        parent_id,
        provider,
        layer_answers,
    )
    updated_graph, planned_ids = plan_layer(
        updated_graph,
        parent_id,
        provider,
    )
    return updated_graph, {
        "parent_id": parent_id,
        "child_ids": child_ids,
        "decomposed": decomposed,
        "baselined_ids": baselined_ids,
        "planned_ids": planned_ids,
        "mutation_summaries": mutation_summaries,
    }


def workflow_stage(graph: Graph, selected_node_id: Optional[str] = None) -> str:
    focus_parent_id = graph.focus_parent_id or graph.root_id
    if focus_parent_id not in graph.nodes:
        focus_parent_id = graph.root_id
    child_ids = layer_children(graph, focus_parent_id)
    if not child_ids or any(
        graph.nodes[child_id].status != NodeStatus.PLANNED for child_id in child_ids
    ):
        return "drafting"

    selected = graph.nodes.get(selected_node_id) if selected_node_id else None
    if (
        selected is not None
        and selected.parent_id == focus_parent_id
        and selected.status == NodeStatus.PLANNED
    ):
        return "planning"
    return "selecting"


def workflow_actions(graph: Graph, selected_node_id: Optional[str] = None) -> list[str]:
    stage = workflow_stage(graph, selected_node_id)
    if stage == "drafting":
        return ["build_layer"]

    actions = ["select_node", "refresh_graph"]
    focus_parent = graph.nodes.get(graph.focus_parent_id or graph.root_id)
    if focus_parent and focus_parent.parent_id:
        actions.append("focus_parent_layer")

    selected = graph.nodes.get(selected_node_id) if selected_node_id else None
    if selected is not None and selected.status == NodeStatus.PLANNED:
        actions.extend(["show_planning", "toggle_task", "replace_plan", "generate_plan"])
        if selected.children_ids or selected.status == NodeStatus.PLANNED:
            actions.append("focus_child_layer")
    return actions


def workflow_snapshot(graph: Graph, selected_node_id: Optional[str] = None) -> dict[str, Any]:
    focus_parent_id = graph.focus_parent_id or graph.root_id
    if focus_parent_id not in graph.nodes:
        focus_parent_id = graph.root_id
    child_ids = layer_children(graph, focus_parent_id)
    return {
        "stage": workflow_stage(graph, selected_node_id),
        "allowed_actions": workflow_actions(graph, selected_node_id),
        "focus_parent_id": focus_parent_id,
        "selected_node_id": selected_node_id,
        "total_children": len(child_ids),
        "planned_children": sum(
            1 for child_id in child_ids if graph.nodes[child_id].status == NodeStatus.PLANNED
        ),
    }


def draft_children_for_node(
    graph: Graph,
    node_id: str,
    provider: LLMProvider,
    target_children: int = 7,
    min_children: int = 5,
    max_children: int = 9,
):
    node = _require_node(graph, node_id)
    if node.status == NodeStatus.DRAFT and node.parent_id is not None:
        raise ValueError(f"Node {node.id} is not baselined; baseline it first.")
    if node.children_ids:
        return []
    if node.parent_id and not layer_is_complete(graph, node.parent_id):
        raise ValueError(
            f"Sibling layer for parent {node.parent_id} is not complete; plan siblings first."
        )

    context = build_context(graph, node.id)
    drafts = provider.decompose(node, context, target_children, min_children, max_children)
    drafts = drafts[:max_children]
    for draft in drafts:
        if not (draft.smart.specific and draft.smart.measurable and draft.smart.relevant):
            raise ValueError("Each workstream must include specific, measurable, and relevant.")
        if not draft.workstream:
            raise ValueError("Each workstream must include a short workstream label.")
    return drafts


def decompose_node(
    graph: Graph,
    node_id: str,
    provider: LLMProvider,
    target_children: int = 7,
    min_children: int = 5,
    max_children: int = 9,
) -> tuple[Graph, list[str]]:
    drafts = draft_children_for_node(
        graph,
        node_id,
        provider,
        target_children=target_children,
        min_children=min_children,
        max_children=max_children,
    )
    new_graph = graph.model_copy(deep=True)
    node = _require_node(new_graph, node_id)
    new_ids: list[str] = []
    for draft in drafts:
        new_graph, child_id = add_node(
            new_graph,
            parent_id=node.id,
            title=draft.title,
            workstream=draft.workstream,
            smart=draft.smart,
            status=NodeStatus.DRAFT,
            ui=NodeUI(layout_mode=LayoutMode.auto),
        )
        new_ids.append(child_id)

    new_graph = sync_suggested_connections_for_drafts(new_graph, drafts, new_ids)
    return new_graph, new_ids


def add_node(
    graph: Graph,
    parent_id: str,
    title: str,
    workstream: str,
    smart: SMARTFields,
    status: NodeStatus = NodeStatus.BASELINED,
    baseline: Optional[NodeBaseline] = None,
    ui: Optional[NodeUI] = None,
    suggested_parent_id: Optional[str] = None,
    suggested_path_ids: Optional[list[str]] = None,
) -> tuple[Graph, str]:
    new_graph = graph.model_copy(deep=True)
    parent = _require_node(new_graph, parent_id)
    child_id = _next_node_id(new_graph.nodes)
    initial_path_ids = suggested_path_ids or [*_path_ids_for_node(new_graph, parent.id), child_id]
    new_graph.nodes[child_id] = Node(
        id=child_id,
        title=title,
        workstream=workstream,
        layer=parent.layer + 1,
        parent_id=parent.id,
        smart=smart,
        baseline=baseline.model_copy(deep=True) if baseline is not None else None,
        status=status,
        ui=ui.model_copy(deep=True) if ui is not None else NodeUI(),
        suggested_parent_id=suggested_parent_id if suggested_parent_id is not None else parent.id,
        suggested_path_ids=initial_path_ids,
    )
    parent.children_ids.append(child_id)
    new_graph.updated_at = _now_iso()
    return new_graph, child_id


def update_node(
    graph: Graph,
    node_id: str,
    title: Optional[str] = None,
    workstream: Optional[str] = None,
    smart: Optional[SMARTFields] = None,
    smart_patch: Optional[SMARTFields] = None,
    baseline: Optional[NodeBaseline] = None,
    baseline_notes: Optional[list[str]] = None,
    assumptions: Optional[list[str]] = None,
    constraints: Optional[list[str]] = None,
    unknowns: Optional[list[str]] = None,
    status: Optional[NodeStatus] = None,
) -> Graph:
    if (
        title is None
        and workstream is None
        and smart is None
        and smart_patch is None
        and baseline is None
        and baseline_notes is None
        and assumptions is None
        and constraints is None
        and unknowns is None
        and status is None
    ):
        raise ValueError("Node update requires at least one changed field.")
    new_graph = graph.model_copy(deep=True)
    node = _require_node(new_graph, node_id)
    if title is not None:
        node.title = title
    if workstream is not None:
        node.workstream = workstream
    if smart is not None:
        node.smart = smart
    if smart_patch is not None:
        node.smart = _merge_smart_fields(node.smart, smart_patch)
    next_baseline = _rebuild_baseline(
        node,
        baseline=baseline,
        baseline_notes=baseline_notes,
        assumptions=assumptions,
        constraints=constraints,
        unknowns=unknowns,
    )
    if next_baseline is not None:
        node.baseline = next_baseline
    if status is not None:
        node.status = status
    new_graph.updated_at = _now_iso()
    return new_graph


def move_node(graph: Graph, node_id: str, parent_id: str) -> Graph:
    new_graph = graph.model_copy(deep=True)
    node = _require_node(new_graph, node_id)
    if node.id == new_graph.root_id:
        raise ValueError("Cannot move the root node.")

    target_parent = _require_node(new_graph, parent_id)
    subtree_ids = set(_iter_subtree_ids(new_graph, node.id))
    if target_parent.id in subtree_ids:
        raise ValueError("Cannot move a node into its own subtree.")

    old_parent = _require_node(new_graph, node.parent_id) if node.parent_id else None
    if old_parent is not None:
        old_parent.children_ids = [
            child_id for child_id in old_parent.children_ids if child_id != node.id
        ]

    if node.id not in target_parent.children_ids:
        target_parent.children_ids.append(node.id)
    node.parent_id = target_parent.id
    _reindex_subtree_layers(new_graph, node.id, target_parent.layer + 1)
    new_graph.updated_at = _now_iso()
    return new_graph


def upsert_suggested_connection(
    graph: Graph,
    source_id: str,
    target_id: str,
    label: str = "",
    rationale: str = "",
) -> Graph:
    new_graph = graph.model_copy(deep=True)
    source = _require_node(new_graph, source_id)
    target = _require_node(new_graph, target_id)
    if source.id == target.id:
        raise ValueError("Connection source and target must be different.")
    if source.parent_id != target.parent_id:
        raise ValueError("Connections can only be assigned between sibling nodes.")
    if source.parent_id is None:
        raise ValueError("Root-level connections are not supported.")

    parent = _require_node(new_graph, source.parent_id)
    order_by_id = {
        child_id: index
        for index, child_id in enumerate(parent.children_ids)
        if child_id in new_graph.nodes
    }
    if order_by_id.get(source.id, -1) >= order_by_id.get(target.id, -1):
        raise ValueError("Connections must point from left to right in sibling order.")

    new_graph.suggested_connections = [
        connection
        for connection in new_graph.suggested_connections
        if not (connection.source_id == source.id and connection.target_id == target.id)
    ]
    new_graph.suggested_connections.append(
        SuggestedConnection(
            source_id=source.id,
            target_id=target.id,
            label=label,
            rationale=rationale,
        )
    )
    _prune_suggested_connections(new_graph)
    _enforce_ordered_suggested_connections(new_graph, parent.children_ids)
    _ensure_transitive_suggested_connections(new_graph, parent.children_ids)
    new_graph.updated_at = _now_iso()
    return new_graph


def delete_suggested_connection(graph: Graph, source_id: str, target_id: str) -> Graph:
    new_graph = graph.model_copy(deep=True)
    _require_node(new_graph, source_id)
    _require_node(new_graph, target_id)
    new_graph.suggested_connections = [
        connection
        for connection in new_graph.suggested_connections
        if not (connection.source_id == source_id and connection.target_id == target_id)
    ]
    new_graph.updated_at = _now_iso()
    return new_graph


def delete_node(graph: Graph, node_id: str) -> Graph:
    new_graph = graph.model_copy(deep=True)
    node = _require_node(new_graph, node_id)
    if node.id == new_graph.root_id:
        raise ValueError("Cannot delete the root node.")

    parent_id = node.parent_id
    if parent_id:
        parent = new_graph.nodes.get(parent_id)
        if parent:
            parent.children_ids = [
                child_id for child_id in parent.children_ids if child_id != node.id
            ]

    deleted_ids = set(_iter_subtree_ids(new_graph, node.id))
    for deleted_id in deleted_ids:
        new_graph.nodes.pop(deleted_id, None)
    _prune_suggested_connections(new_graph)

    if new_graph.focus_parent_id in deleted_ids:
        fallback_parent = parent_id or new_graph.root_id
        focus = _require_node(new_graph, fallback_parent)
        new_graph.focus_parent_id = fallback_parent
        new_graph.active_layer = focus.layer + 1

    new_graph.updated_at = _now_iso()
    return new_graph


def set_node_position(
    graph: Graph,
    node_id: str,
    position: Optional[NodePosition] = None,
    layout_mode: Optional[LayoutMode] = None,
) -> Graph:
    new_graph = graph.model_copy(deep=True)
    node = _require_node(new_graph, node_id)
    next_layout_mode = layout_mode or (
        LayoutMode.manual if position is not None else node.ui.layout_mode
    )
    if next_layout_mode == LayoutMode.auto:
        node.ui = NodeUI(layout_mode=LayoutMode.auto, position=None)
    else:
        if position is None:
            raise ValueError("Manual node positions require coordinates.")
        node.ui = NodeUI(layout_mode=LayoutMode.manual, position=position)
    new_graph.updated_at = _now_iso()
    return new_graph


def set_focus(graph: Graph, focus_parent_id: str, active_layer: Optional[int] = None) -> Graph:
    new_graph = graph.model_copy(deep=True)
    focus = _require_node(new_graph, focus_parent_id)
    new_graph.focus_parent_id = focus_parent_id
    new_graph.active_layer = active_layer if active_layer and active_layer > 0 else focus.layer + 1
    new_graph.updated_at = _now_iso()
    return new_graph


def node_progress(node: Node) -> dict[str, object]:
    tasks = node.plan.tasks if node.plan else []
    total_tasks = len(tasks)
    completed_tasks = sum(1 for task in tasks if task.completed)
    if total_tasks == 0 or completed_tasks == 0:
        check_state = CheckState.unchecked
    elif completed_tasks == total_tasks:
        check_state = CheckState.checked
    else:
        check_state = CheckState.partial
    return {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "check_state": check_state.value,
    }


def graph_progress(graph: Graph) -> dict[str, dict[str, object]]:
    return {node_id: node_progress(node) for node_id, node in graph.nodes.items()}


def toggle_task_completion(
    graph: Graph,
    node_id: str,
    task_index: int,
    completed: bool,
) -> Graph:
    new_graph = graph.model_copy(deep=True)
    node = _require_node(new_graph, node_id)
    if node.plan is None or not node.plan.tasks:
        raise ValueError(f"Node {node_id} has no tasks to toggle.")
    if task_index < 0 or task_index >= len(node.plan.tasks):
        raise ValueError(f"Task index out of range for node {node_id}: {task_index}")
    node.plan.tasks[task_index].completed = completed
    new_graph.updated_at = _now_iso()
    return new_graph


def toggle_subgoal_completion(
    graph: Graph,
    node_id: str,
    completed: bool,
) -> Graph:
    new_graph = graph.model_copy(deep=True)
    node = _require_node(new_graph, node_id)
    if node.plan is None or not node.plan.tasks:
        raise ValueError(f"Node {node_id} has no tasks to toggle.")
    for task in node.plan.tasks:
        task.completed = completed
    new_graph.updated_at = _now_iso()
    return new_graph


def _find_cycle(graph_by_task: dict[str, list[str]]) -> bool:
    visited: set[str] = set()
    visiting: set[str] = set()

    def dfs(task_title: str) -> bool:
        if task_title in visiting:
            return True
        if task_title in visited:
            return False
        visiting.add(task_title)
        for dep in graph_by_task.get(task_title, []):
            if dfs(dep):
                return True
        visiting.remove(task_title)
        visited.add(task_title)
        return False

    for title in graph_by_task:
        if dfs(title):
            return True
    return False


def validate_plan_replacement(tasks: list[Task]) -> list[str]:
    errors: list[str] = []
    titles: list[str] = []

    for idx, task in enumerate(tasks):
        title = task.title.strip()
        if not title:
            errors.append(f"tasks[{idx}].title is required")
        if not task.description.strip():
            errors.append(f"tasks[{idx}].description is required")
        if not task.success_criteria.strip():
            errors.append(f"tasks[{idx}].success_criteria is required")
        if not (task.relative_timing or "").strip():
            errors.append(f"tasks[{idx}].relative_timing is required")
        if not (task.due or "").strip():
            errors.append(f"tasks[{idx}].due is required")
        titles.append(title)

    non_empty_titles = [title for title in titles if title]
    if len(non_empty_titles) != len(set(non_empty_titles)):
        errors.append("task titles must be unique per node")

    title_set = set(non_empty_titles)
    dep_graph: dict[str, list[str]] = {}
    for idx, task in enumerate(tasks):
        title = task.title.strip()
        if not title:
            continue
        dep_graph[title] = []
        for dep in task.depends_on:
            dep_title = dep.strip()
            if not dep_title:
                errors.append(f"tasks[{idx}].depends_on contains empty dependency")
                continue
            if dep_title not in title_set:
                errors.append(f"tasks[{idx}].depends_on target not found: '{dep_title}'")
                continue
            if dep_title == title:
                errors.append(f"tasks[{idx}].depends_on cannot include self: '{title}'")
                continue
            dep_graph[title].append(dep_title)

    if dep_graph and _find_cycle(dep_graph):
        errors.append("task dependencies contain a cycle")

    return errors


def replace_plan(
    graph: Graph,
    node_id: str,
    tasks: list[Task],
) -> Graph:
    errors = validate_plan_replacement(tasks)
    if errors:
        raise ValueError("; ".join(errors))

    new_graph = graph.model_copy(deep=True)
    node = _require_node(new_graph, node_id)
    node.plan = NodePlan(tasks=tasks)
    node.status = NodeStatus.PLANNED
    new_graph.updated_at = _now_iso()
    return new_graph


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
        if node.id == graph.root_id:
            raise ValueError("Cannot delete the root node.")
        if node.children_ids:
            raise ValueError(f"Cannot delete node with children: {node.id}")
        if node.parent_id:
            parent = graph.nodes.get(node.parent_id)
            if parent:
                parent.children_ids = [
                    child_id for child_id in parent.children_ids if child_id != node.id
                ]
        del graph.nodes[node.id]
        _prune_suggested_connections(graph)
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
    _prune_suggested_connections(graph)
    return summaries


def baseline_interview(
    graph: Graph,
    node_id: str,
    provider: LLMProvider,
    ask_fn: Callable[[str], str],
) -> tuple[Graph, list[str]]:
    new_graph = graph.model_copy(deep=True)
    node = _require_node(new_graph, node_id)

    siblings = _siblings_for_node(new_graph, node)
    context = build_context(new_graph, node_id)
    questions = provider.baseline_questions(node, context)
    qa_pairs = collect_baseline_answers(questions, ask_fn)

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
    node = _require_node(new_graph, node_id)

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

    node = _require_node(new_graph, node_id)
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
    baselined_out = {str(layer): baselined.get(layer, 0) for layer in sorted(layers.keys())}
    planned_out = {str(layer): planned.get(layer, 0) for layer in sorted(layers.keys())}
    return {
        "total_nodes": len(graph.nodes),
        "layers": layers_out,
        "baselined": baselined_out,
        "planned": planned_out,
        "focus_parent_id": graph.focus_parent_id,
        "active_layer": graph.active_layer,
        "workflow": workflow_snapshot(graph),
    }
