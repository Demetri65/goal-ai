import json
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import _load_repo_env, _parse_env_line, app
from smart_got import engine
from smart_got.llm import OPENAI_TOKEN_MISSING_MESSAGE, MockProvider
from smart_got.models import NodePlan, SMARTFields, Task
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


def _layer_answers_for(graph, parent_id: str):
    provider = MockProvider()
    answers_by_category = {
        "achievable": "6 hours/week from one coordinator",
        "time_bound": "2026-06-30",
        "resources": "2 volunteers and a permit tracker",
        "constraints": "City permit needs 4 weeks lead time",
        "unknowns": "Weather and turnout variance",
        "assumptions": "Route approval lands on first review",
    }
    questions = engine.layer_baseline_questions(graph, parent_id, provider)
    return [
        {
            "id": question.id,
            "question": question.question,
            "answer": answers_by_category.get(question.category, "Acknowledged"),
            "category": question.category,
        }
        for question in questions
    ]


def test_parse_env_line_handles_plain_exported_and_quoted_values():
    assert _parse_env_line("OPENAI_API_KEY=test-key") == ("OPENAI_API_KEY", "test-key")
    assert _parse_env_line("export SMARTGOT_LLM_MODE=mock") == ("SMARTGOT_LLM_MODE", "mock")
    assert _parse_env_line('OPENAI_API_KEY="quoted-key"') == ("OPENAI_API_KEY", "quoted-key")
    assert _parse_env_line("   # comment only") is None


def test_load_repo_env_reads_env_files_without_overriding_existing_values(tmp_path, monkeypatch):
    env_root = Path(tmp_path)
    (env_root / ".env").write_text("OPENAI_API_KEY=repo-key\nSMARTGOT_LLM_MODE=mock\n")
    (env_root / ".env.local").write_text('OPENAI_API_KEY="local-key"\nEXTRA_FLAG=enabled\n')

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SMARTGOT_LLM_MODE", raising=False)
    monkeypatch.delenv("EXTRA_FLAG", raising=False)

    _load_repo_env(env_root)

    assert os.environ["OPENAI_API_KEY"] == "repo-key"
    assert os.environ["SMARTGOT_LLM_MODE"] == "mock"
    assert os.environ["EXTRA_FLAG"] == "enabled"

    monkeypatch.setenv("OPENAI_API_KEY", "shell-key")
    _load_repo_env(env_root)
    assert os.environ["OPENAI_API_KEY"] == "shell-key"


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
    assert "workflow" in graph_payload

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
    questions = baseline_response.json()["questions"]
    assert 4 <= len(questions) <= 8
    assert all(item["guide"] for item in questions)
    assert all(item["research_basis"] for item in questions)


def test_baseline_questions_requires_openai_token(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SMARTGOT_LLM_MODE", raising=False)
    graph_path = tmp_path / "graph.json"
    _write_graph(graph_path)

    client = TestClient(app)
    response = client.get(
        "/api/v1/baseline/questions",
        params={"path": str(graph_path), "node_id": "root"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == OPENAI_TOKEN_MISSING_MESSAGE


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
    snapshot_events: list[dict[str, object]] = []
    with client.stream("GET", f"/api/v1/jobs/{job_id}/events") as stream_response:
        assert stream_response.status_code == 200
        for line in stream_response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = json.loads(line.removeprefix("data: "))
            event_types.append(payload["type"])
            if payload.get("graph_snapshot"):
                snapshot_events.append(payload)
            if payload["type"] in {"completed", "failed"}:
                break

    job_payload = _wait_for_job(client, job_id)
    assert job_payload["status"] == "succeeded"
    assert event_types[0] == "queued"
    assert "running" in event_types
    assert "completed" in event_types
    assert snapshot_events
    assert snapshot_events[0]["sequence"] > 0
    assert snapshot_events[0]["changed_node_ids"]
    assert snapshot_events[0]["graph_snapshot"]["graph"]["nodes"]

    graph = load_graph(graph_path)
    titles = {node.title for node in graph.nodes.values()}
    assert "New child" in titles


def test_layer_build_job_builds_and_plans_current_layer(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTGOT_LLM_MODE", "mock")
    graph_path = tmp_path / "graph.json"
    graph = engine.init_graph("Web API layer build")
    save_graph(graph, graph_path)
    client = TestClient(app)

    response = client.post(
        "/api/v1/jobs/layer-build",
        json={
            "path": str(graph_path),
            "parent_id": "root",
            "layer_qa_pairs": _layer_answers_for(graph, "root"),
            "target_children": 7,
            "min_children": 5,
            "max_children": 9,
        },
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    snapshot_events: list[dict[str, object]] = []
    with client.stream("GET", f"/api/v1/jobs/{job_id}/events") as stream_response:
        assert stream_response.status_code == 200
        for line in stream_response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = json.loads(line.removeprefix("data: "))
            if payload.get("graph_snapshot"):
                snapshot_events.append(payload)
            if payload["type"] in {"completed", "failed"}:
                break

    job_status = _wait_for_job(client, job_id)
    assert job_status["status"] == "succeeded"

    built_graph = load_graph(graph_path)
    child_ids = engine.layer_children(built_graph, "root")
    assert child_ids
    assert all(built_graph.nodes[child_id].status == "PLANNED" for child_id in child_ids)
    assert snapshot_events
    sequences = [event["sequence"] for event in snapshot_events]
    assert sequences == sorted(sequences)
    creation_events = snapshot_events[: len(child_ids)]
    assert [event["changed_node_ids"][0] for event in creation_events] == child_ids
    assert built_graph.suggested_connections
    title_by_id = {child_id: built_graph.nodes[child_id].title for child_id in child_ids}
    connection_pairs = {
        (title_by_id[item.source_id], title_by_id[item.target_id])
        for item in built_graph.suggested_connections
        if item.source_id in title_by_id and item.target_id in title_by_id
    }
    assert ("Define Scope and Success", "Plan Resource Coverage") in connection_pairs


def test_decompose_job_streams_children_and_suggested_connections(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTGOT_LLM_MODE", "mock")
    graph_path = tmp_path / "graph.json"
    graph = engine.init_graph("Web API streamed decompose")
    save_graph(graph, graph_path)
    client = TestClient(app)

    response = client.post(
        "/api/v1/jobs/decompose",
        json={
            "path": str(graph_path),
            "node_id": "root",
            "target_children": 7,
            "min_children": 5,
            "max_children": 9,
        },
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    snapshot_events: list[dict[str, object]] = []
    with client.stream("GET", f"/api/v1/jobs/{job_id}/events") as stream_response:
        assert stream_response.status_code == 200
        for line in stream_response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = json.loads(line.removeprefix("data: "))
            if payload.get("graph_snapshot"):
                snapshot_events.append(payload)
            if payload["type"] in {"completed", "failed"}:
                break

    job_status = _wait_for_job(client, job_id)
    assert job_status["status"] == "succeeded"

    streamed_graph = load_graph(graph_path)
    child_ids = engine.layer_children(streamed_graph, "root")
    assert child_ids
    assert [
        event["changed_node_ids"][0] for event in snapshot_events[: len(child_ids)]
    ] == child_ids
    assert streamed_graph.suggested_connections
    title_by_id = {child_id: streamed_graph.nodes[child_id].title for child_id in child_ids}
    connection_pairs = {
        (title_by_id[item.source_id], title_by_id[item.target_id])
        for item in streamed_graph.suggested_connections
        if item.source_id in title_by_id and item.target_id in title_by_id
    }
    assert ("Define Scope and Success", "Plan Resource Coverage") in connection_pairs


def test_graph_mutation_endpoint_round_trip(tmp_path):
    graph_path = tmp_path / "graph.json"
    _write_graph(graph_path)
    client = TestClient(app)

    create_response = client.post(
        "/api/v1/graph/mutate",
        json={
            "path": str(graph_path),
            "action": "create_node",
            "parent_id": "root",
            "title": "Canvas node",
            "workstream": "New",
            "smart": {
                "specific": "Ship change",
                "measurable": "Merged",
                "achievable": "",
                "relevant": "Supports root",
                "time_bound": "",
            },
            "position": {"x": 320, "y": 180},
            "layout_mode": "manual",
        },
    )
    assert create_response.status_code == 200
    created_graph = create_response.json()["graph"]
    created_id = next(
        node_id
        for node_id, node in created_graph["nodes"].items()
        if node["title"] == "Canvas node"
    )
    assert created_graph["nodes"][created_id]["ui"]["layout_mode"] == "manual"
    assert created_graph["nodes"][created_id]["suggested_parent_id"] == "root"
    assert created_graph["nodes"][created_id]["suggested_path_ids"] == ["root", created_id]

    update_response = client.post(
        "/api/v1/graph/mutate",
        json={
            "path": str(graph_path),
            "action": "update_node",
            "node_id": created_id,
            "title": "Canvas node updated",
            "smart": {
                "specific": "Ship change",
                "measurable": "Merged",
                "achievable": "1 engineer",
                "relevant": "Supports root",
                "time_bound": "This week",
            },
            "status": "BASELINED",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["graph"]["nodes"][created_id]["title"] == "Canvas node updated"

    move_response = client.post(
        "/api/v1/graph/mutate",
        json={
            "path": str(graph_path),
            "action": "move_node",
            "node_id": created_id,
            "parent_id": "n1",
        },
    )
    assert move_response.status_code == 200
    assert move_response.json()["graph"]["nodes"][created_id]["parent_id"] == "n1"
    assert move_response.json()["graph"]["nodes"][created_id]["suggested_parent_id"] == "root"
    assert move_response.json()["graph"]["nodes"][created_id]["suggested_path_ids"] == [
        "root",
        created_id,
    ]

    reset_position_response = client.post(
        "/api/v1/graph/mutate",
        json={
            "path": str(graph_path),
            "action": "set_position",
            "node_id": created_id,
            "layout_mode": "auto",
        },
    )
    assert reset_position_response.status_code == 200
    assert (
        reset_position_response.json()["graph"]["nodes"][created_id]["ui"]["layout_mode"] == "auto"
    )

    delete_response = client.post(
        "/api/v1/graph/mutate",
        json={
            "path": str(graph_path),
            "action": "delete_node",
            "node_id": created_id,
        },
    )
    assert delete_response.status_code == 200
    assert created_id not in delete_response.json()["graph"]["nodes"]


def test_graph_mutation_endpoint_allows_blank_title_nodes(tmp_path):
    graph_path = tmp_path / "graph.json"
    _write_graph(graph_path)
    client = TestClient(app)

    response = client.post(
        "/api/v1/graph/mutate",
        json={
            "path": str(graph_path),
            "action": "create_node",
            "parent_id": "root",
            "title": "",
            "workstream": "General",
            "smart": {
                "specific": "",
                "measurable": "",
                "achievable": "",
                "relevant": "",
                "time_bound": "",
            },
            "status": "DRAFT",
        },
    )

    assert response.status_code == 200
    graph_payload = response.json()["graph"]
    blank_nodes = [node for node in graph_payload["nodes"].values() if node["parent_id"] == "root"]
    assert any(node["title"] == "" and node["status"] == "DRAFT" for node in blank_nodes)


def test_generation_jobs_fail_without_openai_token(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SMARTGOT_LLM_MODE", raising=False)
    graph_path = tmp_path / "graph.json"
    graph = engine.init_graph("Web API failure case")
    save_graph(graph, graph_path)
    client = TestClient(app)

    decompose_response = client.post(
        "/api/v1/jobs/decompose",
        json={
            "path": str(graph_path),
            "node_id": "root",
            "target_children": 7,
            "min_children": 5,
            "max_children": 9,
        },
    )
    assert decompose_response.status_code == 200
    decompose_status = _wait_for_job(client, decompose_response.json()["job_id"])
    assert decompose_status["status"] == "failed"
    assert decompose_status["error"] == OPENAI_TOKEN_MISSING_MESSAGE

    layer_build_response = client.post(
        "/api/v1/jobs/layer-build",
        json={
            "path": str(graph_path),
            "parent_id": "root",
            "layer_qa_pairs": [],
            "target_children": 7,
            "min_children": 5,
            "max_children": 9,
        },
    )
    assert layer_build_response.status_code == 200
    layer_build_status = _wait_for_job(client, layer_build_response.json()["job_id"])
    assert layer_build_status["status"] == "failed"
    assert layer_build_status["error"] == OPENAI_TOKEN_MISSING_MESSAGE

    graph = engine.init_graph("Web API plan failure")
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
    save_graph(graph, graph_path)

    plan_response = client.post(
        "/api/v1/jobs/plan-generate",
        json={
            "path": str(graph_path),
            "node_id": child_id,
        },
    )
    assert plan_response.status_code == 200
    plan_status = _wait_for_job(client, plan_response.json()["job_id"])
    assert plan_status["status"] == "failed"
    assert plan_status["error"] == OPENAI_TOKEN_MISSING_MESSAGE


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
    assert "POST /api/v1/graph/init" in response.json()["detail"]
