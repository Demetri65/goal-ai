import re

import pytest

from smart_got import engine
from smart_got.llm import MockProvider
from smart_got.models import (
    AddSiblingMutation,
    DeleteNodeMutation,
    Node,
    NodeStatus,
    SMARTFields,
    UpdateNodeMutation,
)
from smart_got.store import load_graph, save_graph


class FakeAskFn:
    def __init__(self):
        self.answers_by_category = {
            "achievable": "6 hours/week from one coordinator",
            "time_bound": "2026-06-30",
            "resources": "2 volunteers, $500 budget, and route-planning tools",
            "constraints": "City permit requires 4 weeks lead time",
            "unknowns": "Weather and turnout variance",
            "assumptions": "City approves route with one revision cycle",
            "default": "Acknowledged",
        }
        self.calls: list[str] = []

    @staticmethod
    def _category_for_question(question_text: str) -> str:
        q = question_text.lower()
        if "hours/week" in q or "commit each week" in q:
            return "achievable"
        if "target date" in q or "deadline" in q or "checkpoint cadence" in q:
            return "time_bound"
        if "what resources" in q:
            return "resources"
        if "constraints" in q or "dependencies" in q:
            return "constraints"
        if "risks" in q or "unknowns" in q:
            return "unknowns"
        if "concrete output" in q or "achievable in this phase" in q:
            return "assumptions"
        return "default"

    def __call__(self, question_text: str) -> str:
        self.calls.append(question_text)
        category = self._category_for_question(question_text)
        return self.answers_by_category[category]


def _baseline_node(graph, node_id, provider):
    ask_fn = FakeAskFn()
    graph, _ = engine.baseline_interview(graph, node_id, provider, ask_fn=ask_fn)
    return graph


def test_decompose_children_quality_and_title_guards():
    provider = MockProvider()
    graph = engine.init_graph("Plan a 10k charity run")
    graph, child_ids = engine.decompose_node(
        graph,
        graph.root_id,
        provider,
        target_children=7,
        min_children=5,
        max_children=9,
    )

    assert 5 <= len(child_ids) <= 9
    forbidden_pattern = re.compile(r"^subgoal\s*\d+$", re.IGNORECASE)
    for child_id in child_ids:
        child = graph.nodes[child_id]
        assert child.workstream.strip()
        assert child.smart.specific.strip()
        assert child.smart.measurable.strip()
        assert child.smart.relevant.strip()
        assert "&" not in child.title
        assert "&" not in child.workstream
        assert not forbidden_pattern.match(child.title.strip())
        assert not child.title.lower().startswith("research ")
        assert not child.title.lower().startswith("design ")
        assert not child.title.lower().startswith("deliver ")


def test_baseline_interview_updates_achievable_and_timebound():
    provider = MockProvider()
    graph = engine.init_graph("Launch pilot")
    ask_fn = FakeAskFn()

    updated, _ = engine.baseline_interview(graph, graph.root_id, provider, ask_fn=ask_fn)
    node = updated.nodes[updated.root_id]

    assert node.status == NodeStatus.BASELINED
    assert node.smart.achievable.strip()
    assert node.smart.time_bound.strip()
    assert node.baseline is not None
    assert node.baseline.qa
    assert len(ask_fn.calls) >= 4


def test_plan_node_has_relative_timing_and_due_for_mock():
    provider = MockProvider()
    graph = engine.init_graph("Launch pilot")
    graph = _baseline_node(graph, graph.root_id, provider)

    planned = engine.plan_node(graph, graph.root_id, provider)
    node = planned.nodes[planned.root_id]

    assert node.status == NodeStatus.PLANNED
    assert node.plan is not None
    assert node.plan.tasks
    for task in node.plan.tasks:
        assert task.relative_timing
        assert task.due is not None


def test_layer_mutation_safety():
    graph = engine.init_graph("Mutation safety")
    root = graph.nodes[graph.root_id]

    graph.nodes["n1"] = Node(
        id="n1",
        title="Existing child",
        workstream="Ops",
        layer=1,
        parent_id=root.id,
        children_ids=["n2"],
        smart=SMARTFields(
            specific="Run operations",
            measurable="Ops readiness reviewed",
            relevant="Supports root",
        ),
        status=NodeStatus.BASELINED,
    )
    graph.nodes["n2"] = Node(
        id="n2",
        title="Grandchild",
        workstream="OpsDetail",
        layer=2,
        parent_id="n1",
        smart=SMARTFields(
            specific="Detail operations",
            measurable="Checklist complete",
            relevant="Supports operations",
        ),
    )
    graph.nodes["n3"] = Node(
        id="n3",
        title="Leaf child",
        workstream="Leaf",
        layer=1,
        parent_id=root.id,
        smart=SMARTFields(
            specific="Leaf specific",
            measurable="Leaf measurable",
            relevant="Leaf relevant",
        ),
    )
    root.children_ids = ["n1", "n3"]

    summaries = engine.apply_layer_mutations(
        graph,
        [
            AddSiblingMutation(
                parent_id=root.id,
                title="Added sibling",
                workstream="Added",
                smart=SMARTFields(
                    specific="Added specific",
                    measurable="Added measurable",
                    relevant="Added relevant",
                ),
            ),
            UpdateNodeMutation(
                node_id="n1",
                title="Existing child updated",
                smart_patch=SMARTFields(achievable="Use coordinator coverage"),
            ),
        ],
    )
    assert any(item.startswith("add_sibling:root:") for item in summaries)
    assert any(item.startswith("update:n1") for item in summaries)
    assert graph.nodes["n1"].title == "Existing child updated"
    assert graph.nodes["n1"].smart.achievable == "Use coordinator coverage"

    with pytest.raises(ValueError):
        engine.apply_layer_mutations(graph, [DeleteNodeMutation(node_id="n1")])

    leaf_delete = engine.apply_layer_mutations(graph, [DeleteNodeMutation(node_id="n3")])
    assert leaf_delete == ["delete:n3"]
    assert "n3" not in graph.nodes
    assert "n3" not in graph.nodes[root.id].children_ids


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
