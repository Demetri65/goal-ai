import pytest

from smart_got import engine
from smart_got.models import (
    LayoutMode,
    NodePlan,
    NodePosition,
    SMARTFields,
    SuggestedConnection,
    Task,
)


def _graph_with_tasks():
    graph = engine.init_graph("Execution")
    root = graph.nodes[graph.root_id]
    root.plan = NodePlan(
        tasks=[
            Task(
                title="Task A",
                success_criteria="Done A",
                depends_on=[],
                relative_timing="Week 1",
                due="TBD",
            ),
            Task(
                title="Task B",
                success_criteria="Done B",
                depends_on=["Task A"],
                relative_timing="Week 2",
                due="TBD",
            ),
        ],
    )
    return graph


def test_build_context_includes_sibling_plan_task_counts():
    graph = engine.init_graph("Execution")
    graph, sibling_id = engine.add_node(
        graph,
        parent_id=graph.root_id,
        title="Prepare launch",
        workstream="Ops",
        smart=SMARTFields(),
    )
    graph, target_id = engine.add_node(
        graph,
        parent_id=graph.root_id,
        title="Measure launch",
        workstream="Analytics",
        smart=SMARTFields(),
    )
    graph.nodes[sibling_id].plan = NodePlan(
        tasks=[
            Task(title="Task A", description="A", success_criteria="Done A"),
            Task(title="Task B", description="B", success_criteria="Done B"),
            Task(title="Task C", description="C", success_criteria="Done C"),
        ]
    )

    context = engine.build_context(graph, target_id)

    assert "Sibling plan task counts:" in context
    assert "- Prepare launch: 3 tasks" in context
    assert "Sibling plan task details (avoid overlapping these tasks):" in context
    assert "Prepare launch / Task A" in context


def test_validate_plan_replacement_catches_duplicates_missing_targets_and_cycles():
    tasks = [
        Task(title="A", success_criteria="done", depends_on=["A"]),
        Task(title="A", success_criteria="done", depends_on=["B"]),
    ]
    errors = engine.validate_plan_replacement(tasks)

    assert any("unique" in item for item in errors)
    assert any("cannot include self" in item for item in errors)
    assert any("target not found" in item for item in errors)

    cyclic = [
        Task(title="A", success_criteria="done", depends_on=["B"]),
        Task(title="B", success_criteria="done", depends_on=["A"]),
    ]
    cyclic_errors = engine.validate_plan_replacement(cyclic)
    assert any("cycle" in item for item in cyclic_errors)


def test_toggle_task_completion_updates_single_task_only():
    graph = _graph_with_tasks()

    updated = engine.toggle_task_completion(graph, "root", 1, True)
    assert updated.nodes["root"].plan is not None
    assert updated.nodes["root"].plan.tasks[0].completed is False
    assert updated.nodes["root"].plan.tasks[1].completed is True


def test_toggle_subgoal_completion_updates_all_tasks():
    graph = _graph_with_tasks()

    updated = engine.toggle_subgoal_completion(graph, "root", True)
    assert updated.nodes["root"].plan is not None
    assert all(task.completed for task in updated.nodes["root"].plan.tasks)


def test_node_progress_maps_unchecked_partial_checked():
    graph = _graph_with_tasks()
    node = graph.nodes["root"]

    unchecked = engine.node_progress(node)
    assert unchecked["check_state"] == "unchecked"

    node.plan.tasks[0].completed = True
    partial = engine.node_progress(node)
    assert partial["check_state"] == "partial"

    node.plan.tasks[1].completed = True
    checked = engine.node_progress(node)
    assert checked["check_state"] == "checked"


def test_delete_node_blocks_root_and_deletes_subtrees():
    graph = engine.init_graph("Goal")
    graph, child_id = engine.add_node(
        graph,
        parent_id="root",
        title="Child",
        workstream="Ops",
        smart=SMARTFields(specific="x", measurable="y", relevant="z"),
    )
    graph, grandchild_id = engine.add_node(
        graph,
        parent_id=child_id,
        title="Grandchild",
        workstream="Ops",
        smart=SMARTFields(specific="x", measurable="y", relevant="z"),
    )
    graph.suggested_connections.append(
        SuggestedConnection(source_id=child_id, target_id=grandchild_id)
    )

    with pytest.raises(ValueError):
        engine.delete_node(graph, "root")

    updated = engine.delete_node(graph, child_id)
    assert child_id not in updated.nodes
    assert all(node.parent_id != child_id for node in updated.nodes.values())
    assert updated.suggested_connections == []


def test_move_node_reparents_subtree_and_reindexes_layers():
    graph = engine.init_graph("Goal")
    graph, first_id = engine.add_node(
        graph,
        parent_id="root",
        title="First",
        workstream="Ops",
        smart=SMARTFields(specific="x", measurable="y", relevant="z"),
    )
    graph, second_id = engine.add_node(
        graph,
        parent_id="root",
        title="Second",
        workstream="Ops",
        smart=SMARTFields(specific="x", measurable="y", relevant="z"),
    )
    graph, grandchild_id = engine.add_node(
        graph,
        parent_id=first_id,
        title="Grandchild",
        workstream="Ops",
        smart=SMARTFields(specific="x", measurable="y", relevant="z"),
    )

    updated = engine.move_node(graph, first_id, second_id)

    assert updated.nodes[first_id].parent_id == second_id
    assert first_id not in updated.nodes["root"].children_ids
    assert first_id in updated.nodes[second_id].children_ids
    assert updated.nodes[first_id].layer == updated.nodes[second_id].layer + 1
    assert updated.nodes[grandchild_id].layer == updated.nodes[first_id].layer + 1
    assert updated.nodes[first_id].suggested_parent_id == "root"
    assert updated.nodes[first_id].suggested_path_ids == ["root", first_id]

    with pytest.raises(ValueError):
        engine.move_node(updated, second_id, grandchild_id)


def test_add_node_sets_suggested_path_baseline_once():
    graph = engine.init_graph("Goal")
    graph, child_id = engine.add_node(
        graph,
        parent_id="root",
        title="",
        workstream="General",
        smart=SMARTFields(),
        status=engine.NodeStatus.DRAFT,
    )

    assert graph.nodes[child_id].suggested_parent_id == "root"
    assert graph.nodes[child_id].suggested_path_ids == ["root", child_id]


def test_upsert_suggested_connection_enforces_order_and_transitivity():
    graph = engine.init_graph("Goal")
    graph, first_id = engine.add_node(
        graph,
        parent_id="root",
        title="First",
        workstream="Ops",
        smart=SMARTFields(specific="x", measurable="y", relevant="z"),
    )
    graph, second_id = engine.add_node(
        graph,
        parent_id="root",
        title="Second",
        workstream="Ops",
        smart=SMARTFields(specific="x", measurable="y", relevant="z"),
    )
    graph, third_id = engine.add_node(
        graph,
        parent_id="root",
        title="Third",
        workstream="Ops",
        smart=SMARTFields(specific="x", measurable="y", relevant="z"),
    )

    graph = engine.upsert_suggested_connection(graph, first_id, second_id)
    graph = engine.upsert_suggested_connection(graph, second_id, third_id)

    connection_pairs = {
        (connection.source_id, connection.target_id)
        for connection in graph.suggested_connections
    }
    assert (first_id, second_id) in connection_pairs
    assert (second_id, third_id) in connection_pairs
    assert (first_id, third_id) in connection_pairs

    with pytest.raises(ValueError, match="left to right"):
        engine.upsert_suggested_connection(graph, third_id, first_id)


def test_set_node_position_persists_manual_and_can_reset_to_auto():
    graph = engine.init_graph("Goal")
    graph, child_id = engine.add_node(
        graph,
        parent_id="root",
        title="Child",
        workstream="Ops",
        smart=SMARTFields(specific="x", measurable="y", relevant="z"),
    )

    updated = engine.set_node_position(
        graph,
        child_id,
        NodePosition(x=120, y=240),
        LayoutMode.manual,
    )
    assert updated.nodes[child_id].ui.layout_mode == LayoutMode.manual
    assert updated.nodes[child_id].ui.position == NodePosition(x=120, y=240)

    reset = engine.set_node_position(updated, child_id, layout_mode=LayoutMode.auto)
    assert reset.nodes[child_id].ui.layout_mode == LayoutMode.auto
    assert reset.nodes[child_id].ui.position is None
