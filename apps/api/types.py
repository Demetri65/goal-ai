from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from smart_got.models import (
    BaselineQA,
    LayoutMode,
    NodeBaseline,
    NodePosition,
    NodeStatus,
    SMARTFields,
    Task,
)

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
    sequence: int = 0
    changed_node_ids: list[str] = Field(default_factory=list)
    graph_snapshot: Optional[dict[str, Any]] = None
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


class LayerBuildRequest(GraphPathMixin):
    parent_id: str
    layer_qa_pairs: list[BaselineQA] = Field(default_factory=list)
    target_children: int = 7
    min_children: int = 5
    max_children: int = 9


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


class GraphMutationRequest(GraphPathMixin):
    action: Literal[
        "create_node",
        "update_node",
        "move_node",
        "delete_node",
        "set_position",
        "upsert_suggested_connection",
        "delete_suggested_connection",
    ]
    node_id: Optional[str] = None
    parent_id: Optional[str] = None
    source_id: Optional[str] = None
    target_id: Optional[str] = None
    label: Optional[str] = None
    rationale: Optional[str] = None
    title: Optional[str] = None
    workstream: Optional[str] = None
    smart: Optional[SMARTFields] = None
    baseline: Optional[NodeBaseline] = None
    baseline_notes: Optional[list[str]] = None
    assumptions: Optional[list[str]] = None
    constraints: Optional[list[str]] = None
    unknowns: Optional[list[str]] = None
    status: Optional[NodeStatus] = None
    position: Optional[NodePosition] = None
    layout_mode: Optional[LayoutMode] = None

    @model_validator(mode="after")
    def _validate_fields(self) -> "GraphMutationRequest":
        if self.action == "create_node":
            if self.parent_id is None:
                raise ValueError("create_node requires parent_id")
            if self.smart is None:
                raise ValueError("create_node requires smart")
            return self

        if self.action == "update_node":
            if self.node_id is None:
                raise ValueError("update_node requires node_id")
            if (
                self.title is None
                and self.workstream is None
                and self.smart is None
                and self.baseline is None
                and self.baseline_notes is None
                and self.assumptions is None
                and self.constraints is None
                and self.unknowns is None
                and self.status is None
            ):
                raise ValueError("update_node requires at least one changed field")
            return self

        if self.action == "move_node":
            if self.node_id is None or self.parent_id is None:
                raise ValueError("move_node requires node_id and parent_id")
            return self

        if self.action == "delete_node":
            if self.node_id is None:
                raise ValueError("delete_node requires node_id")
            return self

        if self.action in {"upsert_suggested_connection", "delete_suggested_connection"}:
            if self.source_id is None or self.target_id is None:
                raise ValueError(f"{self.action} requires source_id and target_id")
            if self.source_id == self.target_id:
                raise ValueError("Connection source and target must be different")
            return self

        if self.node_id is None:
            raise ValueError("set_position requires node_id")
        if self.layout_mode == LayoutMode.manual and self.position is None:
            raise ValueError("manual layout_mode requires position")
        if self.layout_mode is None and self.position is None:
            raise ValueError("set_position requires position or layout_mode")
        return self


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
    workflow: dict[str, Any]
