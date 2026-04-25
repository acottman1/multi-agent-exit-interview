"""
Golden interview fixture: "Cooperative Lena"

Scenario 1 — ERP Modernization Handoff.
Lena Torres is a senior contractor BA rolling off a nine-month ERP modernization
engagement. She is cooperative, articulate, and reflective — the optimistic baseline
for demonstrating named-entity extraction, stakeholder relationship mapping, and
identification of undocumented workflow deviations.

Turn order driven by the seeded erp_modernization_seed.json priority ladder:
  1. amb_erp_001  — Marcus ambiguity (who revised the process map?)
  2. q_erp_001    — vendor onboarding actual path (workflows, high)
  3. q_erp_002    — supplier exception approval rule vs workaround (undocumented_knowledge, high)
  4. q_erp_003    — January scope change and where it's documented (risks, medium)
"""
from __future__ import annotations

from pathlib import Path

from app.core.models import Interviewee

INTERVIEWEE = Interviewee(
    name="Lena Torres",
    role="Contractor - Senior Business Analyst",
    project_ids=["project_erp"],
)

SEED_PATH = Path(__file__).parent.parent / "seeds" / "erp_modernization_seed.json"

SCRIPTED_ANSWERS: list[str] = [
    # Turn 1 — Marcus ambiguity
    (
        "That was Marcus Lee — he's on the client integration team. Marcus Baines "
        "is internal, but it was Marcus Lee who redrew the process map after the "
        "February workshop because the original swimlane didn't reflect the SharePoint "
        "detour we added for legal review."
    ),
    # Turn 2 — vendor onboarding actual path (q_erp_001)
    (
        "The documented flow says it starts in OrionERP, but that's not what actually "
        "happens. The real path is: someone fills out a SharePoint intake form first "
        "because legal review needs fields that never made it into the first OrionERP "
        "release. Once legal signs off, the request goes to manual triage — Janelle "
        "Brooks in operations does that review — and only then does the actual OrionERP "
        "vendor record get created. Janelle is the only one who knows which requests "
        "have sufficient supporting evidence to move forward. That dependency is not "
        "documented anywhere."
    ),
    # Turn 3 — supplier exception approval (q_erp_002)
    (
        "The business rule is owned by Priya Shah — she knows what qualifies as a "
        "legitimate exception. But the actual workaround to get an exception unblocked "
        "quickly is Marcus Lee's territory. He knows which middleware touchpoints to "
        "adjust so the exception doesn't stall in the queue. If you go to Priya alone "
        "you get the rule. If you go to Marcus alone you get movement but maybe not "
        "the right rule. You need both of them in the room."
    ),
    # Turn 4 — January scope change (q_erp_003)
    (
        "In January we finally admitted the vendor workflow was too unstable to include "
        "in release one. Before that, the whole team was acting as if both employee and "
        "vendor flows would go live together. After that review, success criteria shifted "
        "from 'go live broadly' to 'stabilize employee flow and preserve a controlled "
        "exception process.' That decision is in the decision register in Confluence — "
        "it's actually one of the better-documented moments. Elena Ruiz from HR "
        "operations was the one who forced the conversation because she was most "
        "concerned about the data quality impact on employees."
    ),
]

# ── Assertions ────────────────────────────────────────────────────────────────

REQUIRED_NODE_LABELS: list[str] = [
    "Marcus Lee",     # ambiguity resolved; process map owner
    "Janelle Brooks", # new — critical undocumented dependency
    "Priya Shah",     # exception rule owner
    "Elena Ruiz",     # new — HR operations stakeholder
]

RICHARD_AMBIGUITY_ID: str = "amb_erp_001"

EXPECTED_COVERAGE_ABOVE_ZERO: list[str] = [
    "workflows",
    "undocumented_knowledge",
    "risks",
]

MIN_NEW_NODES: int = 2  # at minimum Janelle Brooks + Elena Ruiz
