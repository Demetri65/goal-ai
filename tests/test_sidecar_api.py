import json
import time

from fastapi.testclient import TestClient

from apps.api.main import app
from smart_got import engine
from smart_got.models import BaselineQA, NodePlan, SMARTFields, Task
from smart_got.store import load_graph, save_graph


def _write_graph(path):
    graph = engine.init_graph("Web API goal")
    graph, child_id = engine.add_node(
        graph,
        parent_id="root",
        title="Operations",
        workstream="Ops",
        smart=SMARTFields(
            specific="Run ops",
            measurable="Ops metrics in place",
            relevant="Supports root",
        ),
    )
    graph.nodes[child_id].plan = NodePlan(
        tasks=[
            Task(
                title="Draft checklist",
                success_criteria="Checklist drafted",
                depends_on=[],
                relative_timing="Week 1",
                due="TBD",
            ),
            Task(
                title="Run checklist",
                success_criteria="Checklist run",
                depends_on=["Draft checklist"],
                relative_timing="Week 2",
                due="TBD",
            ),
        ],
    )
    save_graph(graph, path)


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 4.0):
    start = time.time()
    while time.time() - start < timeout:
        response = client.get(f"/api/v1/jobs/{job_id}")
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish in time")


def test_read_endpoints_and_progress(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTGOT_LLM_MODE", "mock")
    graph_path = tmp_path / "graph.json"
    _write_graph(graph_path)

    client = TestClient(app)
    graph_response = client.get("/api/v1/graph", params={"path": str(graph_path)})
    assert graph_response.status_code == 200
    graph_payload = graph_response.json()
    assert graph_payload["graph"]["root_id"] == "root"
    assert "node_progress" in graph_payload

    status_response = client.get("/api/v1/status", params={"path": str(graph_path)})
    assert status_response.status_code == 200
    assert "updated_at" in status_response.json()

    node_response = client.get(
        "/api/v1/nodes/root",
        params={"path": str(graph_path)},
    )
    assert node_response.status_code == 200
    assert node_response.json()["node"]["id"] == "root"

    baseline_response = client.get(
        "/api/v1/baseline/questions",
        params={"path": str(graph_path), "node_id": "root"},
    )
    assert baseline_response.status_code == 200
    assert 4 <= len(baseline_response.json()["questions"]) <= 8


def test_job_lifecycle_and_sse_events(tmp_path):
    graph_path = tmp_path / "graph.json"
    _write_graph(graph_path)

    client = TestClient(app)
    create_job = client.post(
        "/api/v1/jobs/node-add",
        json={
            "path": str(graph_path),
            "parent_id": "root",
            "title": "New child",
            "workstream": "Ops",
            "smart": {
                "specific": "Do thing",
                "measurable": "Done thing",
                "achievable": "",
                "relevant": "Supports",
                "time_bound": "",
            },
        },
    )
    assert create_job.status_code == 200
    job_id = create_job.json()["job_id"]

    event_types: list[str] = []
    with client.stream("GET", f"/api/v1/jobs/{job_id}/events") as stream_response:
        assert stream_response.status_code == 200
        for line in stream_response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = json.loads(line.removeprefix("data: "))
            event_types.append(payload["type"])
            if payload["type"] in {"completed", "failed"}:
                break

    job_payload = _wait_for_job(client, job_id)
    assert job_payload["status"] == "succeeded"
    assert event_types[0] == "queued"
    assert "running" in event_types
    assert "completed" in event_types

    graph = load_graph(graph_path)
    titles = {node.title for node in graph.nodes.values()}
    assert "New child" in titles


def test_plan_replace_validation_and_toggle_jobs(tmp_path):
    graph_path = tmp_path / "graph.json"
    _write_graph(graph_path)
    client = TestClient(app)

    invalid_job = client.post(
        "/api/v1/jobs/plan-replace",
        json={
            "path": str(graph_path),
            "node_id": "root",
            "tasks": [
                {
                    "title": "T1",
                    "description": "",
                    "success_criteria": "done",
                    "depends_on": ["T1"],
                    "estimate_hours": None,
                    "relative_timing": "Week 1",
                    "due": "TBD",
                    "completed": False,
                },
                {
                    "title": "T1",
                    "description": "",
                    "success_criteria": "done",
                    "depends_on": [],
                    "estimate_hours": None,
                    "relative_timing": "Week 2",
                    "due": "TBD",
                    "completed": False,
                },
            ],
        },
    )
    assert invalid_job.status_code == 200
    invalid_job_id = invalid_job.json()["job_id"]
    invalid_status = _wait_for_job(client, invalid_job_id)
    assert invalid_status["status"] == "failed"
    assert "unique" in (invalid_status.get("error") or "")

    valid_job = client.post(
        "/api/v1/jobs/plan-replace",
        json={
            "path": str(graph_path),
            "node_id": "root",
            "tasks": [
                {
                    "title": "Replace task",
                    "description": "Task description",
                    "success_criteria": "Task done",
                    "depends_on": [],
                    "estimate_hours": None,
                    "relative_timing": "Week 1",
                    "due": "TBD",
                    "completed": False,
                }
            ],
        },
    )
    assert valid_job.status_code == 200
    valid_status = _wait_for_job(client, valid_job.json()["job_id"])
    assert valid_status["status"] == "succeeded"

    toggle_job = client.post(
        "/api/v1/jobs/task-toggle",
        json={
            "path": str(graph_path),
            "node_id": "n1",
            "task_index": 0,
            "completed": True,
        },
    )
    assert toggle_job.status_code == 200
    toggle_job_id = toggle_job.json()["job_id"]
    toggle_status = _wait_for_job(client, toggle_job_id)
    assert toggle_status["status"] == "succeeded"

    subgoal_job = client.post(
        "/api/v1/jobs/subgoal-toggle",
        json={
            "path": str(graph_path),
            "node_id": "n1",
            "completed": False,
        },
    )
    assert subgoal_job.status_code == 200
    subgoal_status = _wait_for_job(client, subgoal_job.json()["job_id"])
    assert subgoal_status["status"] == "succeeded"

    graph = load_graph(graph_path)
    assert graph.nodes["n1"].plan is not None
    assert all(task.completed is False for task in graph.nodes["n1"].plan.tasks)


def test_plan_replace_rejects_milestones_payload(tmp_path):
    graph_path = tmp_path / "graph.json"
    _write_graph(graph_path)
    client = TestClient(app)

    response = client.post(
        "/api/v1/jobs/plan-replace",
        json={
            "path": str(graph_path),
            "node_id": "root",
            "tasks": [],
            "milestones": [{"title": "legacy milestone"}],
        },
    )
    assert response.status_code == 422
    assert "milestones" in response.text


def test_focus_and_ui_session_round_trip(tmp_path):
    graph_path = tmp_path / "graph.json"
    _write_graph(graph_path)
    client = TestClient(app)

    focus_response = client.post(
        "/api/v1/focus",
        json={
            "path": str(graph_path),
            "focus_parent_id": "root",
            "active_layer": 1,
        },
    )
    assert focus_response.status_code == 200
    assert focus_response.json()["focus_parent_id"] == "root"

    put_response = client.put(
        "/api/v1/ui-session/session-1",
        json={
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"graph": str(graph_path)},
        },
    )
    assert put_response.status_code == 200

    get_response = client.get("/api/v1/ui-session/session-1")
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["messages"][0]["content"] == "hello"
    assert payload["metadata"]["graph"] == str(graph_path)


def test_missing_graph_error_message():
    client = TestClient(app)
    response = client.get("/api/v1/graph", params={"path": "does-not-exist.json"})
    assert response.status_code == 404
    assert "smartgot run --goal" in response.json()["detail"]
