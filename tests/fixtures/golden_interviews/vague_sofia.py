"""
Golden interview fixture: "Vague Sofia"

Scenario 5 — Client Onboarding Operations Transfer.
Sofia Mendes is friendly and high-level but tends to summarize outcomes instead
of steps. She gives answers that sound complete but lack operational detail.
This fixture tests whether the system correctly rejects vague completion signals
and keeps probing for graph-usable specifics, and whether the clarification
detector fires frequently on low-information answers.

Turn order driven by the seeded client_onboarding_seed.json priority ladder:
  1. amb_onboard_001 — client's technical team ambiguity (internal IT vs vendor)
  2. q_onboard_001   — tracker fields that actually matter (undocumented_knowledge, high)
  3. q_onboard_002   — SSO readiness definition in practice (workflows, high)
  4. q_onboard_003   — early warning signs for onboarding at risk (risks, medium)
"""
from __future__ import annotations

from pathlib import Path

from app.core.models import Interviewee

INTERVIEWEE = Interviewee(
    name="Sofia Mendes",
    role="Contractor - Onboarding Coordinator",
    project_ids=["project_onboarding_program"],
)

SEED_PATH = Path(__file__).parent.parent / "seeds" / "client_onboarding_seed.json"

SCRIPTED_ANSWERS: list[str] = [
    # Turn 1 — technical team ambiguity
    (
        "It depends on the client, honestly. Sometimes it's their internal IT group "
        "and sometimes they bring in a vendor. We just ask whoever shows up to the "
        "kickoff. Usually it works out."
    ),
    # Turn 2 — tracker fields that matter (q_onboard_001)
    (
        "The tracker has a lot of fields but the important ones are basically the "
        "client contacts, the go-live date, and the product modules. Oh and whether "
        "SSO is involved because that always takes longer. The rest is kind of "
        "administrative. You get a feel for it pretty quickly."
    ),
    # Turn 3 — SSO readiness in practice (q_onboard_002)
    (
        "SSO is always tricky. Clients say they're ready but usually they mean they've "
        "started looking into it internally. We've learned to ask if legal and security "
        "have actually signed off, not just if they're 'working on it.' If they haven't, "
        "configuration can't really start on our side."
    ),
    # Turn 4 — early warning signs (q_onboard_003)
    (
        "You can usually tell when something is going to slip. Like if the client "
        "hasn't named a technical owner by the second week, that's a red flag. "
        "Or if the go-live date is really aggressive and they haven't done training "
        "yet. Multi-region clients are also harder — data residency questions always "
        "come up late. We've had situations where we were almost ready to go live and "
        "then legal flagged something about where data was being stored."
    ),
]

# ── Assertions ────────────────────────────────────────────────────────────────

# The technical team ambiguity is NOT resolved — vague answer leaves it open.
AMBIGUITY_MUST_REMAIN_UNRESOLVED: bool = True
RICHARD_AMBIGUITY_ID: str = "amb_onboard_001"

# Vague answers should trigger heavy clarification probing.
MIN_TOTAL_CLARIFICATIONS: int = 4

# Vague answers should not score high coverage.
MAX_COVERAGE_SCORE: float = 0.30

# Minimal graph growth — Sofia's answers are outcome-level, not entity-level.
MAX_NEW_NODES: int = 3

# Generic summary language should not be hallucinated as graph entities.
LABELS_THAT_MUST_NOT_EXIST: list[str] = [
    "Whoever Shows Up",
    "The Client",
    "Usually",
]
