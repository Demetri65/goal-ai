from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from smart_got.models import BaselineQA, NodeBaseline, SMARTFields, Task

DEFAULT_GRAPH_PATH = "out/graph.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    status: JobStatus
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    graph_updated_at: Optional[str] = None


class JobEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    type: str
    status: JobStatus
    message: str
    timestamp: str = Field(default_factory=now_iso)


class GraphPathMixin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = DEFAULT_GRAPH_PATH


class GraphInitRequest(GraphPathMixin):
    goal: str
    overwrite: bool = False

    @model_validator(mode="after")
    def _ensure_goal(self) -> "GraphInitRequest":
        if not self.goal.strip():
            raise ValueError("goal is required")
        return self


class DecomposeRequest(GraphPathMixin):
    node_id: str
    target_children: int = 7
    min_children: int = 5
    max_children: int = 9


class BaselineApplyRequest(GraphPathMixin):
    node_id: str
    qa_pairs: list[BaselineQA] = Field(default_factory=list)
    smart_patch: Optional[SMARTFields] = None
    baseline: Optional[NodeBaseline] = None
    baseline_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class PlanGenerateRequest(GraphPathMixin):
    node_id: str


class NodeUpdateRequest(GraphPathMixin):
    node_id: str
    title: Optional[str] = None
    workstream: Optional[str] = None
    smart_patch: Optional[SMARTFields] = None

    @model_validator(mode="after")
    def _ensure_has_change(self) -> "NodeUpdateRequest":
        if self.title is None and self.workstream is None and self.smart_patch is None:
            raise ValueError("node update requires title, workstream, and/or smart_patch")
        return self


class NodeAddRequest(GraphPathMixin):
    parent_id: str
    title: str
    workstream: str
    smart: SMARTFields


class NodeDeleteRequest(GraphPathMixin):
    node_id: str


class PlanReplaceRequest(GraphPathMixin):
    node_id: str
    tasks: list[Task] = Field(default_factory=list)


class TaskToggleRequest(GraphPathMixin):
    node_id: str
    task_index: int
    completed: bool


class SubgoalToggleRequest(GraphPathMixin):
    node_id: str
    completed: bool


class FocusRequest(GraphPathMixin):
    focus_parent_id: str
    active_layer: Optional[int] = None


class JobAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus


class UISessionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NodeProgressView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_tasks: int
    completed_tasks: int
    check_state: str


class GraphView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: dict[str, Any]
    node_progress: dict[str, NodeProgressView]
