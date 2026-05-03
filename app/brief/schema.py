"""
RoleBrief schema — the primary output artifact of a completed interview.

Each section maps directly to a downstream use case:
  role_summary      → onboarding materials, JD reality-check
  responsibilities  → delegation, handoff planning
  people            → relationship map, warm introductions
  systems           → access provisioning, technical onboarding
  implicit_knowledge → the stuff that gets lost without this tool
  risks             → 30/60/90-day watchlist for the successor
  hiring_profile    → backfill interview kit (generated end-of-interview)

Agents fill sections by appending items. The updater deduplicates on
each item's dedup_key field (defined per-section in DomainConfig).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _brief_id() -> str:
    return f"brief_{uuid4().hex[:8]}"


# ── Shared vocabulary ─────────────────────────────────────────────────────────

Criticality = Literal["low", "medium", "high", "critical"]
Frequency = Literal["daily", "weekly", "monthly", "ad-hoc", "as-needed"]
HandoffStatus = Literal["documented", "undocumented", "in-progress", "at-risk", "not-started"]
OwnershipStatus = Literal["owned", "co-owned", "used"]
FragilityRating = Literal["low", "medium", "high", "critical"]
DocumentationStatus = Literal["well-documented", "partially-documented", "undocumented"]
RelationshipType = Literal["collaborator", "dependency", "stakeholder", "escalation", "report", "client"]
KnowledgeType = Literal["historical_context", "workaround", "judgment_rule", "social_norm", "technical_detail"]
Urgency = Literal["immediate", "first-week", "first-month", "first-quarter", "background"]
RiskType = Literal["single_point_of_failure", "relationship_risk", "technical_debt", "knowledge_gap", "process_gap"]
Severity = Literal["low", "medium", "high", "critical"]
Likelihood = Literal["unlikely", "possible", "likely", "certain"]


# ── Meta ──────────────────────────────────────────────────────────────────────

class BriefMeta(BaseModel):
    session_id: str
    domain_name: str
    interviewee_name: str
    role_title: str
    interview_date: datetime = Field(default_factory=_utcnow)
    completeness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    open_questions_count: int = Field(default=0, ge=0)
    last_day: str | None = None
    team_name: str | None = None
    manager_name: str | None = None


# ── Role summary ──────────────────────────────────────────────────────────────

class RoleSummary(BaseModel):
    one_liner: str
    formal_vs_actual: str
    team_name: str | None = None
    manager_name: str | None = None


# ── Responsibilities ──────────────────────────────────────────────────────────

class Responsibility(BaseModel):
    title: str                       # dedup_key — imperative verb-noun phrase
    description: str
    criticality: Criticality
    frequency: Frequency
    in_job_description: bool = False
    handoff_status: HandoffStatus = "undocumented"
    systems_involved: list[str] = Field(default_factory=list)   # canonical names
    people_involved: list[str] = Field(default_factory=list)    # canonical names
    source_turn_ids: list[str] = Field(default_factory=list)


# ── People ────────────────────────────────────────────────────────────────────

class BriefPerson(BaseModel):
    canonical_name: str              # dedup_key — "First Last" always
    role_title: str
    organization: str
    relationship_type: RelationshipType
    continuity_reason: str
    nuance_notes: str = ""
    source_turn_ids: list[str] = Field(default_factory=list)


# ── Systems ───────────────────────────────────────────────────────────────────

class BriefSystem(BaseModel):
    canonical_name: str              # dedup_key — "Vendor Product" format
    ownership_status: OwnershipStatus
    owner_name: str | None = None
    fragility: FragilityRating
    documentation_status: DocumentationStatus
    access_holders: list[str] = Field(default_factory=list)     # canonical names
    gotchas: str = ""
    source_turn_ids: list[str] = Field(default_factory=list)


# ── Implicit knowledge ────────────────────────────────────────────────────────

class ImplicitKnowledgeItem(BaseModel):
    title: str                       # dedup_key — noun-phrase descriptor
    description: str
    knowledge_type: KnowledgeType
    urgency: Urgency
    related_systems: list[str] = Field(default_factory=list)    # canonical names
    related_people: list[str] = Field(default_factory=list)     # canonical names
    source_turn_ids: list[str] = Field(default_factory=list)


# ── Risks ─────────────────────────────────────────────────────────────────────

class BriefRisk(BaseModel):
    title: str                       # dedup_key — noun-phrase naming what's at risk
    description: str
    risk_type: RiskType
    severity: Severity
    likelihood: Likelihood
    mitigation: str = ""
    related_systems: list[str] = Field(default_factory=list)    # canonical names
    related_people: list[str] = Field(default_factory=list)     # canonical names
    source_turn_ids: list[str] = Field(default_factory=list)


# ── Hiring profile ────────────────────────────────────────────────────────────

class HiringProfile(BaseModel):
    role_title: str                  # dedup_key — binds to role in Obsidian graph
    required_skills: list[str] = Field(default_factory=list)
    interview_questions: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    background_note: str = ""


# ── Role brief (top-level artifact) ──────────────────────────────────────────

class RoleBrief(BaseModel):
    brief_id: str = Field(default_factory=_brief_id)
    meta: BriefMeta

    role_summary: RoleSummary | None = None
    responsibilities: list[Responsibility] = Field(default_factory=list)
    people: list[BriefPerson] = Field(default_factory=list)
    systems: list[BriefSystem] = Field(default_factory=list)
    implicit_knowledge: list[ImplicitKnowledgeItem] = Field(default_factory=list)
    risks: list[BriefRisk] = Field(default_factory=list)
    hiring_profile: HiringProfile | None = None

    open_questions: list[str] = Field(default_factory=list)
    extra_sections: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=_utcnow)
    finalized: bool = False

    # ── Convenience helpers ───────────────────────────────────────────────────

    def section_item_count(self) -> dict[str, int]:
        return {
            "responsibilities": len(self.responsibilities),
            "people": len(self.people),
            "systems": len(self.systems),
            "implicit_knowledge": len(self.implicit_knowledge),
            "risks": len(self.risks),
        }

    def is_empty(self) -> bool:
        return all(c == 0 for c in self.section_item_count().values())
