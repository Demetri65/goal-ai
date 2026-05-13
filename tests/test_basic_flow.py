import re

import pytest

from smart_got import engine
from smart_got.llm import MockProvider
from smart_got.models import (
    AddSiblingMutation,
    ChildDraft,
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
        if "hours/week" in q or "hours per week" in q or "commit each week" in q:
            return "achievable"
        if "target date" in q or "deadline" in q or "checkpoint cadence" in q or "what date" in q:
            return "time_bound"
        if "resource" in q:
            return "resources"
        if "constraints" in q or "dependencies" in q or "dependency" in q:
            return "constraints"
        if "risks" in q or "unknowns" in q or "uncertainty" in q:
            return "unknowns"
        if "concrete output" in q or "achievable in this phase" in q or "evidence proves" in q:
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

    title_by_id = {child_id: graph.nodes[child_id].title for child_id in child_ids}
    connection_pairs = {
        (title_by_id[item.source_id], title_by_id[item.target_id])
        for item in graph.suggested_connections
    }
    assert ("Define Scope and Success", "Plan Resource Coverage") in connection_pairs
    assert ("Build Timeline", "Prepare Operations Logistics") in connection_pairs


def test_decompose_ignores_invalid_dependency_titles():
    class InvalidDependencyProvider(MockProvider):
        def decompose(self, node, context, target_children, min_children, max_children):
            del context, target_children, min_children, max_children
            return [
                ChildDraft(
                    title="Start Work",
                    workstream="Start",
                    depends_on=["Missing Work"],
                    smart=SMARTFields(
                        specific=f"Start work for {node.title}",
                        measurable="Start complete",
                        relevant=f"Supports {node.title}",
                    ),
                ),
                ChildDraft(
                    title="Finish Work",
                    workstream="Finish",
                    depends_on=["Start Work", "Finish Work"],
                    smart=SMARTFields(
                        specific=f"Finish work for {node.title}",
                        measurable="Finish complete",
                        relevant=f"Supports {node.title}",
                    ),
                ),
            ]

    graph = engine.init_graph("Launch pilot")
    graph, child_ids = engine.decompose_node(
        graph,
        graph.root_id,
        InvalidDependencyProvider(),
        target_children=2,
        min_children=2,
        max_children=2,
    )

    assert len(graph.suggested_connections) == 1
    connection = graph.suggested_connections[0]
    assert connection.source_id == child_ids[0]
    assert connection.target_id == child_ids[1]


def test_decompose_adds_transitive_dependency_connections():
    class ChainedDependencyProvider(MockProvider):
        def decompose(self, node, context, target_children, min_children, max_children):
            del context, target_children, min_children, max_children
            return [
                ChildDraft(
                    title="Scope Work",
                    workstream="Scope",
                    smart=SMARTFields(
                        specific=f"Scope work for {node.title}",
                        measurable="Scope complete",
                        relevant=f"Supports {node.title}",
                    ),
                ),
                ChildDraft(
                    title="Build Work",
                    workstream="Build",
                    depends_on=["Scope Work"],
                    smart=SMARTFields(
                        specific=f"Build work for {node.title}",
                        measurable="Build complete",
                        relevant=f"Supports {node.title}",
                    ),
                ),
                ChildDraft(
                    title="Launch Work",
                    workstream="Launch",
                    depends_on=["Build Work"],
                    smart=SMARTFields(
                        specific=f"Launch work for {node.title}",
                        measurable="Launch complete",
                        relevant=f"Supports {node.title}",
                    ),
                ),
            ]

    graph = engine.init_graph("Launch pilot")
    graph, child_ids = engine.decompose_node(
        graph,
        graph.root_id,
        ChainedDependencyProvider(),
        target_children=3,
        min_children=3,
        max_children=3,
    )

    connection_pairs = {
        (connection.source_id, connection.target_id)
        for connection in graph.suggested_connections
    }
    assert (child_ids[0], child_ids[1]) in connection_pairs
    assert (child_ids[1], child_ids[2]) in connection_pairs
    assert (child_ids[0], child_ids[2]) in connection_pairs


def test_decompose_ignores_backward_dependency_connections():
    class BackwardDependencyProvider(MockProvider):
        def decompose(self, node, context, target_children, min_children, max_children):
            del context, target_children, min_children, max_children
            return [
                ChildDraft(
                    title="First Work",
                    workstream="First",
                    depends_on=["Second Work"],
                    smart=SMARTFields(
                        specific=f"First work for {node.title}",
                        measurable="First complete",
                        relevant=f"Supports {node.title}",
                    ),
                ),
                ChildDraft(
                    title="Second Work",
                    workstream="Second",
                    smart=SMARTFields(
                        specific=f"Second work for {node.title}",
                        measurable="Second complete",
                        relevant=f"Supports {node.title}",
                    ),
                ),
            ]

    graph = engine.init_graph("Launch pilot")
    graph, _ = engine.decompose_node(
        graph,
        graph.root_id,
        BackwardDependencyProvider(),
        target_children=2,
        min_children=2,
        max_children=2,
    )

    assert graph.suggested_connections == []


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


def test_build_layer_decomposes_baselines_and_plans_children():
    provider = MockProvider()
    graph = engine.init_graph("Launch pilot")
    questions = engine.layer_baseline_questions(graph, graph.root_id, provider)
    answers = engine.collect_baseline_answers(questions, FakeAskFn())

    updated, summary = engine.build_layer(
        graph,
        graph.root_id,
        provider,
        answers,
        target_children=7,
        min_children=5,
        max_children=9,
    )

    assert summary["decomposed"] is True
    assert summary["baselined_ids"]
    assert summary["planned_ids"]
    assert engine.layer_is_complete(updated, updated.root_id)
    assert all(
        updated.nodes[child_id].status == NodeStatus.PLANNED
        for child_id in updated.nodes[updated.root_id].children_ids
    )
    assert updated.suggested_connections
    assert all(
        connection.source_id in updated.nodes and connection.target_id in updated.nodes
        for connection in updated.suggested_connections
    )


def test_build_layer_skips_duplicate_decomposition_for_existing_children():
    provider = MockProvider()
    graph = engine.init_graph("Launch pilot")
    graph, child_ids = engine.decompose_node(
        graph,
        graph.root_id,
        provider,
        target_children=7,
        min_children=5,
        max_children=9,
    )
    questions = engine.layer_baseline_questions(graph, graph.root_id, provider)
    answers = engine.collect_baseline_answers(questions, FakeAskFn())

    updated, summary = engine.build_layer(
        graph,
        graph.root_id,
        provider,
        answers,
        target_children=7,
        min_children=5,
        max_children=9,
    )

    assert summary["decomposed"] is False
    assert summary["child_ids"] == child_ids
    assert len(summary["baselined_ids"]) == len(child_ids)
    assert engine.layer_is_complete(updated, updated.root_id)


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
