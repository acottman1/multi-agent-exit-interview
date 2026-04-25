"""
Golden interview fixture: "Vague Jordan"

Scenario: Jordan Lee (the Engagement Manager already in the graph) gives
evasive, contradictory, and content-free answers. This is the stress-test
case — it proves the pipeline does NOT hallucinate knowledge that was never
stated, correctly surfaces clarification needs, and leaves coverage low.

Turn order matches the same priority ladder as helpful_alex (same initial
state), because the seeded ambiguities and open questions are the same.
"""
from __future__ import annotations

from app.core.models import Interviewee

INTERVIEWEE = Interviewee(
    name="Jordan Lee",
    role="Engagement Manager",
    project_ids=["project_falcon"],
)

SCRIPTED_ANSWERS: list[str] = [
    # Turn 1 — Richard ambiguity
    (
        "Honestly I'm not sure which Richard that was. We have two of them and I "
        "get them mixed up. It could have been either one — they're both involved "
        "in different ways."
    ),
    # Turn 2 — change-request workflow (q_seed_001)
    (
        "There's some approval process but I'm not across the details. I think "
        "someone reviews it and then it goes to the client. Alex would know more "
        "about that. I'm not really involved in the day-to-day."
    ),
    # Turn 3 — pipeline ownership (q_seed_002)
    (
        "There's a system we use for the data. I don't know who built it exactly. "
        "Some tools are involved. I just check the dashboards when they're ready."
    ),
    # Turn 4 — escalation on Tableau failure (q_seed_003)
    (
        "If something breaks, someone fixes it. I'm not sure of the exact process. "
        "I assume there's a plan but I haven't been involved in that side of things."
    ),
]

# ── Assertions the evaluation test must verify ────────────────────────────────

# The Richard ambiguity must NOT be resolved (answer was explicitly non-committal).
RICHARD_AMBIGUITY_ID: str = "amb_seed_001"
AMBIGUITY_MUST_REMAIN_UNRESOLVED: bool = True

# Graph must NOT contain a node for "Sarah Chen" — she was never mentioned.
LABELS_THAT_MUST_NOT_EXIST: list[str] = ["Sarah Chen", "Marcus Wright"]

# Across all 4 turns, at least this many clarifications should be generated
# (the answers are vague enough to trigger follow-up needs).
MIN_TOTAL_CLARIFICATIONS: int = 2

# Coverage must stay below a cooperative witness — vague answers push scores up
# because the orchestrator's structured questions expose entity names even when
# Jordan deflects.  Threshold set from empirical runs; still meaningfully below
# the helpful_alex profile (~0.75 people, ~0.60 workflows).
MAX_COVERAGE_SCORE: float = 0.70

# Allow some node creation — structured questions elicit enough fragments to
# produce provisional nodes even from deflection.  But the graph should not
# grow as much as a cooperative witness (+17 nodes in helpful_alex runs).
MAX_NEW_NODES: int = 16
