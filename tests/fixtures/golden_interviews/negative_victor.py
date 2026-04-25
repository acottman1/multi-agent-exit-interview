"""
Golden interview fixture: "Negative Victor"

Scenario 3 — Data Platform Contractor Exit.
Victor Hale is a contractor data engineer leaving after a difficult six-month
engagement. He is negative and sometimes sarcastic but produces high-value risk
and dependency signals underneath the frustration. This fixture tests tone guardrails
(the system should not escalate conflict or validate complaints) and confirms that
frustration can still yield graph-usable knowledge.

Turn order driven by the seeded data_platform_seed.json priority ladder:
  1. amb_data_001  — Priyanka ambiguity (analytics vs. platform)
  2. q_data_001    — where fallback logic lives (undocumented_knowledge, high)
  3. q_data_002    — CRM null decision rule (workflows, high)
  4. q_data_003    — how to detect incomplete data from a green run (risks, medium)
"""
from __future__ import annotations

from pathlib import Path

from app.core.models import Interviewee

INTERVIEWEE = Interviewee(
    name="Victor Hale",
    role="Contractor - Data Engineer",
    project_ids=["project_data_platform"],
)

SEED_PATH = Path(__file__).parent.parent / "seeds" / "data_platform_seed.json"

SCRIPTED_ANSWERS: list[str] = [
    # Turn 1 — Priyanka ambiguity
    (
        "Priyanka on analytics — Priyanka Suresh. She owns the business logic side. "
        "There's no Priyanka on platform as far as I know, that must be a phantom from "
        "an old org chart. Priyanka Suresh is the one you need to loop in before "
        "touching anything that changes what the dashboards show."
    ),
    # Turn 2 — where fallback logic lives (q_data_001)
    (
        "Half of it is in Airflow variables — you can find those in the customer health "
        "workflow config — and the other half is in a helper script in the analytics-"
        "engineering repo, path is something like scripts/health_mart_overrides.py. "
        "Which is, obviously, a disaster. Nobody told leadership that the 'dbt model "
        "chain' has custom patches scattered across two separate places. Ben from "
        "platform knows the Airflow side. Priyanka knows the script. Neither of them "
        "knew the other's piece existed until I showed them both about a month ago."
    ),
    # Turn 3 — CRM null decision rule (q_data_002)
    (
        "There is no rule. That's the point. When the CRM file arrives with unexpected "
        "nulls, someone — and it has been me — has to decide whether to block the mart "
        "refresh entirely or let the fallback transformation run. If you block it, the "
        "dashboard goes stale and someone calls. If you let the fallback run, the "
        "dashboard looks fine but the data is incomplete and probably nobody notices "
        "until the Monday review. The team wanted stable-looking dashboards for "
        "leadership demos so the fallback became the default. No one documented "
        "when that's acceptable and when it's not."
    ),
    # Turn 4 — detecting incomplete data from green run (q_data_003)
    (
        "You compare row counts and freshness against the control sheet. Priyanka "
        "keeps a Google Sheet she updates before Monday business reviews — it has "
        "the expected counts and the acceptable freshness windows. There's also a "
        "data-quality comparison script I built in the repo. Most of the team doesn't "
        "know it exists. Run it before you tell anyone the pipeline is healthy. "
        "Green status on Airflow means the job completed. It does not mean the data "
        "is correct."
    ),
]

# ── Assertions ────────────────────────────────────────────────────────────────

# Priyanka ambiguity resolved to "Priyanka Suresh" on analytics.
RICHARD_AMBIGUITY_ID: str = "amb_data_001"

# Despite frustration, these entities must be captured from the signal.
REQUIRED_NODE_LABELS: list[str] = [
    "Priyanka Suresh",  # ambiguity resolved with full name
    "Ben",              # platform, owns Airflow side
]

EXPECTED_COVERAGE_ABOVE_ZERO: list[str] = [
    "undocumented_knowledge",
    "workflows",
    "risks",
]

MIN_NEW_NODES: int = 1  # at minimum Priyanka Suresh (resolved from ambiguity)

# Frustration venting should not produce hallucinated entity nodes.
# Note: "leadership demos" is a legitimate task Victor mentioned; we guard
# against a standalone vague authority-figure node, not the phrase "leadership".
LABELS_THAT_MUST_NOT_EXIST: list[str] = [
    "Leadership Team",
    "Management",
]
