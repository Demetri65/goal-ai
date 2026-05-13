from smart_got.models import Graph


def test_task_completed_defaults_false_for_legacy_graph_payload():
    raw_graph = {
        "root_id": "root",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "nodes": {
            "root": {
                "id": "root",
                "title": "Legacy goal",
                "workstream": "Goal",
                "layer": 0,
                "parent_id": None,
                "children_ids": [],
                "smart": {
                    "specific": "Legacy goal",
                    "measurable": "",
                    "achievable": "",
                    "relevant": "",
                    "time_bound": "",
                },
                "plan": {
                    "tasks": [
                        {
                            "title": "Legacy task",
                            "description": "",
                            "success_criteria": "Done",
                            "depends_on": [],
                            "estimate_hours": None,
                            "relative_timing": "Week 1",
                            "due": "TBD",
                        }
                    ],
                    "milestones": [],
                },
                "status": "PLANNED",
            }
        },
    }

    graph = Graph.model_validate(raw_graph)
    assert graph.nodes["root"].plan is not None
    assert "milestones" not in graph.nodes["root"].plan.model_dump(mode="json")
    assert graph.nodes["root"].plan.tasks[0].completed is False
    assert graph.nodes["root"].ui.layout_mode == "auto"
    assert graph.nodes["root"].ui.position is None
    assert graph.nodes["root"].suggested_parent_id is None
    assert graph.nodes["root"].suggested_path_ids == ["root"]
    assert graph.suggested_connections == []


def test_legacy_nodes_backfill_suggested_path_metadata():
    raw_graph = {
        "root_id": "root",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "nodes": {
            "root": {
                "id": "root",
                "title": "Legacy goal",
                "workstream": "Goal",
                "layer": 0,
                "parent_id": None,
                "children_ids": ["n1"],
                "smart": {
                    "specific": "Legacy goal",
                    "measurable": "",
                    "achievable": "",
                    "relevant": "",
                    "time_bound": "",
                },
                "status": "BASELINED",
            },
            "n1": {
                "id": "n1",
                "title": "Child goal",
                "workstream": "General",
                "layer": 1,
                "parent_id": "root",
                "children_ids": [],
                "smart": {
                    "specific": "",
                    "measurable": "",
                    "achievable": "",
                    "relevant": "",
                    "time_bound": "",
                },
                "status": "DRAFT",
            },
        },
    }

    graph = Graph.model_validate(raw_graph)

    assert graph.nodes["n1"].suggested_parent_id == "root"
    assert graph.nodes["n1"].suggested_path_ids == ["root", "n1"]


def test_legacy_graph_payload_prunes_invalid_suggested_connections():
    raw_graph = {
        "root_id": "root",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "nodes": {
            "root": {
                "id": "root",
                "title": "Legacy goal",
                "workstream": "Goal",
                "layer": 0,
                "parent_id": None,
                "children_ids": ["n1"],
                "smart": {
                    "specific": "Legacy goal",
                    "measurable": "",
                    "achievable": "",
                    "relevant": "",
                    "time_bound": "",
                },
                "status": "BASELINED",
            },
            "n1": {
                "id": "n1",
                "title": "Child goal",
                "workstream": "General",
                "layer": 1,
                "parent_id": "root",
                "children_ids": [],
                "smart": {
                    "specific": "",
                    "measurable": "",
                    "achievable": "",
                    "relevant": "",
                    "time_bound": "",
                },
                "status": "DRAFT",
            },
        },
        "suggested_connections": [
            {"source_id": "root", "target_id": "n1"},
            {"source_id": "n1", "target_id": "missing"},
            {"source_id": "n1", "target_id": "n1"},
        ],
    }

    graph = Graph.model_validate(raw_graph)

    assert len(graph.suggested_connections) == 1
    assert graph.suggested_connections[0].source_id == "root"
    assert graph.suggested_connections[0].target_id == "n1"
