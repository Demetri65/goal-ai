import pytest

from smart_got import engine
from smart_got.models import NodePlan, SMARTFields, Task


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


def test_delete_node_blocks_root_and_nodes_with_children():
    graph = engine.init_graph("Goal")
    graph, child_id = engine.add_node(
        graph,
        parent_id="root",
        title="Child",
        workstream="Ops",
        smart=SMARTFields(specific="x", measurable="y", relevant="z"),
    )
    graph, _ = engine.add_node(
        graph,
        parent_id=child_id,
        title="Grandchild",
        workstream="Ops",
        smart=SMARTFields(specific="x", measurable="y", relevant="z"),
    )

    with pytest.raises(ValueError):
        engine.delete_node(graph, "root")

    with pytest.raises(ValueError):
        engine.delete_node(graph, child_id)
