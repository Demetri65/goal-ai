from __future__ import annotations

from enum import Enum
from typing import Optional, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NodeStatus(str, Enum):
    DRAFT = "DRAFT"
    BASELINED = "BASELINED"
    PLANNED = "PLANNED"


class CheckState(str, Enum):
    unchecked = "unchecked"
    partial = "partial"
    checked = "checked"


class SMARTFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specific: str = ""
    measurable: str = ""
    achievable: str = ""
    relevant: str = ""
    time_bound: str = ""


class BaselineQA(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    question: str
    answer: str = ""
    category: str


class BaselineQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    category: str


class NodeBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qa: list[BaselineQA] = Field(default_factory=list)
    baseline_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str = ""
    success_criteria: str = ""
    depends_on: list[str] = Field(default_factory=list)
    estimate_hours: Optional[float] = None
    relative_timing: Optional[str] = None
    due: Optional[str] = None
    completed: bool = False


class NodePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[Task] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _drop_legacy_milestones(cls, data: object) -> object:
        if isinstance(data, dict) and "milestones" in data:
            data = dict(data)
            data.pop("milestones", None)
        return data


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    workstream: str = "General"
    layer: int
    parent_id: Optional[str] = None
    children_ids: list[str] = Field(default_factory=list)
    smart: SMARTFields
    baseline: Optional[NodeBaseline] = None
    plan: Optional[NodePlan] = None
    status: NodeStatus = NodeStatus.DRAFT

    @model_validator(mode="before")
    @classmethod
    def _coerce_baseline(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if not data.get("workstream"):
            data["workstream"] = "Goal" if data.get("parent_id") is None else "General"
        baseline = data.get("baseline")
        if isinstance(baseline, list):
            qa_items: list[BaselineQA] = []
            for item in baseline:
                if isinstance(item, BaselineQA):
                    qa_items.append(item)
                elif isinstance(item, dict):
                    qa_items.append(
                        BaselineQA(
                            question=item.get("question", ""),
                            answer=item.get("answer", ""),
                            category=item.get("category", "uncategorized"),
                        )
                    )
            data["baseline"] = NodeBaseline(qa=qa_items)
        return data


class Graph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_id: str
    nodes: dict[str, Node]
    created_at: str
    updated_at: str
    focus_parent_id: str = ""
    active_layer: int = 0

    @model_validator(mode="after")
    def _ensure_focus_fields(self) -> "Graph":
        if not self.focus_parent_id:
            self.focus_parent_id = self.root_id
        if self.active_layer <= 0:
            focus_node = self.nodes.get(self.focus_parent_id)
            self.active_layer = (focus_node.layer + 1) if focus_node else 1
        return self


class ChildDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    workstream: str
    smart: SMARTFields


class UpdateNodeMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    title: Optional[str] = None
    smart_patch: Optional[SMARTFields] = None

    @model_validator(mode="after")
    def _ensure_has_change(self) -> "UpdateNodeMutation":
        if self.title is None and self.smart_patch is None:
            raise ValueError("UpdateNodeMutation requires title and/or smart_patch.")
        return self


class AddSiblingMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_id: str
    title: str
    workstream: str
    smart: SMARTFields


class DeleteNodeMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str


Mutation: TypeAlias = UpdateNodeMutation | AddSiblingMutation | DeleteNodeMutation


class BaselineApplyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    smart_patch: SMARTFields
    baseline: NodeBaseline
    layer_mutations: list[Mutation] = Field(default_factory=list)
    rationale: str


class PlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    smart_patch: SMARTFields = Field(default_factory=SMARTFields)
    plan: NodePlan
