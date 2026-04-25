"""
Golden interview fixture: "Timid Noah"

Scenario 2 — Cloud Migration Support Rollover.
Noah Kim is a junior contractor who is cautious and worried about saying something
incorrect. He gives partial answers unless encouraged. This fixture tests whether the
system adapts follow-up intensity when the interviewee is hesitant or low-confidence,
and whether clarification agents generate enough probing questions to extract usable detail.

Turn order driven by the seeded cloud_migration_seed.json priority ladder:
  1. amb_cloud_001 — Rachel ambiguity (app team vs. security)
  2. q_cloud_001   — escalation thresholds (workflows, high)
  3. q_cloud_002   — which parts of access verification are manual (undocumented_knowledge, high)
  4. q_cloud_003   — how to distinguish systemic from local tickets (risks, medium)
"""
from __future__ import annotations

from pathlib import Path

from app.core.models import Interviewee

INTERVIEWEE = Interviewee(
    name="Noah Kim",
    role="Contractor - Incident Coordination Support",
    project_ids=["project_cloud_migration"],
)

SEED_PATH = Path(__file__).parent.parent / "seeds" / "cloud_migration_seed.json"

SCRIPTED_ANSWERS: list[str] = [
    # Turn 1 — Rachel ambiguity
    (
        "Oh, that would be Rachel from application support — her last name is Kim, "
        "same as mine actually. Rachel Kim. The security team has someone named Rachel "
        "too but she mostly deals with policy changes, not the role mapping stuff."
    ),
    # Turn 2 — escalation thresholds (q_cloud_001)
    (
        "Um, it's hard to explain exactly. It kind of depended on the situation. "
        "I guess if it was a lot of people having problems, or if it was someone "
        "important like an executive or someone in finance, then you'd want to reach "
        "out directly too, not just submit the ticket. But I'm not sure that's written "
        "down anywhere officially. It was more just how people seemed to handle it."
    ),
    # Turn 3 — manual parts of access verification (q_cloud_002)
    (
        "The checklist says it's automated but the exceptions part isn't really. "
        "Like, there's a Teams thread where people would flag the exceptions, and "
        "then someone would copy them into the tracker later. Rachel Kim handled "
        "most of that. I think if she was out it might not get done properly — "
        "I'm not totally sure who the backup would be."
    ),
    # Turn 4 — systemic vs local ticket triage (q_cloud_003)
    (
        "I learned mostly from watching patterns. If multiple people from the same "
        "business unit all lost access right after a migration weekend, that usually "
        "meant a mapping or sync issue — you'd want to flag Dev Patel on infrastructure. "
        "If it was just one person and their device was behaving strangely, that was "
        "usually just a local thing for regular support to handle. I wish someone had "
        "written that down though. It took me a while to figure out."
    ),
]

# ── Assertions ────────────────────────────────────────────────────────────────

# The Rachel ambiguity should be resolved (Rachel Kim, app support).
RICHARD_AMBIGUITY_ID: str = "amb_cloud_001"

# Noah is hesitant — clarifications should fire frequently to probe vague answers.
MIN_TOTAL_CLARIFICATIONS: int = 3

# Shallow, hesitant answers should not hallucinate confident new entities,
# but structured questions do elicit fragments that produce provisional nodes.
MAX_NEW_NODES: int = 18

# Coverage can rise somewhat because Noah gives partial specifics (names,
# tool names), unlike a fully evasive witness.  Ceiling set from empirical
# runs; still well below a fully cooperative witness profile.
MAX_COVERAGE_SCORE: float = 0.70

# Entities that should NOT be hallucinated from Noah's hedging language.
LABELS_THAT_MUST_NOT_EXIST: list[str] = [
    "Official Policy",
    "The Management",
]
