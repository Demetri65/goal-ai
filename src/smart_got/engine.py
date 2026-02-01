from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from smart_got.llm import LLMProvider
from smart_got.models import BaselineQA, Graph, Node, NodeStatus, SMARTFields


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
        layer=0,
        smart=SMARTFields(specific=goal),
    )
    now = _now_iso()
    return Graph(root_id=root_id, nodes={root_id: root}, created_at=now, updated_at=now)


def layer_complete(graph: Graph, layer: int) -> bool:
    return all(
        node.status == NodeStatus.BASELINED
        for node in graph.nodes.values()
        if node.layer == layer
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
    if node.children_ids:
        return new_graph, []
    if not layer_complete(new_graph, node.layer):
        raise ValueError(f"Layer {node.layer} is not complete; baseline it first.")

    siblings = [
        sibling
        for sibling in new_graph.nodes.values()
        if sibling.parent_id == node.parent_id and sibling.id != node.id
    ]
    drafts = provider.decompose(
        node, siblings, target_children, min_children, max_children
    )
    drafts = drafts[:max_children]
    new_ids: list[str] = []
    for draft in drafts:
        if not (draft.smart.specific and draft.smart.measurable and draft.smart.relevant):
            raise ValueError("Each workstream must include specific, measurable, and relevant.")
        child_id = _next_node_id(new_graph.nodes)
        child = Node(
            id=child_id,
            title=draft.title,
            layer=node.layer + 1,
            parent_id=node.id,
            smart=draft.smart,
        )
        new_graph.nodes[child_id] = child
        node.children_ids.append(child_id)
        new_ids.append(child_id)

    new_graph.updated_at = _now_iso()
    return new_graph, new_ids


def apply_baseline(
    graph: Graph,
    node_id: str,
    qa_pairs: list[BaselineQA],
    smart_patch: Optional[SMARTFields] = None,
) -> Graph:
    new_graph = graph.model_copy(deep=True)
    node = new_graph.nodes.get(node_id)
    if node is None:
        raise KeyError(f"Node not found: {node_id}")

    node.baseline = qa_pairs
    if smart_patch is not None:
        node.smart = _merge_smart_fields(node.smart, smart_patch)
    node.status = NodeStatus.BASELINED
    new_graph.updated_at = _now_iso()
    return new_graph


def status_summary(graph: Graph) -> dict[str, object]:
    layers: dict[int, int] = {}
    baselined: dict[int, int] = {}
    for node in graph.nodes.values():
        layers[node.layer] = layers.get(node.layer, 0) + 1
        if node.status == NodeStatus.BASELINED:
            baselined[node.layer] = baselined.get(node.layer, 0) + 1

    layers_out = {str(layer): count for layer, count in sorted(layers.items())}
    baselined_out = {
        str(layer): baselined.get(layer, 0) for layer in sorted(layers.keys())
    }
    return {
        "total_nodes": len(graph.nodes),
        "layers": layers_out,
        "baselined": baselined_out,
    }
