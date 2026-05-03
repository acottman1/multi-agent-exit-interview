"""
ContextBriefing — lightweight pre-interview context loaded before turn 1.

Replaces the full KnowledgeGraph in initial_state.json for the brief engine.
The briefing gives the interview engine just enough to:
  - Make questions specific rather than generic ("you work with Sarah Chen"
    instead of "who do you work with?")
  - Pre-populate the entity extractor's alias map so disambiguation fires
    on known names from turn 1 rather than only after they appear.
  - Let the coverage updater track which known items have been discussed.

Intentionally thin — the interview elicits the rest.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ── Known entities (preloaded anchors) ───────────────────────────────────────

class KnownPerson(BaseModel):
    """A person the interviewee is known to work with, used for disambiguation."""
    canonical_name: str         # "First Last" form — must match RoleBrief dedup_key
    role: str
    team: str | None = None
    is_internal: bool = True


class KnownSystem(BaseModel):
    """A system/tool the interviewee is known to use, used for disambiguation."""
    canonical_name: str         # "Vendor Product" form — must match RoleBrief dedup_key
    category: str | None = None # e.g. "crm", "analytics", "communication", "internal"


# ── Interviewee identity ──────────────────────────────────────────────────────

class IntervieweeContext(BaseModel):
    name: str
    role_title: str
    department: str | None = None
    manager_name: str | None = None
    last_day: str | None = None         # ISO date string, e.g. "2026-05-15"
    years_at_org: float | None = None


# ── Full context briefing ─────────────────────────────────────────────────────

class ContextBriefing(BaseModel):
    """
    Pre-interview context provided to the engine before the first turn.

    Load from a JSON file via ContextBriefing.model_validate(json.loads(...)).
    The engine uses this to seed the RoleBrief.meta and the entity extractor's
    alias map, then discards it — the interviewee's answers fill everything else.
    """
    interviewee: IntervieweeContext
    known_team_members: list[KnownPerson] = Field(default_factory=list)
    known_systems: list[KnownSystem] = Field(default_factory=list)
    known_responsibilities: list[str] = Field(default_factory=list)

    def alias_map(self) -> dict[str, list[str]]:
        """Return surface-form → [canonical_name] for the entity extractor."""
        result: dict[str, list[str]] = {}
        for person in self.known_team_members:
            first_name = person.canonical_name.split()[0]
            result.setdefault(first_name, []).append(person.canonical_name)
            result.setdefault(person.canonical_name, []).append(person.canonical_name)
        for system in self.known_systems:
            result.setdefault(system.canonical_name, []).append(system.canonical_name)
        return result
