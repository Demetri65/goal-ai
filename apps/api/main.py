from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse

from apps.api.jobs import JobRegistry
from apps.api.session_store import load_session, save_session
from apps.api.types import (
    DEFAULT_GRAPH_PATH,
    BaselineApplyRequest,
    DecomposeRequest,
    FocusRequest,
    GraphInitRequest,
    GraphMutationRequest,
    JobAccepted,
    LayerBuildRequest,
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
from smart_got.store import graph_exists, load_graph, save_graph

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return key, value


def _load_repo_env(project_root: Path = PROJECT_ROOT) -> None:
    for filename in (".env", ".env.local"):
        env_path = project_root / filename
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text().splitlines():
            parsed = _parse_env_line(raw_line)
            if parsed is None:
                continue
            key, value = parsed
            os.environ.setdefault(key, value)


_load_repo_env()

app = FastAPI(title="SMART-GoT Sidecar API", version="0.1.0")
registry = JobRegistry()


def _split_env_list(name: str) -> list[str]:
    return [item.strip().rstrip("/") for item in os.getenv(name, "").split(",") if item.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        *_split_env_list("SMARTGOT_CORS_ORIGINS"),
    ],
    allow_origin_regex=(
        os.getenv("SMARTGOT_CORS_ORIGIN_REGEX")
        or r"^(https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?|https://[a-z0-9-]+\.vercel\.app)$"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


JobOperation = Callable[[Callable[[str], Awaitable[None]]], Awaitable[str | None]]


def _resolve_graph_path(path: str) -> Path:
    path_obj = Path(path).expanduser()
    if path_obj.is_absolute():
        return path_obj
    if os.getenv("VERCEL"):
        return (Path("/tmp/smartgot") / path_obj).resolve()
    return (PROJECT_ROOT / path_obj).resolve()


def _load_graph_or_error(path: str):
    path_obj = _resolve_graph_path(path)
    if not graph_exists(path_obj):
        raise HTTPException(
            status_code=404,
            detail=(
                f"Graph file not found at '{path_obj}'. Create it with "
                "`POST /api/v1/graph/init` first."
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
        "workflow": engine.workflow_snapshot(graph),
    }


async def _emit_graph_progress(
    progress,
    message: str,
    before_graph,
    after_graph,
    *,
    changed_node_ids: list[str] | None = None,
) -> None:
    await progress(
        message,
        changed_node_ids=changed_node_ids or engine.changed_node_ids(before_graph, after_graph),
        graph_snapshot=_graph_payload(after_graph),
    )


async def _stream_draft_children(
    progress,
    graph,
    parent_id: str,
    drafts,
    path: str,
) -> tuple[Any, list[str]]:
    child_ids: list[str] = []
    for draft in drafts:
        before_graph = graph
        graph, node_id = await asyncio.to_thread(
            engine.add_node,
            graph,
            parent_id,
            draft.title,
            draft.workstream,
            draft.smart,
            engine.NodeStatus.DRAFT,
        )
        child_ids.append(node_id)
        graph = await asyncio.to_thread(
            engine.sync_suggested_connections_for_drafts,
            graph,
            drafts,
            child_ids,
        )
        await asyncio.to_thread(save_graph, graph, _resolve_graph_path(path))
        await _emit_graph_progress(
            progress,
            f"created node {node_id}",
            before_graph,
            graph,
            changed_node_ids=[node_id],
        )
    return graph, child_ids


def _get_provider_or_http_error():
    try:
        return get_provider()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _submit_graph_job(kind: str, operation: JobOperation) -> JobAccepted:
    record = await registry.submit(kind, operation)
    return JobAccepted(job_id=record.id, status=record.status)


@app.get("/")
def root():
    web_url = os.getenv("SMARTGOT_WEB_URL", "").strip()
    if web_url:
        return RedirectResponse(web_url, status_code=307)

    return {
        "status": "ok",
        "service": "SMART-GoT API",
        "health": "/health",
        "app": "Set SMARTGOT_WEB_URL to redirect this route to the web app.",
    }


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
    if graph_exists(path_obj) and not request.overwrite:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Graph file already exists at '{path_obj}'. Set overwrite=true to replace it."
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
    try:
        provider = _get_provider_or_http_error()
        context = engine.build_context(graph, node_id)
        questions = provider.baseline_questions(node, context)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"node_id": node_id, "questions": [item.model_dump(mode="json") for item in questions]}


@app.post("/api/v1/jobs/decompose", response_model=JobAccepted)
async def job_decompose(request: DecomposeRequest) -> JobAccepted:
    async def operation(progress):
        provider = get_provider()
        await progress("loading graph")
        graph = await asyncio.to_thread(_load_graph_or_error, request.path)
        await progress(f"decomposing node {request.node_id}")
        drafts = await asyncio.to_thread(
            engine.draft_children_for_node,
            graph,
            request.node_id,
            provider,
            target_children=request.target_children,
            min_children=request.min_children,
            max_children=request.max_children,
        )
        graph, _ = await _stream_draft_children(
            progress,
            graph,
            request.node_id,
            drafts,
            request.path,
        )
        return graph.updated_at

    return await _submit_graph_job("decompose", operation)


@app.post("/api/v1/jobs/layer-build", response_model=JobAccepted)
async def job_layer_build(request: LayerBuildRequest) -> JobAccepted:
    async def operation(progress):
        provider = get_provider()
        await progress("loading graph")
        graph = await asyncio.to_thread(_load_graph_or_error, request.path)
        await progress(f"building layer for parent {request.parent_id}")
        if not engine.layer_children(graph, request.parent_id):
            drafts = await asyncio.to_thread(
                engine.draft_children_for_node,
                graph,
                request.parent_id,
                provider,
                target_children=request.target_children,
                min_children=request.min_children,
                max_children=request.max_children,
            )
            graph, _ = await _stream_draft_children(
                progress,
                graph,
                request.parent_id,
                drafts,
                request.path,
            )

        draft_ids = engine.layer_draft_ids(graph, request.parent_id)
        if draft_ids:
            await progress(f"applying layer baseline to {len(draft_ids)} nodes")
        for child_id in draft_ids:
            node = graph.nodes[child_id]
            context = engine.build_context(graph, child_id)
            node_questions = provider.baseline_questions(node, context)
            qa_pairs = engine.map_layer_answers_to_node(request.layer_qa_pairs, node_questions)
            before_graph = graph
            graph, _ = await asyncio.to_thread(
                engine.apply_baseline_answers,
                graph,
                child_id,
                provider,
                qa_pairs,
            )
            await asyncio.to_thread(save_graph, graph, _resolve_graph_path(request.path))
            await _emit_graph_progress(
                progress,
                f"baselined node {child_id}",
                before_graph,
                graph,
                changed_node_ids=engine.changed_node_ids(before_graph, graph),
            )

        pending_ids = engine.layer_pending_plan_ids(graph, request.parent_id)
        if pending_ids:
            await progress(f"planning {len(pending_ids)} nodes")
        for child_id in pending_ids:
            before_graph = graph
            graph = await asyncio.to_thread(engine.plan_node, graph, child_id, provider)
            await asyncio.to_thread(save_graph, graph, _resolve_graph_path(request.path))
            await _emit_graph_progress(
                progress,
                f"planned node {child_id}",
                before_graph,
                graph,
                changed_node_ids=[child_id],
            )
        return graph.updated_at

    return await _submit_graph_job("layer-build", operation)


@app.post("/api/v1/jobs/baseline-apply", response_model=JobAccepted)
async def job_baseline_apply(request: BaselineApplyRequest) -> JobAccepted:
    async def operation(progress):
        if not request.qa_pairs and request.baseline is None:
            raise ValueError("baseline apply requires qa_pairs and/or baseline payload")
        await progress("loading graph")
        graph = await asyncio.to_thread(_load_graph_or_error, request.path)
        await progress(f"applying baseline to {request.node_id}")
        before_graph = graph
        updated_graph = await asyncio.to_thread(
            lambda: engine.apply_baseline(
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
        )
        await asyncio.to_thread(save_graph, updated_graph, _resolve_graph_path(request.path))
        await _emit_graph_progress(
            progress,
            f"updated node {request.node_id}",
            before_graph,
            updated_graph,
            changed_node_ids=engine.changed_node_ids(before_graph, updated_graph),
        )
        return updated_graph.updated_at

    return await _submit_graph_job("baseline-apply", operation)


@app.post("/api/v1/jobs/plan-generate", response_model=JobAccepted)
async def job_plan_generate(request: PlanGenerateRequest) -> JobAccepted:
    async def operation(progress):
        provider = get_provider()
        await progress("loading graph")
        graph = await asyncio.to_thread(_load_graph_or_error, request.path)
        await progress(f"generating plan for {request.node_id}")
        before_graph = graph
        updated_graph = await asyncio.to_thread(engine.plan_node, graph, request.node_id, provider)
        await asyncio.to_thread(save_graph, updated_graph, _resolve_graph_path(request.path))
        await _emit_graph_progress(
            progress,
            f"planned node {request.node_id}",
            before_graph,
            updated_graph,
            changed_node_ids=[request.node_id],
        )
        return updated_graph.updated_at

    return await _submit_graph_job("plan-generate", operation)


@app.post("/api/v1/jobs/node-update", response_model=JobAccepted)
async def job_node_update(request: NodeUpdateRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = await asyncio.to_thread(_load_graph_or_error, request.path)
        await progress(f"updating node {request.node_id}")
        before_graph = graph
        updated_graph = await asyncio.to_thread(
            engine.update_node,
            graph,
            request.node_id,
            request.title,
            request.workstream,
            None,
            request.smart_patch,
        )
        await asyncio.to_thread(save_graph, updated_graph, _resolve_graph_path(request.path))
        await _emit_graph_progress(
            progress,
            f"updated node {request.node_id}",
            before_graph,
            updated_graph,
            changed_node_ids=[request.node_id],
        )
        return updated_graph.updated_at

    return await _submit_graph_job("node-update", operation)


@app.post("/api/v1/jobs/node-add", response_model=JobAccepted)
async def job_node_add(request: NodeAddRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = await asyncio.to_thread(_load_graph_or_error, request.path)
        await progress(f"adding node under {request.parent_id}")
        before_graph = graph
        updated_graph, new_id = await asyncio.to_thread(
            engine.add_node,
            graph,
            request.parent_id,
            request.title,
            request.workstream,
            request.smart,
        )
        await asyncio.to_thread(save_graph, updated_graph, _resolve_graph_path(request.path))
        await _emit_graph_progress(
            progress,
            f"created node {new_id}",
            before_graph,
            updated_graph,
            changed_node_ids=[new_id],
        )
        return updated_graph.updated_at

    return await _submit_graph_job("node-add", operation)


@app.post("/api/v1/jobs/node-delete", response_model=JobAccepted)
async def job_node_delete(request: NodeDeleteRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = await asyncio.to_thread(_load_graph_or_error, request.path)
        await progress(f"deleting node {request.node_id}")
        before_graph = graph
        updated_graph = await asyncio.to_thread(engine.delete_node, graph, request.node_id)
        await asyncio.to_thread(save_graph, updated_graph, _resolve_graph_path(request.path))
        await _emit_graph_progress(
            progress,
            f"deleted node {request.node_id}",
            before_graph,
            updated_graph,
            changed_node_ids=engine.changed_node_ids(before_graph, updated_graph),
        )
        return updated_graph.updated_at

    return await _submit_graph_job("node-delete", operation)


@app.post("/api/v1/jobs/plan-replace", response_model=JobAccepted)
async def job_plan_replace(request: PlanReplaceRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = await asyncio.to_thread(_load_graph_or_error, request.path)
        errors = await asyncio.to_thread(engine.validate_plan_replacement, request.tasks)
        if errors:
            raise ValueError("; ".join(errors))
        await progress(f"replacing plan for {request.node_id}")
        before_graph = graph
        updated_graph = await asyncio.to_thread(
            engine.replace_plan,
            graph,
            request.node_id,
            request.tasks,
        )
        await asyncio.to_thread(save_graph, updated_graph, _resolve_graph_path(request.path))
        await _emit_graph_progress(
            progress,
            f"updated plan for {request.node_id}",
            before_graph,
            updated_graph,
            changed_node_ids=[request.node_id],
        )
        return updated_graph.updated_at

    return await _submit_graph_job("plan-replace", operation)


@app.post("/api/v1/jobs/subgoal-toggle", response_model=JobAccepted)
async def job_subgoal_toggle(request: SubgoalToggleRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = await asyncio.to_thread(_load_graph_or_error, request.path)
        await progress(f"setting all tasks on {request.node_id} to completed={request.completed}")
        before_graph = graph
        updated_graph = await asyncio.to_thread(
            engine.toggle_subgoal_completion,
            graph,
            request.node_id,
            request.completed,
        )
        await asyncio.to_thread(save_graph, updated_graph, _resolve_graph_path(request.path))
        await _emit_graph_progress(
            progress,
            f"updated tasks for {request.node_id}",
            before_graph,
            updated_graph,
            changed_node_ids=[request.node_id],
        )
        return updated_graph.updated_at

    return await _submit_graph_job("subgoal-toggle", operation)


@app.post("/api/v1/jobs/task-toggle", response_model=JobAccepted)
async def job_task_toggle(request: TaskToggleRequest) -> JobAccepted:
    async def operation(progress):
        await progress("loading graph")
        graph = await asyncio.to_thread(_load_graph_or_error, request.path)
        message = (
            f"setting task index {request.task_index} on "
            f"{request.node_id} to completed={request.completed}"
        )
        await progress(message)
        before_graph = graph
        updated_graph = await asyncio.to_thread(
            engine.toggle_task_completion,
            graph,
            request.node_id,
            request.task_index,
            request.completed,
        )
        await asyncio.to_thread(save_graph, updated_graph, _resolve_graph_path(request.path))
        await _emit_graph_progress(
            progress,
            f"updated task {request.task_index} for {request.node_id}",
            before_graph,
            updated_graph,
            changed_node_ids=[request.node_id],
        )
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


@app.post("/api/v1/graph/mutate")
def mutate_graph(request: GraphMutationRequest) -> dict[str, Any]:
    graph = _load_graph_or_error(request.path)

    if request.action == "create_node":
        updated_graph, node_id = engine.add_node(
            graph,
            parent_id=request.parent_id or graph.root_id,
            title=(request.title or "").strip(),
            workstream=request.workstream or "General",
            smart=request.smart or engine.SMARTFields(),
            status=request.status or engine.NodeStatus.BASELINED,
            baseline=request.baseline,
        )
        if request.position is not None or request.layout_mode is not None:
            updated_graph = engine.set_node_position(
                updated_graph,
                node_id,
                request.position,
                request.layout_mode,
            )
    elif request.action == "update_node":
        updated_graph = engine.update_node(
            graph,
            request.node_id or "",
            title=request.title,
            workstream=request.workstream,
            smart=request.smart,
            baseline=request.baseline,
            baseline_notes=request.baseline_notes,
            assumptions=request.assumptions,
            constraints=request.constraints,
            unknowns=request.unknowns,
            status=request.status,
        )
    elif request.action == "move_node":
        updated_graph = engine.move_node(
            graph,
            request.node_id or "",
            request.parent_id or "",
        )
    elif request.action == "delete_node":
        updated_graph = engine.delete_node(graph, request.node_id or "")
    elif request.action == "upsert_suggested_connection":
        updated_graph = engine.upsert_suggested_connection(
            graph,
            request.source_id or "",
            request.target_id or "",
            label=request.label or "",
            rationale=request.rationale or "",
        )
    elif request.action == "delete_suggested_connection":
        updated_graph = engine.delete_suggested_connection(
            graph,
            request.source_id or "",
            request.target_id or "",
        )
    else:
        updated_graph = engine.set_node_position(
            graph,
            request.node_id or "",
            request.position,
            request.layout_mode,
        )

    save_graph(updated_graph, _resolve_graph_path(request.path))
    return _graph_payload(updated_graph)


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
