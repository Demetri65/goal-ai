from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class NodeStatus(str, Enum):
    DRAFT = "DRAFT"
    BASELINED = "BASELINED"


class SMARTFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specific: str = ""
    measurable: str = ""
    achievable: str = ""
    relevant: str = ""
    time_bound: str = ""


class BaselineQA(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str = ""


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    layer: int
    parent_id: Optional[str] = None
    children_ids: list[str] = Field(default_factory=list)
    smart: SMARTFields
    baseline: list[BaselineQA] = Field(default_factory=list)
    status: NodeStatus = NodeStatus.DRAFT


class Graph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_id: str
    nodes: dict[str, Node]
    created_at: str
    updated_at: str


class ChildDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    smart: SMARTFields
