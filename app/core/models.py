"""
Core models: interview turns, agent I/O contracts, and SharedInterviewState.

Design rules enforced here:
  - Agents receive slices of state, never the full SharedInterviewState.
  - proposed_updates is separate from graph; only updater.py may promote items.
  - Every CandidateEntity carries is_ambiguous + possible_matches so the LLM
    can signal fuzzy resolution needs without complex Python string-matching.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.graph.schema import (
    EdgeStatus,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NodeStatus,
    NodeType,
    RelationshipType,
    UpdateOp,
)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _turn_id() -> str:
    return f"turn_{uuid4().hex[:8]}"


def _q_id() -> str:
    return f"q_{uuid4().hex[:8]}"


def _amb_id() -> str:
    return f"amb_{uuid4().hex[:8]}"


def _upd_id() -> str:
    return f"upd_{uuid4().hex[:8]}"


def _sess_id() -> str:
    return f"sess_{uuid4().hex[:8]}"


# ── Shared vocabulary ─────────────────────────────────────────────────────────

ClarificationPriority = Literal["high", "medium", "low"]

ClarificationKind = Literal[
    "ambiguous_entity",
    "vague_predicate",
    "unclear_ownership",
    "missing_artifact_identity",
    "insufficient_coverage",
]


# ── Interview participants ─────────────────────────────────────────────────────

class Interviewee(BaseModel):
    name: str
    role: str
    project_ids: list[str]


# ── Interview turn ─────────────────────────────────────────────────────────────

class InterviewTurn(BaseModel):
    turn_id: str = Field(default_factory=_turn_id)
    turn_number: int = Field(ge=1)
    question: str
    question_rationale: str
    answer: str
    timestamp: datetime = Field(default_factory=_utcnow)


# ── Open questions and ambiguities ────────────────────────────────────────────

class OpenQuestion(BaseModel):
    question_id: str = Field(default_factory=_q_id)
    text: str
    rationale: str
    target_category: str
    priority: ClarificationPriority = "medium"


class Ambiguity(BaseModel):
    ambiguity_id: str = Field(default_factory=_amb_id)
    kind: ClarificationKind
    target: str
    reason: str
    suggested_question: str
    priority: ClarificationPriority
    source_turn_id: str
    resolved: bool = False


# ── Coverage scores ───────────────────────────────────────────────────────────

class CoverageScores(BaseModel):
    people: float = Field(0.0, ge=0.0, le=1.0)
    systems: float = Field(0.0, ge=0.0, le=1.0)
    workflows: float = Field(0.0, ge=0.0, le=1.0)
    stakeholders: float = Field(0.0, ge=0.0, le=1.0)
    risks: float = Field(0.0, ge=0.0, le=1.0)
    undocumented_knowledge: float = Field(0.0, ge=0.0, le=1.0)


# ── Agent output: Entity extraction ───────────────────────────────────────────

class PossibleMatch(BaseModel):
    """A candidate existing graph node that an ambiguous entity might refer to."""
    node_id: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)


class CandidateEntity(BaseModel):
    temp_id: str
    type: NodeType
    label: str
    aliases: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str
    # Constraint §26-5: LLM signals ambiguity; Pydantic enforces the shape.
    is_ambiguous: bool = False
    possible_matches: list[PossibleMatch] = Field(default_factory=list)


class EntityExtractionOutput(BaseModel):
    entities: list[CandidateEntity]


# ── Agent output: Relationship extraction ─────────────────────────────────────

class CandidateRelationship(BaseModel):
    temp_id: str
    type: RelationshipType
    source_ref: str  # temp_id or an existing GraphNode.id
    target_ref: str  # temp_id or an existing GraphNode.id
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str


class RelationshipExtractionOutput(BaseModel):
    relationships: list[CandidateRelationship]


# ── Agent output: Attribute extraction ───────────────────────────────────────

class CandidateAttribute(BaseModel):
    entity_ref: str  # temp_id or existing node id
    attribute_key: str
    attribute_value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str


class AttributeExtractionOutput(BaseModel):
    attributes: list[CandidateAttribute]


# ── Agent output: Clarification detection ─────────────────────────────────────

class Clarification(BaseModel):
    kind: ClarificationKind
    target: str
    reason: str
    suggested_question: str
    priority: ClarificationPriority


class ClarificationOutput(BaseModel):
    clarifications: list[Clarification]


# ── Agent output: Graph mapping ────────────────────────────────────────────────

class NodeUpdateOp(BaseModel):
    op: UpdateOp
    node: GraphNode


class EdgeUpdateOp(BaseModel):
    op: UpdateOp
    edge: GraphEdge


class GraphMappingOutput(BaseModel):
    node_updates: list[NodeUpdateOp] = Field(default_factory=list)
    edge_updates: list[EdgeUpdateOp] = Field(default_factory=list)


# ── Agent output: Orchestrator ────────────────────────────────────────────────

class OrchestratorOutput(BaseModel):
    next_question: str
    rationale: str
    target_category: str
    question_id: str = Field(default_factory=_q_id)


# ── Agent output: Coverage ────────────────────────────────────────────────────

class CoverageOutput(BaseModel):
    updated_scores: CoverageScores
    priority_topics: list[str]
    missing_categories: list[str]
    rationale: str


# ── Proposed update bundle (pre-commit) ───────────────────────────────────────
#
# Specialist agents write their outputs here.
# ONLY updater.py may move items from here into the canonical KnowledgeGraph.

class ProposedUpdate(BaseModel):
    update_id: str = Field(default_factory=_upd_id)
    source_turn_id: str
    entity_extraction: EntityExtractionOutput | None = None
    relationship_extraction: RelationshipExtractionOutput | None = None
    attribute_extraction: AttributeExtractionOutput | None = None
    graph_mapping: GraphMappingOutput | None = None
    clarifications: ClarificationOutput | None = None
    committed: bool = False


# ── Shared interview state ────────────────────────────────────────────────────
#
# Single source of truth for the live session.
# Agents receive named slices of this object, never the whole thing.

class SharedInterviewState(BaseModel):
    session_id: str = Field(default_factory=_sess_id)
    interviewee: Interviewee
    graph: KnowledgeGraph = Field(default_factory=KnowledgeGraph)
    proposed_updates: list[ProposedUpdate] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    coverage: CoverageScores = Field(default_factory=CoverageScores)
    asked_question_ids: list[str] = Field(default_factory=list)
    turns: list[InterviewTurn] = Field(default_factory=list)
    final_outputs: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
