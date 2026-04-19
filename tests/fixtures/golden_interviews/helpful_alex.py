"""
Golden interview fixture: "Helpful Alex"

Scenario: Alex Miller is cooperative, specific, and names people / systems
precisely. This is the optimistic case — it proves the extraction pipeline
captures clearly-stated knowledge accurately.

Turn order is dictated by the orchestrator's rule-based priority ladder given
the seeded initial_state.json:
  1. amb_seed_001  — Richard ambiguity (highest priority)
  2. q_seed_001    — change-request approval path (workflows, high)
  3. q_seed_002    — Snowflake-to-Tableau pipeline owner (systems, high)
  4. q_seed_003    — escalation path on Tableau failure (risks, medium)
"""
from __future__ import annotations

from app.core.models import Interviewee

INTERVIEWEE = Interviewee(
    name="Alex Miller",
    role="Contractor - Data Analyst",
    project_ids=["project_falcon"],
)

# Scripted answers in turn order.  The provider ignores the actual question
# text and returns these in sequence.
SCRIPTED_ANSWERS: list[str] = [
    # Turn 1 — Richard ambiguity
    (
        "That was Richard Jones, the client-side product owner at NorthStar Corp. "
        "Richard Smith is internal — he's our program manager — but the FALCON-42 "
        "comment was definitely about Richard Jones blocking the approval on their side."
    ),
    # Turn 2 — change-request workflow (q_seed_001)
    (
        "The full approval path is: first I assess the data-model impact and write "
        "up a change spec, then Jordan Lee reviews it internally and signs off. "
        "On the client side, Richard Jones reviews the spec with his team, and "
        "then Marcus Wright — NorthStar's VP of Data — has final sign-off. "
        "Marcus is the one who actually unblocks things when Richard is on holiday. "
        "The whole loop usually takes two to three weeks and nothing is automated."
    ),
    # Turn 3 — pipeline ownership (q_seed_002)
    (
        "Sarah Chen owns the entire Snowflake-to-Tableau pipeline. She's a data "
        "engineer on our team, reports to Jordan. She built all the dbt models "
        "that sit between Snowflake and Tableau and she's the only one who "
        "understands the transformation logic end-to-end. The dbt project lives "
        "in a private GitHub repo — sarah-chen/falcon-dbt — and she's the sole "
        "maintainer. That's the single biggest knowledge-transfer risk."
    ),
    # Turn 4 — escalation on Tableau failure (q_seed_003)
    (
        "If Tableau goes down overnight, call Sarah Chen first — she can usually "
        "diagnose from the Snowflake logs without waking anyone else. If she can't "
        "fix it within two hours, the escalation goes to Jordan Lee, who decides "
        "whether to call the NorthStar on-call contact. The on-call contact is "
        "listed in the NorthStar SLA document but I don't think that document is "
        "in Confluence — it might only exist in Richard Jones's inbox."
    ),
]

# ── Assertions the evaluation test must verify ────────────────────────────────

# Node labels that MUST appear somewhere in the final graph (case-insensitive
# substring match against GraphNode.label).
REQUIRED_NODE_LABELS: list[str] = [
    "Richard Jones",   # pre-seeded but ambiguity must be resolved
    "Sarah Chen",      # new person, extracted from turns 3 and 4
    "Marcus Wright",   # new person, first mentioned in turn 2
]

# The seeded Richard ambiguity must be marked resolved after turn 1.
RICHARD_AMBIGUITY_ID: str = "amb_seed_001"

# Coverage categories that must have increased above their starting value of 0.
EXPECTED_COVERAGE_ABOVE_ZERO: list[str] = ["workflows", "systems", "risks"]

# Minimum number of unique new nodes added during the interview (excluding
# those already present in initial_state.json, which has 13 nodes).
MIN_NEW_NODES: int = 2  # at minimum Sarah Chen + Marcus Wright
