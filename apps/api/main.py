from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from apps.api.jobs import JobRegistry
from apps.api.session_store import load_session, save_session
from apps.api.types import (
    DEFAULT_GRAPH_PATH,
    BaselineApplyRequest,
    DecomposeRequest,
    FocusRequest,
    GraphInitRequest,
    JobAccepted,
    JobStatus,
    NodeAddRequest,
    NodeDeleteRequest,
    NodeUpdateRequest,
    PlanGenerateRequest,
    PlanReplaceRequest,
    SubgoalToggleRequest,
    TaskToggleRequest,
    UISessionPayload,
)
from smart_got import engine
from smart_got.llm import get_provider
from smart_got.store import load_graph, save_graph

app = FastAPI(title="SMART-GoT Sidecar API", version="0.1.0")
registry = JobRegistry()
PROJECT_ROOT = Path(__file__).resolve().parents[2]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


JobOperation = Callable[[Callable[[str], Awaitable[None]]], Awaitable[str | None]]


def _resolve_graph_path(path: str) -> Path:
    path_obj = Path(path).expanduser()
    if path_obj.is_absolute():
        return path_obj
    return (PROJECT_ROOT / path_obj).resolve()


def _load_graph_or_error(path: str):
    path_obj = _resolve_graph_path(path)
    if not path_obj.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Graph file not found at '{path_obj}'. Create it with "
                "`smartgot run --goal \"...\"` first."
            ),
        )
    try:
        return load_graph(path_obj)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to load graph: {exc}") from exc


def _graph_payload(graph) -> dict[str, Any]:
    return {
        "graph": graph.model_dump(mode="json"),
        "node_progress": engine.graph_progress(graph),
    }


async def _submit_graph_job(kind: str, operation: JobOperation) -> JobAccepted:
    record = await registry.submit(kind, operation)
    return JobAccepted(job_id=record.id, status=record.status)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/graph")
def get_graph(path: str = Query(DEFAULT_GRAPH_PATH)) -> dict[str, Any]:
    graph = _load_graph_or_error(path)
    return _graph_payload(graph)


@app.post("/api/v1/graph/init")
def init_graph(request: GraphInitRequest) -> dict[str, Any]:
    path_obj = _resolve_graph_path(request.path)
    if path_obj.exists() and not request.overwrite:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Graph file already exists at '{path_obj}'. "
                "Set overwrite=true to replace it."
            ),
        )
    graph = engine.init_graph(request.goal.strip())
    save_graph(graph, path_obj)
    return _graph_payload(graph)


@app.get("/api/v1/status")
def get_status(path: str = Query(DEFAULT_GRAPH_PATH)) -> dict[str, Any]:
    graph = _load_graph_or_error(path)
    summary = engine.status_summary(graph)
    summary["updated_at"] = graph.updated_at
    summary["path"] = str(_resolve_graph_path(path))
    return summary


@app.get("/api/v1/nodes/{node_id}")
def get_node(node_id: str, path: str = Query(DEFAULT_GRAPH_PATH)) -> dict[str, Any]:
    graph = _load_graph_or_error(path)
    node = graph.nodes.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")
    return {
        "node": node.model_dump(mode="json"),
        "progress": engine.node_progress(node),
    }


@app.get("/api/v1/baseline/questions")
def get_baseline_questions(node_id: str, path: str = Query(DEFAULT_GRAPH_PATH)) -> dict[str, Any]:
    graph = _load_graph_or_error(path)
    node = graph.nodes.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")
    provider = get_provider()
    context = engine.build_context(graph, node_id)
    questions = provider.baseline_questions(node, context)
    return {"node_id": node_id, "questions": [item.model_dump(mode="json") for item in questions]}


@app.post("/api/v1/jobs/decompose", response_model=JobAccepted)
async def job_decompose(request: DecomposeRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = _load_graph_or_error(request.path)
        await progress(f"decomposing node {request.node_id}")
        updated_graph, new_ids = engine.decompose_node(
            graph,
            request.node_id,
            get_provider(),
            target_children=request.target_children,
            min_children=request.min_children,
            max_children=request.max_children,
        )
        await progress(f"created {len(new_ids)} child nodes")
        save_graph(updated_graph, _resolve_graph_path(request.path))
        return updated_graph.updated_at

    return await _submit_graph_job("decompose", operation)


@app.post("/api/v1/jobs/baseline-apply", response_model=JobAccepted)
async def job_baseline_apply(request: BaselineApplyRequest) -> JobAccepted:
    async def operation(progress):
        if not request.qa_pairs and request.baseline is None:
            raise ValueError("baseline apply requires qa_pairs and/or baseline payload")
        await progress("loading graph")
        graph = _load_graph_or_error(request.path)
        await progress(f"applying baseline to {request.node_id}")
        updated_graph = engine.apply_baseline(
            graph,
            request.node_id,
            request.qa_pairs,
            smart_patch=request.smart_patch,
            baseline=request.baseline,
            baseline_notes=request.baseline_notes,
            assumptions=request.assumptions,
            constraints=request.constraints,
            unknowns=request.unknowns,
        )
        save_graph(updated_graph, _resolve_graph_path(request.path))
        return updated_graph.updated_at

    return await _submit_graph_job("baseline-apply", operation)


@app.post("/api/v1/jobs/plan-generate", response_model=JobAccepted)
async def job_plan_generate(request: PlanGenerateRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = _load_graph_or_error(request.path)
        await progress(f"generating plan for {request.node_id}")
        updated_graph = engine.plan_node(graph, request.node_id, get_provider())
        save_graph(updated_graph, _resolve_graph_path(request.path))
        return updated_graph.updated_at

    return await _submit_graph_job("plan-generate", operation)


@app.post("/api/v1/jobs/node-update", response_model=JobAccepted)
async def job_node_update(request: NodeUpdateRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = _load_graph_or_error(request.path)
        await progress(f"updating node {request.node_id}")
        updated_graph = engine.update_node(
            graph,
            node_id=request.node_id,
            title=request.title,
            workstream=request.workstream,
            smart_patch=request.smart_patch,
        )
        save_graph(updated_graph, _resolve_graph_path(request.path))
        return updated_graph.updated_at

    return await _submit_graph_job("node-update", operation)


@app.post("/api/v1/jobs/node-add", response_model=JobAccepted)
async def job_node_add(request: NodeAddRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = _load_graph_or_error(request.path)
        await progress(f"adding node under {request.parent_id}")
        updated_graph, new_id = engine.add_node(
            graph,
            parent_id=request.parent_id,
            title=request.title,
            workstream=request.workstream,
            smart=request.smart,
        )
        await progress(f"created node {new_id}")
        save_graph(updated_graph, _resolve_graph_path(request.path))
        return updated_graph.updated_at

    return await _submit_graph_job("node-add", operation)


@app.post("/api/v1/jobs/node-delete", response_model=JobAccepted)
async def job_node_delete(request: NodeDeleteRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = _load_graph_or_error(request.path)
        await progress(f"deleting node {request.node_id}")
        updated_graph = engine.delete_node(graph, request.node_id)
        save_graph(updated_graph, _resolve_graph_path(request.path))
        return updated_graph.updated_at

    return await _submit_graph_job("node-delete", operation)


@app.post("/api/v1/jobs/plan-replace", response_model=JobAccepted)
async def job_plan_replace(request: PlanReplaceRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = _load_graph_or_error(request.path)
        errors = engine.validate_plan_replacement(request.tasks)
        if errors:
            raise ValueError("; ".join(errors))
        await progress(f"replacing plan for {request.node_id}")
        updated_graph = engine.replace_plan(
            graph,
            node_id=request.node_id,
            tasks=request.tasks,
        )
        save_graph(updated_graph, _resolve_graph_path(request.path))
        return updated_graph.updated_at

    return await _submit_graph_job("plan-replace", operation)


@app.post("/api/v1/jobs/subgoal-toggle", response_model=JobAccepted)
async def job_subgoal_toggle(request: SubgoalToggleRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = _load_graph_or_error(request.path)
        await progress(
            f"setting all tasks on {request.node_id} to completed={request.completed}"
        )
        updated_graph = engine.toggle_subgoal_completion(
            graph,
            node_id=request.node_id,
            completed=request.completed,
        )
        save_graph(updated_graph, _resolve_graph_path(request.path))
        return updated_graph.updated_at

    return await _submit_graph_job("subgoal-toggle", operation)


@app.post("/api/v1/jobs/task-toggle", response_model=JobAccepted)
async def job_task_toggle(request: TaskToggleRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = _load_graph_or_error(request.path)
        await progress(
            f"setting task index {request.task_index} on {request.node_id} to completed={request.completed}"
        )
        updated_graph = engine.toggle_task_completion(
            graph,
            node_id=request.node_id,
            task_index=request.task_index,
            completed=request.completed,
        )
        save_graph(updated_graph, _resolve_graph_path(request.path))
        return updated_graph.updated_at

    return await _submit_graph_job("task-toggle", operation)


@app.post("/api/v1/focus")
def update_focus(request: FocusRequest) -> dict[str, Any]:
    graph = _load_graph_or_error(request.path)
    updated_graph = engine.set_focus(
        graph,
        focus_parent_id=request.focus_parent_id,
        active_layer=request.active_layer,
    )
    save_graph(updated_graph, _resolve_graph_path(request.path))
    return {
        "focus_parent_id": updated_graph.focus_parent_id,
        "active_layer": updated_graph.active_layer,
        "updated_at": updated_graph.updated_at,
    }


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    try:
        record = await registry.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}") from exc
    return record.model_dump(mode="json")


@app.get("/api/v1/jobs/{job_id}/events")
async def stream_job_events(job_id: str):
    try:
        await registry.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}") from exc

    async def event_stream():
        async for event in registry.iter_events(job_id):
            payload = json.dumps(event.model_dump(mode="json"))
            yield f"data: {payload}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/v1/ui-session/{session_id}")
def get_ui_session(session_id: str) -> dict[str, Any]:
    try:
        session = load_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.model_dump(mode="json")


@app.put("/api/v1/ui-session/{session_id}")
def put_ui_session(session_id: str, payload: UISessionPayload) -> dict[str, Any]:
    try:
        session = save_session(session_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.model_dump(mode="json")


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8001)
