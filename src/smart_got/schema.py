from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


NodeType = Literal["goal"]
NodeStatus = Literal["draft", "proposed", "accepted", "rejected", "deprecated"]
Provenance = Literal["user", "llm", "tool"]
EdgeType = Literal["subgoal_of"]
GateStatus = Literal["pending", "approved"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SmrMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    unit: str = ""
    method: str = ""
    target_value: float | int | None = None


class SmrData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specific_text: str | None = None
    rationale: str = ""
    metric: SmrMetric = Field(default_factory=SmrMetric)
    forcing_questions: list[str] = Field(default_factory=list)


class BaselineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = ""
    unit: str = ""
    value: int | float | str | None = None
    source: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    timestamp: str | None = None


class ConstraintEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str | None = None
    text: str = ""


class PlanData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[str] = Field(default_factory=list)
    if_then: list[str] = Field(default_factory=list)
    milestones: list[str] | None = None
    time_bound_weeks: int | None = Field(default=None, ge=1)
    assumptions: list[str] | None = None
    notes: list[str] | None = None


class ResourceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    text: str = ""
    link: str | None = None


class DecisionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_options: list[str] = Field(default_factory=list)
    chosen_plan_id: str | None = None


class EvalData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float | None = Field(default=None, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    rubric: dict[str, Any] | None = None
    last_updated: str | None = None


class GoalNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    smr: SmrData = Field(default_factory=SmrData)
    baseline: dict[str, BaselineEntry] = Field(default_factory=dict)
    constraints: list[ConstraintEntry] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    plan: PlanData = Field(default_factory=PlanData)
    resources: list[ResourceEntry] = Field(default_factory=list)
    review_prompts: list[str] = Field(default_factory=list)
    decision: DecisionData = Field(default_factory=DecisionData)
    eval: EvalData = Field(default_factory=EvalData)


class Node(BaseModel):
    id: str
    type: NodeType
    stage: int = Field(ge=1, le=4)
    status: NodeStatus = "draft"
    text: str = ""
    data: GoalNodeData = Field(default_factory=GoalNodeData)
    provenance: Provenance = "llm"
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def touch(self) -> None:
        self.updated_at = utcnow()


class Edge(BaseModel):
    src: str
    dst: str
    type: EdgeType


class RevisionEvent(BaseModel):
    ts: datetime = Field(default_factory=utcnow)
    kind: str
    detail: dict[str, Any] = Field(default_factory=dict)


class StageGate(BaseModel):
    stage: int = Field(ge=1, le=4)
    status: GateStatus = "pending"
    approved_at: Optional[datetime] = None
    note: str = ""


class Graph(BaseModel):
    nodes: dict[str, Node] = Field(default_factory=dict)
    edges: list[Edge] = Field(default_factory=list)
    revisions: list[RevisionEvent] = Field(default_factory=list)
    gates: list[StageGate] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node
        self.revisions.append(RevisionEvent(kind="add_node", detail={"id": node.id, "type": node.type}))

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)
        self.revisions.append(RevisionEvent(kind="add_edge", detail=edge.model_dump()))

    def get_nodes(self, node_type: NodeType, status: Optional[NodeStatus] = None) -> list[Node]:
        out = [n for n in self.nodes.values() if n.type == node_type]
        if status is not None:
            out = [n for n in out if n.status == status]
        return out

    def root_goal_id(self) -> str:
        value = self.meta.get("root_goal_id", "goal.v1")
        return value if isinstance(value, str) and value else "goal.v1"

    def root_goal(self) -> Optional[Node]:
        return self.nodes.get(self.root_goal_id())

    def upsert_gate(self, stage: int) -> StageGate:
        for g in self.gates:
            if g.stage == stage:
                return g
        g = StageGate(stage=stage)
        self.gates.append(g)
        return g

    def gate(self, stage: int) -> Optional[StageGate]:
        for g in self.gates:
            if g.stage == stage:
                return g
        return None
