import pytest

from smart_got import engine
from smart_got.llm import MockProvider
from smart_got.models import BaselineQA, SMARTFields
from smart_got.store import load_graph, save_graph


def _baseline_node(graph, node_id, provider):
    node = graph.nodes[node_id]
    root = graph.nodes[graph.root_id]
    questions = provider.baseline_questions(root, None, node)
    answers = [BaselineQA(question=q, answer="ok") for q in questions]
    patch = SMARTFields(measurable="Measure progress", relevant=f"Supports {node.title}")
    return engine.apply_baseline(graph, node_id, answers, patch)


def test_decompose_requires_layer_completion():
    provider = MockProvider()
    graph = engine.init_graph("Launch pilot")

    with pytest.raises(ValueError):
        engine.decompose_node(graph, graph.root_id, provider)

    graph = _baseline_node(graph, graph.root_id, provider)
    graph, child_ids = engine.decompose_node(
        graph,
        graph.root_id,
        provider,
        target_children=7,
        min_children=5,
        max_children=9,
    )

    assert 5 <= len(child_ids) <= 9
    for child_id in child_ids:
        child = graph.nodes[child_id]
        assert child.smart.specific
        assert child.smart.measurable
        assert child.smart.relevant


def test_save_load_roundtrip(tmp_path):
    provider = MockProvider()
    graph = engine.init_graph("Launch pilot")
    graph = _baseline_node(graph, graph.root_id, provider)
    graph, child_ids = engine.decompose_node(
        graph,
        graph.root_id,
        provider,
        target_children=7,
        min_children=5,
        max_children=9,
    )

    path = tmp_path / "graph.json"
    save_graph(graph, path)
    loaded = load_graph(path)

    assert loaded.root_id == graph.root_id
    assert set(loaded.nodes.keys()) == set(graph.nodes.keys())
    assert len(loaded.nodes[graph.root_id].children_ids) == len(child_ids)
