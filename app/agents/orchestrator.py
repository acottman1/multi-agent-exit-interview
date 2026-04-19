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

from app.core.models import (
    ClarificationPriority,
    OrchestratorOutput,
    SharedInterviewState,
)
from app.graph.schema import GraphNode, NodeType
from app.graph.updater import CONFIRMED_THRESHOLD

# Lower rank integer = higher priority.
_PRIORITY_RANK: dict[ClarificationPriority, int] = {"high": 0, "medium": 1, "low": 2}


def select_next_question(state: SharedInterviewState) -> OrchestratorOutput:
    """
    Pick the most valuable next question given the current state.

    Pure function — does NOT mutate state. The turn loop is responsible for
    appending the resulting question_id to asked_question_ids.
    """
    if (amb_q := _ambiguity_question(state)) is not None:
        return amb_q

    if (seeded_q := _seeded_open_question(state)) is not None:
        return seeded_q

    if (probe_q := _probe_low_confidence_node(state)) is not None:
        return probe_q

    return _coverage_gap_fallback(state)


# ── Priority 1: unresolved ambiguities ────────────────────────────────────────

def _ambiguity_question(state: SharedInterviewState) -> OrchestratorOutput | None:
    pending = [
        a for a in state.ambiguities
        if not a.resolved
        and _ambiguity_question_id(a.ambiguity_id) not in state.asked_question_ids
    ]
    if not pending:
        return None

    pending.sort(key=lambda a: _PRIORITY_RANK[a.priority])
    amb = pending[0]
    return OrchestratorOutput(
        next_question=amb.suggested_question,
        rationale=f"Resolving ambiguity: {amb.reason}",
        target_category="ambiguity_resolution",
        question_id=_ambiguity_question_id(amb.ambiguity_id),
    )


def _ambiguity_question_id(ambiguity_id: str) -> str:
    """Deterministic question_id so we do not re-ask the same ambiguity."""
    return f"q_amb_{ambiguity_id}"


# ── Priority 2: pending seeded open questions ─────────────────────────────────

def _seeded_open_question(state: SharedInterviewState) -> OrchestratorOutput | None:
    pending = [
        q for q in state.open_questions
        if q.question_id not in state.asked_question_ids
    ]
    if not pending:
        return None

    pending.sort(key=lambda q: _PRIORITY_RANK[q.priority])
    q = pending[0]
    return OrchestratorOutput(
        next_question=q.text,
        rationale=q.rationale,
        target_category=q.target_category,
        question_id=q.question_id,
    )


# ── Priority 3: lowest-confidence provisional node ────────────────────────────

def _probe_low_confidence_node(state: SharedInterviewState) -> OrchestratorOutput | None:
    candidates = [
        n for n in state.graph.nodes
        if n.status == "provisional"
        and n.confidence < CONFIRMED_THRESHOLD
        and _probe_question_id(n.id) not in state.asked_question_ids
    ]
    if not candidates:
        return None

    candidates.sort(key=lambda n: n.confidence)
    weakest = candidates[0]
    return OrchestratorOutput(
        next_question=_probe_question_for_node(weakest),
        rationale=(
            f"Node {weakest.id!r} ({weakest.type}, label={weakest.label!r}) "
            f"has confidence {weakest.confidence:.2f} — probing for more detail."
        ),
        target_category=_category_for_node_type(weakest.type),
        question_id=_probe_question_id(weakest.id),
    )


def _probe_question_id(node_id: str) -> str:
    return f"q_probe_{node_id}"


def _probe_question_for_node(node: GraphNode) -> str:
    """Targeted follow-up template per node type."""
    templates: dict[NodeType, str] = {
        "Workflow": f"Can you walk me through the {node.label!r} workflow step by step, including who owns each part?",
        "System": f"Who owns and maintains {node.label!r}, and what would break if it went down overnight?",
        "Person": f"Can you tell me more about {node.label!r} — their role and how you worked together?",
        "Document": f"Where does {node.label!r} live today, and how current is it?",
        "Risk": f"You mentioned the risk of {node.label!r} — what would the impact be and who else knows about it?",
        "Task": f"Can you describe the task {node.label!r} and its current status?",
        "Decision": f"What was the context behind the decision {node.label!r}?",
        "Issue": f"What's the current state of the issue {node.label!r}?",
        "Team": f"Can you describe the team {node.label!r} — who's on it and what they focus on?",
        "Project": f"What's the current status of {node.label!r}?",
        "Client": f"What's the nature of your relationship with {node.label!r}?",
        "Role": f"What does the role {node.label!r} actually involve day-to-day?",
    }
    return templates.get(node.type, f"Can you tell me more about {node.label!r}?")


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

def _coverage_gap_fallback(state: SharedInterviewState) -> OrchestratorOutput:
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
    weakest_cat, weakest_score = scored[0]
    return OrchestratorOutput(
        next_question=_fallback_question(weakest_cat),
        rationale=f"Coverage for {weakest_cat!r} is {weakest_score:.2f}; broadening the discussion.",
        target_category=weakest_cat,
    )


def _fallback_question(category: str) -> str:
    prompts = {
        "people": "Who else did you work with day-to-day that we haven't talked about yet?",
        "stakeholders": "Are there client-side or internal stakeholders we haven't discussed?",
        "systems": "What systems or tools did you rely on that we haven't covered?",
        "workflows": "What workflows or procedures do you think are most at risk of being lost?",
        "risks": "What would keep you up at night after you've left the project?",
        "undocumented_knowledge": "What's something you know about this project that isn't written down anywhere?",
    }
    return prompts.get(category, "What else should the next person know?")
