"""
Golden interview fixture: "Technical Aisha"

Scenario 4 — Cybersecurity Compliance Transition.
Aisha Rahman is technical and knowledgeable but concise to the point of
underexplaining. She assumes context and gives compressed answers. This fixture
is a strong candidate for graph-shaped output: systems, controls, artifacts,
owners, and exceptions can be mapped explicitly. Tests whether entity and
relationship extractors handle dense, terse responses.

Turn order driven by the seeded cybersecurity_seed.json priority ladder:
  1. amb_cyber_001 — Priya ambiguity (IT support vs. governance)
  2. q_cyber_001   — quarterly access review end-to-end (workflows, high)
  3. q_cyber_002   — verifying remediation actually happened (undocumented_knowledge, high)
  4. q_cyber_003   — exception tracker ownership (risks, medium)
"""
from __future__ import annotations

from pathlib import Path

from app.core.models import Interviewee

INTERVIEWEE = Interviewee(
    name="Aisha Rahman",
    role="Contractor - Compliance Analyst",
    project_ids=["project_soc2_compliance"],
)

SEED_PATH = Path(__file__).parent.parent / "seeds" / "cybersecurity_seed.json"

SCRIPTED_ANSWERS: list[str] = [
    # Turn 1 — Priya ambiguity
    (
        "That's Priya Nair, IT support. She reconciles the Jamf endpoint inventory "
        "when counts don't match what Okta shows. There's no Priya in governance — "
        "Mina handles governance coordination."
    ),
    # Turn 2 — quarterly access review end-to-end (q_cyber_001)
    (
        "Drata generates the review task. Application owners get notified and validate "
        "their access lists — response rates vary, security ops follows up on "
        "non-responders. Once evidence is collected it gets exported, normalized for "
        "naming convention, and stored in SharePoint under the current quarter folder. "
        "Exceptions go into a separate spreadsheet outside Drata if revocation takes "
        "longer than the policy window. Jamf exports are delayed on Mondays so don't "
        "schedule evidence collection runs on Monday mornings. Some application owners "
        "won't respond without escalation through their director — Darren handles that."
    ),
    # Turn 3 — verifying remediation (q_cyber_002)
    (
        "Cross-check the ServiceNow ticket. Drata shows task complete but that only "
        "means someone marked it done. The actual remediation evidence — access revoked, "
        "ticket closed with closure notes — lives in ServiceNow. For Okta-related items "
        "you also need to pull the admin export and verify the account is actually "
        "deprovisioned, not just flagged. That cross-check is in my audit notes but "
        "not in the standard control narrative."
    ),
    # Turn 4 — exception tracker ownership (q_cyber_003)
    (
        "Intended owner is security governance. In practice it was me this cycle. "
        "Mina is supposed to take it over but hasn't been formally handed the "
        "spreadsheet yet. If I leave before that's done, it lives on my SharePoint "
        "mirror. The risk is naming convention — auditors flag anything that doesn't "
        "match the evidence package folder structure, even if the content is correct."
    ),
]

# ── Assertions ────────────────────────────────────────────────────────────────

# Priya ambiguity resolved to Priya Nair in IT support.
RICHARD_AMBIGUITY_ID: str = "amb_cyber_001"

# Dense answers should yield a rich entity set.
REQUIRED_NODE_LABELS: list[str] = [
    "Priya Nair",    # ambiguity resolved with full name
    "Mina",          # governance coordinator
    "Darren",        # security ops escalation lead
    "ServiceNow",    # already seeded but must appear in relationships
]

EXPECTED_COVERAGE_ABOVE_ZERO: list[str] = [
    "workflows",
    "systems",
    "undocumented_knowledge",
    "risks",
]

MIN_NEW_NODES: int = 1  # at minimum Priya Nair resolved from ambiguity
