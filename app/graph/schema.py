"""
Graph schema: typed models for all nodes, edges, and the KnowledgeGraph container.

Status lifecycle:
  provisional  ->  confirmed   (via updater.py promotion rules)
  confirmed    ->  superseded  (on contradiction, preserves prior provenance)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ── Allowed vocabulary ────────────────────────────────────────────────────────

NodeType = Literal[
    "Person",
    "Role",
    "Team",
    "Project",
    "Client",
    "System",
    "Document",
    "Workflow",
    "Task",
    "Decision",
    "Risk",
    "Issue",
]

RelationshipType = Literal[
    "WORKS_ON",
    "REPORTS_TO",
    "COMMUNICATES_WITH",
    "OWNS",
    "SUPPORTS",
    "USES",
    "DEPENDS_ON",
    "APPROVES",
    "DOCUMENTS",
    "ESCALATES_TO",
    "BLOCKED_BY",
    "AFFECTS",
    "RELATED_TO",
]

NodeStatus = Literal["provisional", "confirmed", "superseded"]
EdgeStatus = Literal["provisional", "confirmed", "superseded"]
UpdateOp = Literal["upsert", "delete"]


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Node ──────────────────────────────────────────────────────────────────────

class GraphNode(BaseModel):
    id: str
    type: NodeType
    label: str
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    status: NodeStatus = "provisional"
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: list[str] = Field(
        ...,
        description="Source doc IDs or interview turn IDs that support this node.",
        min_length=1,
    )
    superseded_by: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("provenance")
    @classmethod
    def provenance_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("provenance must contain at least one source reference")
        return v


# ── Edge ──────────────────────────────────────────────────────────────────────

class GraphEdge(BaseModel):
    id: str
    type: RelationshipType
    source_id: str
    target_id: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    status: EdgeStatus = "provisional"
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: list[str] = Field(..., min_length=1)
    superseded_by: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("provenance")
    @classmethod
    def provenance_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("provenance must contain at least one source reference")
        return v


# ── Graph container ───────────────────────────────────────────────────────────

class KnowledgeGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)

    def node_ids(self) -> set[str]:
        return {n.id for n in self.nodes}

    def edge_ids(self) -> set[str]:
        return {e.id for e in self.edges}
