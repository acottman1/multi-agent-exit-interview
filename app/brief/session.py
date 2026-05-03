"""
BriefSessionState — single source of truth for a live brief-engine interview.

Analogous to SharedInterviewState for the graph engine, but built around the
brief artifact rather than the KnowledgeGraph. Agents receive slices of this
object (Constraint §26-4), never the whole thing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from app.brief.schema import RoleBrief
from app.config.context_briefing import ContextBriefing
from app.config.domain_config import DomainConfig
from app.core.models import Ambiguity, InterviewTurn, OpenQuestion


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _sess_id() -> str:
    return f"sess_{uuid4().hex[:8]}"


class BriefSessionState(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    session_id: str = Field(default_factory=_sess_id)
    domain_config: DomainConfig
    context_briefing: ContextBriefing | None = None
    brief: RoleBrief

    turns: list[InterviewTurn] = Field(default_factory=list)

    # Keyed by coverage_category.name; values 0.0–1.0.
    coverage: dict[str, float] = Field(default_factory=dict)

    asked_question_ids: list[str] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)

    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None

    # ── Convenience helpers ───────────────────────────────────────────────────

    def mandatory_coverage_met(self) -> bool:
        """True when every mandatory category has reached its min_score."""
        return all(
            self.coverage.get(cat.name, 0.0) >= cat.min_score
            for cat in self.domain_config.mandatory_categories()
        )

    def weighted_completeness(self) -> float:
        """Weighted average of all coverage scores, capped at 1.0."""
        cats = self.domain_config.coverage_categories
        total_weight = sum(c.weight for c in cats)
        if total_weight == 0:
            return 0.0
        return min(
            1.0,
            sum(self.coverage.get(c.name, 0.0) * c.weight for c in cats) / total_weight,
        )
