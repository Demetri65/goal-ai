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
