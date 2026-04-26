"""
Orchestrator agent — selects the next interview question.

Phase 4 implementation is rule-based and deterministic. A later phase will
swap this for an LLM-backed version (via instructor) while preserving the
`select_next_question` contract. Tests pin the priority ladder so that
swap cannot silently change interview behaviour.

Priority ladder (highest first):
  1. Unresolved ambiguity with highest priority (e.g. the 'Richard' problem)
  2. Seeded open_question not yet asked, highest priority first
  3. Lowest-confidence provisional node in the graph
  4. Coverage-gap fallback question for the lowest-scoring category
"""
from __future__ import annotations

import hashlib

from app.core.models import (
    ClarificationPriority,
    OrchestratorOutput,
    SharedInterviewState,
)
from app.graph.schema import GraphNode, NodeType
from app.graph.updater import CONFIRMED_THRESHOLD

# Lower rank integer = higher priority.
_PRIORITY_RANK: dict[ClarificationPriority, int] = {"high": 0, "medium": 1, "low": 2}


# ── Question variant pools ─────────────────────────────────────────────────────

# Multiple formulations per coverage category.  Selection is deterministic
# per session (hash of session_id + key) so replaying an interview always
# produces the same questions.
_FALLBACK_VARIANTS: dict[str, list[str]] = {
    "people": [
        "Who else did you work with day-to-day that we haven't talked about yet?",
        "Are there team members or collaborators you depended on regularly that we should capture?",
        "Who would the next person in your role need to know about to hit the ground running?",
    ],
    "stakeholders": [
        "Are there client-side or internal stakeholders we haven't discussed?",
        "Who outside your immediate team had influence over decisions or priorities on this project?",
        "Which stakeholders would notice first if something went wrong after you left?",
    ],
    "systems": [
        "What systems or tools did you rely on that we haven't covered?",
        "Are there any internal tools, dashboards, or data sources central to your daily work?",
        "What would stop working first if you weren't available to maintain it?",
    ],
    "workflows": [
        "What workflows or procedures do you think are most at risk of being lost?",
        "Are there recurring processes that live mostly in your head rather than in documentation?",
        "Walk me through the most complex routine you handle — what are the steps, and who else is involved?",
    ],
    "risks": [
        "What would keep you up at night after you've left the project?",
        "What known issues have been deprioritized but could resurface?",
        "If something broke in the first month after your departure, what would it most likely be?",
    ],
    "undocumented_knowledge": [
        "What's something you know about this project that isn't written down anywhere?",
        "What workarounds or informal rules exist that a newcomer would only discover by making a mistake?",
        "What context or history would be most helpful for someone inheriting your responsibilities?",
    ],
}

# Multiple probe templates per node type.  {label} is replaced at call time;
# {label!r} adds surrounding quotes via repr().
_PROBE_VARIANTS: dict[str, list[str]] = {
    "Workflow": [
        "Can you walk me through the {label!r} workflow step by step, including who owns each part?",
        "Where does the {label!r} process begin and end, and what can go wrong in the middle?",
        "Who triggers {label!r} and who has to sign off before it's complete?",
    ],
    "System": [
        "Who owns and maintains {label!r}, and what would break if it went down overnight?",
        "How does {label!r} fit into the overall data flow — what feeds into it and what depends on it?",
        "What's the most fragile part of {label!r} that the next person needs to know about?",
    ],
    "Person": [
        "Can you tell me more about {label!r} — their role and how you worked together?",
        "How would you describe {label!r}'s involvement in the day-to-day work on this project?",
        "If {label!r} were unavailable for a week, what would stall or break?",
    ],
    "Document": [
        "Where does {label!r} live today, and how current is it?",
        "Who is responsible for keeping {label!r} up to date, and when was it last used?",
        "Is {label!r} the authoritative source for its topic, or are there other versions floating around?",
    ],
    "Risk": [
        "You mentioned the risk of {label!r} — what would the impact be and who else knows about it?",
        "Has {label!r} caused problems before, or is it a potential issue that hasn't surfaced yet?",
        "What would need to happen to mitigate {label!r} before your departure?",
    ],
    "Task": [
        "Can you describe the task {label!r} and its current status?",
        "Who else is aware of {label!r} and what would happen if it were left unfinished?",
        "What's blocking {label!r} right now, if anything?",
    ],
    "Decision": [
        "What was the context behind the decision {label!r}?",
        "Who made {label!r}, and was there significant disagreement or pushback at the time?",
        "Are there implications of {label!r} that haven't played out yet?",
    ],
    "Issue": [
        "What's the current state of the issue {label!r}?",
        "Who owns {label!r} and what's the path to resolution?",
        "Has {label!r} been escalated, or is it being tracked informally?",
    ],
    "Team": [
        "Can you describe the team {label!r} — who's on it and what they focus on?",
        "How does {label!r} interact with your work — are they a dependency, a customer, or a peer?",
        "Who is the main point of contact in {label!r} for the work you've been doing?",
    ],
    "Project": [
        "What's the current status of {label!r}?",
        "What's the single most important thing to know about {label!r} for whoever takes over?",
        "Are there any open threads or pending decisions in {label!r} that need to be resolved soon?",
    ],
    "Client": [
        "What's the nature of your relationship with {label!r}?",
        "Who on the {label!r} side is the primary contact, and what do they care about most?",
        "What's the most important commitment or expectation {label!r} has that the next person needs to honor?",
    ],
    "Role": [
        "What does the role {label!r} actually involve day-to-day?",
        "What informal responsibilities come with {label!r} that aren't in the job description?",
        "Who does {label!r} need to coordinate with most frequently?",
    ],
}


def _select_variant(session_id: str, key: str, variants: list[str]) -> str:
    """Deterministically pick a variant using a stable hash (not Python's hash())."""
    digest = int(hashlib.md5(f"{session_id}:{key}".encode()).hexdigest(), 16)
    return variants[digest % len(variants)]


# ── Public entry points ───────────────────────────────────────────────────────

def select_next_questions(
    state: SharedInterviewState, n: int = 5
) -> list[OrchestratorOutput]:
    """
    Return up to *n* candidate questions ranked by the priority ladder.

    Walks all four tiers and collects every available candidate across them,
    then returns the first *n* in priority order.  Callers can present a
    menu and let the user choose; the default (index 0) is the same question
    that select_next_question() would have returned.

    Pure function — does NOT mutate state.
    """
    candidates: list[OrchestratorOutput] = []
    candidates.extend(_ambiguity_questions(state))
    candidates.extend(_seeded_open_questions(state))
    candidates.extend(_probe_low_confidence_nodes(state))
    candidates.extend(_coverage_gap_fallbacks(state))

    # Deduplicate by question_id while preserving priority order.
    seen: set[str] = set()
    unique: list[OrchestratorOutput] = []
    for c in candidates:
        if c.question_id not in seen:
            seen.add(c.question_id)
            unique.append(c)

    return unique[:n]


def select_next_question(state: SharedInterviewState) -> OrchestratorOutput:
    """
    Pick the single most valuable next question given the current state.

    Pure function — does NOT mutate state. The turn loop is responsible for
    appending the resulting question_id to asked_question_ids.
    """
    return select_next_questions(state, n=1)[0]


# ── Priority 1: unresolved ambiguities ────────────────────────────────────────

def _ambiguity_questions(state: SharedInterviewState) -> list[OrchestratorOutput]:
    pending = [
        a for a in state.ambiguities
        if not a.resolved
        and _ambiguity_question_id(a.ambiguity_id) not in state.asked_question_ids
    ]
    pending.sort(key=lambda a: _PRIORITY_RANK[a.priority])
    return [
        OrchestratorOutput(
            next_question=a.suggested_question,
            rationale=f"Resolving ambiguity: {a.reason}",
            target_category="ambiguity_resolution",
            question_id=_ambiguity_question_id(a.ambiguity_id),
        )
        for a in pending
    ]


def _ambiguity_question(state: SharedInterviewState) -> OrchestratorOutput | None:
    qs = _ambiguity_questions(state)
    return qs[0] if qs else None


def _ambiguity_question_id(ambiguity_id: str) -> str:
    """Deterministic question_id so we do not re-ask the same ambiguity."""
    return f"q_amb_{ambiguity_id}"


# ── Priority 2: pending seeded open questions ─────────────────────────────────

def _seeded_open_questions(state: SharedInterviewState) -> list[OrchestratorOutput]:
    pending = [
        q for q in state.open_questions
        if q.question_id not in state.asked_question_ids
    ]
    pending.sort(key=lambda q: _PRIORITY_RANK[q.priority])
    return [
        OrchestratorOutput(
            next_question=q.text,
            rationale=q.rationale,
            target_category=q.target_category,
            question_id=q.question_id,
        )
        for q in pending
    ]


def _seeded_open_question(state: SharedInterviewState) -> OrchestratorOutput | None:
    qs = _seeded_open_questions(state)
    return qs[0] if qs else None


# ── Priority 3: lowest-confidence provisional node ────────────────────────────

def _probe_low_confidence_nodes(state: SharedInterviewState) -> list[OrchestratorOutput]:
    candidates = [
        n for n in state.graph.nodes
        if n.status == "provisional"
        and n.confidence < CONFIRMED_THRESHOLD
        and _probe_question_id(n.id) not in state.asked_question_ids
    ]
    candidates.sort(key=lambda n: n.confidence)
    return [
        OrchestratorOutput(
            next_question=_probe_question_for_node(n, state.session_id),
            rationale=(
                f"Node {n.id!r} ({n.type}, label={n.label!r}) "
                f"has confidence {n.confidence:.2f} — probing for more detail."
            ),
            target_category=_category_for_node_type(n.type),
            question_id=_probe_question_id(n.id),
        )
        for n in candidates
    ]


def _probe_low_confidence_node(state: SharedInterviewState) -> OrchestratorOutput | None:
    qs = _probe_low_confidence_nodes(state)
    return qs[0] if qs else None


def _probe_question_id(node_id: str) -> str:
    return f"q_probe_{node_id}"


def _probe_question_for_node(node: GraphNode, session_id: str) -> str:
    """Pick a targeted follow-up from the variant pool for this node type."""
    variants = _PROBE_VARIANTS.get(node.type)
    if not variants:
        return f"Can you tell me more about {node.label!r}?"
    template = _select_variant(session_id, f"probe:{node.id}", variants)
    return template.format(label=node.label)


def _category_for_node_type(node_type: NodeType) -> str:
    mapping: dict[NodeType, str] = {
        "Person": "people",
        "Team": "stakeholders",
        "Client": "stakeholders",
        "System": "systems",
        "Document": "systems",
        "Workflow": "workflows",
        "Risk": "risks",
        "Task": "undocumented_knowledge",
        "Decision": "undocumented_knowledge",
        "Issue": "undocumented_knowledge",
        "Project": "undocumented_knowledge",
        "Role": "people",
    }
    return mapping.get(node_type, "undocumented_knowledge")


# ── Priority 4: coverage-gap fallback ─────────────────────────────────────────

def _coverage_gap_fallbacks(state: SharedInterviewState) -> list[OrchestratorOutput]:
    cov = state.coverage
    scored: list[tuple[str, float]] = [
        ("people", cov.people),
        ("stakeholders", cov.stakeholders),
        ("systems", cov.systems),
        ("workflows", cov.workflows),
        ("risks", cov.risks),
        ("undocumented_knowledge", cov.undocumented_knowledge),
    ]
    scored.sort(key=lambda item: item[1])
    return [
        OrchestratorOutput(
            next_question=_fallback_question(cat, state.session_id),
            rationale=f"Coverage for {cat!r} is {score:.2f}; broadening the discussion.",
            target_category=cat,
        )
        for cat, score in scored
    ]


def _coverage_gap_fallback(state: SharedInterviewState) -> OrchestratorOutput:
    return _coverage_gap_fallbacks(state)[0]


def _fallback_question(category: str, session_id: str) -> str:
    variants = _FALLBACK_VARIANTS.get(category)
    if not variants:
        return "What else should the next person know?"
    return _select_variant(session_id, f"fallback:{category}", variants)
