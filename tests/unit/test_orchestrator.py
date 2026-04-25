"""
Unit tests for app/agents/orchestrator.py.

These tests pin the priority ladder so a future LLM-backed orchestrator
cannot silently change interview behaviour without updating the tests.
"""
from __future__ import annotations

import pytest

from app.agents.orchestrator import select_next_question
from app.core.models import (
    Ambiguity,
    CoverageScores,
    Interviewee,
    OpenQuestion,
    OrchestratorOutput,
    SharedInterviewState,
)
from app.graph.schema import GraphNode, KnowledgeGraph

INTERVIEWEE = Interviewee(
    name="Alex Miller",
    role="Contractor - Data Analyst",
    project_ids=["project_falcon"],
)


def _state(**overrides) -> SharedInterviewState:
    base = {"interviewee": INTERVIEWEE}
    base.update(overrides)
    return SharedInterviewState(**base)


def _ambiguity(
    ambiguity_id: str = "amb_001",
    priority: str = "high",
    resolved: bool = False,
    suggested: str = "Which Richard did you mean?",
) -> Ambiguity:
    return Ambiguity(
        ambiguity_id=ambiguity_id,
        kind="ambiguous_entity",
        target="Richard",
        reason="Two candidates share the alias 'Richard'.",
        suggested_question=suggested,
        priority=priority,  # type: ignore[arg-type]
        source_turn_id="seed",
        resolved=resolved,
    )


def _open_q(
    question_id: str = "q_001",
    text: str = "How does the change request workflow end?",
    priority: str = "medium",
    target: str = "workflows",
) -> OpenQuestion:
    return OpenQuestion(
        question_id=question_id,
        text=text,
        rationale="Seeded from ingestion.",
        target_category=target,
        priority=priority,  # type: ignore[arg-type]
    )


def _node(
    node_id: str = "workflow_cr",
    node_type: str = "Workflow",
    label: str = "Change Request Workflow",
    confidence: float = 0.45,
    status: str = "provisional",
) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=node_type,  # type: ignore[arg-type]
        label=label,
        confidence=confidence,
        status=status,  # type: ignore[arg-type]
        provenance=["source_a"],
    )


# ── Priority 1: ambiguities beat everything ───────────────────────────────────

class TestPriorityAmbiguities:
    def test_unresolved_ambiguity_wins_over_open_question(self):
        state = _state(
            ambiguities=[_ambiguity()],
            open_questions=[_open_q(priority="high")],
        )
        out = select_next_question(state)
        assert out.target_category == "ambiguity_resolution"
        assert out.next_question == "Which Richard did you mean?"

    def test_unresolved_ambiguity_wins_over_low_confidence_node(self):
        state = _state(
            ambiguities=[_ambiguity()],
            graph=KnowledgeGraph(nodes=[_node(confidence=0.20)]),
        )
        out = select_next_question(state)
        assert out.target_category == "ambiguity_resolution"

    def test_resolved_ambiguity_is_ignored(self):
        state = _state(
            ambiguities=[_ambiguity(resolved=True)],
            open_questions=[_open_q(priority="high", text="Fallback question")],
        )
        out = select_next_question(state)
        assert out.next_question == "Fallback question"

    def test_high_priority_ambiguity_beats_medium(self):
        state = _state(
            ambiguities=[
                _ambiguity("amb_low", priority="medium", suggested="Medium Q"),
                _ambiguity("amb_high", priority="high", suggested="High Q"),
            ]
        )
        out = select_next_question(state)
        assert out.next_question == "High Q"

    def test_question_id_is_deterministic_for_ambiguity(self):
        state = _state(ambiguities=[_ambiguity(ambiguity_id="amb_001")])
        out = select_next_question(state)
        assert out.question_id == "q_amb_amb_001"

    def test_already_asked_ambiguity_is_skipped(self):
        state = _state(
            ambiguities=[_ambiguity(ambiguity_id="amb_001")],
            asked_question_ids=["q_amb_amb_001"],
            open_questions=[_open_q(text="Seeded fallback")],
        )
        out = select_next_question(state)
        assert out.next_question == "Seeded fallback"


# ── Priority 2: seeded open questions ─────────────────────────────────────────

class TestPrioritySeededQuestions:
    def test_highest_priority_open_question_is_selected(self):
        state = _state(
            open_questions=[
                _open_q("q_med", text="Medium Q", priority="medium"),
                _open_q("q_hi", text="High Q", priority="high"),
                _open_q("q_lo", text="Low Q", priority="low"),
            ]
        )
        out = select_next_question(state)
        assert out.next_question == "High Q"
        assert out.question_id == "q_hi"

    def test_already_asked_question_is_skipped(self):
        state = _state(
            open_questions=[
                _open_q("q_asked", text="Asked already", priority="high"),
                _open_q("q_new", text="Pending", priority="medium"),
            ],
            asked_question_ids=["q_asked"],
        )
        out = select_next_question(state)
        assert out.next_question == "Pending"

    def test_target_category_is_preserved(self):
        state = _state(open_questions=[_open_q(target="workflows")])
        out = select_next_question(state)
        assert out.target_category == "workflows"


# ── Priority 3: probe low-confidence provisional nodes ────────────────────────

class TestPriorityLowConfidenceNode:
    def test_lowest_confidence_provisional_node_is_probed(self):
        state = _state(
            graph=KnowledgeGraph(nodes=[
                _node("n_high", confidence=0.75),
                _node("n_low", confidence=0.30, label="Weak Node"),
                _node("n_mid", confidence=0.60),
            ])
        )
        out = select_next_question(state)
        assert "Weak Node" in out.next_question
        assert out.question_id == "q_probe_n_low"

    def test_confirmed_nodes_are_ignored(self):
        state = _state(
            graph=KnowledgeGraph(nodes=[
                _node("confirmed_node", confidence=0.95, status="confirmed"),
            ])
        )
        out = select_next_question(state)
        # No probe candidates → falls through to coverage fallback
        assert not out.question_id.startswith("q_probe_")

    def test_superseded_nodes_are_ignored(self):
        state = _state(
            graph=KnowledgeGraph(nodes=[
                _node("superseded_node", confidence=0.30, status="superseded"),
            ])
        )
        out = select_next_question(state)
        assert not out.question_id.startswith("q_probe_")

    def test_workflow_node_gets_workflow_template(self):
        state = _state(graph=KnowledgeGraph(nodes=[_node(
            "workflow_cr", "Workflow", "Change Request Workflow", confidence=0.45
        )]))
        out = select_next_question(state)
        assert "Change Request Workflow" in out.next_question
        assert out.target_category == "workflows"

    def test_system_node_gets_system_template(self):
        state = _state(graph=KnowledgeGraph(nodes=[_node(
            "system_snowflake", "System", "Snowflake", confidence=0.55
        )]))
        out = select_next_question(state)
        assert "Snowflake" in out.next_question
        assert out.target_category == "systems"

    def test_already_probed_node_is_skipped(self):
        state = _state(
            graph=KnowledgeGraph(nodes=[
                _node("n1", confidence=0.30),
                _node("n2", confidence=0.40),
            ]),
            asked_question_ids=["q_probe_n1"],
        )
        out = select_next_question(state)
        assert out.question_id == "q_probe_n2"


# ── Priority 4: coverage-gap fallback ─────────────────────────────────────────

class TestCoverageGapFallback:
    def test_fallback_when_nothing_else_to_ask(self):
        state = _state()  # no ambiguities, no open questions, empty graph
        out = select_next_question(state)
        assert isinstance(out, OrchestratorOutput)
        assert out.next_question  # some non-empty string

    def test_fallback_picks_weakest_coverage_category(self):
        state = _state(coverage=CoverageScores(
            people=0.8, stakeholders=0.7, systems=0.9,
            workflows=0.1, risks=0.6, undocumented_knowledge=0.5,
        ))
        out = select_next_question(state)
        assert out.target_category == "workflows"

    def test_fallback_rationale_mentions_coverage_score(self):
        state = _state()
        out = select_next_question(state)
        assert "coverage" in out.rationale.lower()


# ── Golden-path: using the actual initial_state.json ──────────────────────────

class TestAgainstInitialState:
    """End-to-end: the orchestrator must ask about the Richard ambiguity first."""

    def test_first_question_is_richard_ambiguity(self):
        from app.ingestion.loaders import load_initial_state
        state = load_initial_state(INTERVIEWEE)
        out = select_next_question(state)
        assert out.target_category == "ambiguity_resolution"
        assert "Richard" in out.next_question

    def test_after_richard_resolved_moves_to_highest_priority_seed(self):
        from app.ingestion.loaders import load_initial_state
        state = load_initial_state(INTERVIEWEE)
        # Simulate the orchestrator having asked about Richard
        state.ambiguities[0].resolved = True
        out = select_next_question(state)
        # Next should be one of the three high-priority seeded questions
        assert out.question_id in {"q_seed_001", "q_seed_002", "q_seed_003"}
