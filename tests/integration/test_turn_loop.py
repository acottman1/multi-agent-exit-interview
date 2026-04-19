"""
Integration tests for the Phase 4 turn loop.

Focus areas:
  - The five extractors run concurrently, not sequentially.
  - One turn hits every stage: orchestrator → analyzers → graph mapper → updater.
  - Multi-turn run_interview respects max_turns and should_stop.
  - The pipeline wires through the real initial_state.json fixture.
"""
from __future__ import annotations

import asyncio
import time
from typing import Iterator

import pytest

from app.agents.stubs import STUB_DELAY_SECONDS
from app.core.models import (
    Clarification,
    ClarificationOutput,
    CoverageOutput,
    CoverageScores,
    EntityExtractionOutput,
    GraphMappingOutput,
    Interviewee,
    SharedInterviewState,
)
from app.graph.schema import GraphEdge, GraphNode, KnowledgeGraph
from app.interview import turn_loop
from app.interview.turn_loop import run_interview, run_turn
from app.ingestion.loaders import load_initial_state


INTERVIEWEE = Interviewee(
    name="Alex Miller",
    role="Contractor - Data Analyst",
    project_ids=["project_falcon"],
)


# ── Answer-provider helpers ───────────────────────────────────────────────────

def scripted(answers: list[str]):
    """Sync scripted answer provider — returns answers[0], answers[1], ..."""
    it: Iterator[str] = iter(answers)

    def provider(_question: str) -> str:
        try:
            return next(it)
        except StopIteration:
            return "(no further answer)"

    return provider


def async_scripted(answers: list[str]):
    """Async scripted answer provider to prove async callbacks work too."""
    it: Iterator[str] = iter(answers)

    async def provider(_question: str) -> str:
        try:
            return next(it)
        except StopIteration:
            return "(no further answer)"

    return provider


# ── Single-turn smoke test ────────────────────────────────────────────────────

class TestSingleTurn:
    async def test_run_turn_completes(self):
        state = load_initial_state(INTERVIEWEE)
        result = await run_turn(state, scripted(["Answer 1"]))
        assert result.turn.turn_number == 1
        assert result.turn.answer == "Answer 1"

    async def test_turn_is_appended_to_state(self):
        state = load_initial_state(INTERVIEWEE)
        await run_turn(state, scripted(["First answer"]))
        assert len(state.turns) == 1
        assert state.turns[0].answer == "First answer"

    async def test_question_id_tracked(self):
        state = load_initial_state(INTERVIEWEE)
        result = await run_turn(state, scripted(["Answer"]))
        assert result.orchestrator_output.question_id in state.asked_question_ids

    async def test_proposed_update_recorded(self):
        state = load_initial_state(INTERVIEWEE)
        await run_turn(state, scripted(["Answer"]))
        assert len(state.proposed_updates) == 1
        assert state.proposed_updates[0].committed is True

    async def test_first_question_targets_richard_ambiguity(self):
        """Given initial_state.json, the first question must resolve Richard."""
        state = load_initial_state(INTERVIEWEE)
        result = await run_turn(state, scripted(["Richard Jones on the client side."]))
        assert "Richard" in result.orchestrator_output.next_question
        assert result.orchestrator_output.target_category == "ambiguity_resolution"

    async def test_async_answer_provider_is_awaited(self):
        state = load_initial_state(INTERVIEWEE)
        result = await run_turn(state, async_scripted(["async answer"]))
        assert result.turn.answer == "async answer"


# ── Concurrency proof ─────────────────────────────────────────────────────────

class TestConcurrency:
    async def test_five_analyzers_run_in_parallel(self):
        """
        Each stub sleeps STUB_DELAY_SECONDS. Sequential would be 5 * delay.
        Parallel is ~1 * delay (plus the graph_mapper, which runs after).
        """
        state = load_initial_state(INTERVIEWEE)
        # Total = 5 analyzers in parallel (~delay) + 1 mapper (~delay) = ~2*delay
        # Sequential would be 6 * delay. Assert safely below 4 * delay.
        start = time.monotonic()
        await run_turn(state, scripted(["Answer"]))
        elapsed = time.monotonic() - start
        assert elapsed < 4 * STUB_DELAY_SECONDS, (
            f"Turn took {elapsed:.3f}s; suggests extractors ran sequentially."
        )

    async def test_analyzers_started_before_any_completed(self, monkeypatch):
        """
        Deterministic concurrency proof: instrument each stub so we capture
        start/end timestamps. If ANY analyzer finished before ALL started,
        the pipeline wasn't concurrent.
        """
        starts: list[float] = []
        ends: list[float] = []

        def make_tracked(empty_output_factory):
            async def tracked(*_args, **_kwargs):
                starts.append(time.monotonic())
                await asyncio.sleep(STUB_DELAY_SECONDS)
                ends.append(time.monotonic())
                return empty_output_factory()
            return tracked

        monkeypatch.setattr(turn_loop, "extract_entities",
                            make_tracked(lambda: EntityExtractionOutput(entities=[])))
        monkeypatch.setattr(turn_loop, "extract_relationships",
                            make_tracked(lambda: __import__(
                                "app.core.models", fromlist=["RelationshipExtractionOutput"]
                            ).RelationshipExtractionOutput(relationships=[])))
        monkeypatch.setattr(turn_loop, "extract_attributes",
                            make_tracked(lambda: __import__(
                                "app.core.models", fromlist=["AttributeExtractionOutput"]
                            ).AttributeExtractionOutput(attributes=[])))
        monkeypatch.setattr(turn_loop, "detect_clarifications",
                            make_tracked(lambda: ClarificationOutput(clarifications=[])))
        monkeypatch.setattr(turn_loop, "update_coverage",
                            make_tracked(lambda: CoverageOutput(
                                updated_scores=CoverageScores(),
                                priority_topics=[],
                                missing_categories=[],
                                rationale="",
                            )))

        state = load_initial_state(INTERVIEWEE)
        await run_turn(state, scripted(["Answer"]))

        # We captured 5 extractors + 1 mapper = 6 start/end pairs.
        assert len(starts) >= 5
        # All 5 extractors must have started before the first one ended.
        first_end = min(ends[:5])
        all_five_started_by = max(starts[:5])
        assert all_five_started_by <= first_end, (
            "Extractors appear to have run sequentially, not concurrently."
        )


# ── Multi-turn loop ───────────────────────────────────────────────────────────

class TestRunInterview:
    async def test_respects_max_turns(self):
        state = load_initial_state(INTERVIEWEE)
        results = await run_interview(
            state, scripted(["a", "b", "c", "d"]), max_turns=3,
        )
        assert len(results) == 3
        assert len(state.turns) == 3

    async def test_should_stop_short_circuits(self):
        state = load_initial_state(INTERVIEWEE)

        def stop_after_two(s: SharedInterviewState) -> bool:
            return len(s.turns) >= 2

        results = await run_interview(
            state, scripted(["a", "b", "c", "d", "e"]),
            max_turns=10, should_stop=stop_after_two,
        )
        assert len(results) == 2
        assert len(state.turns) == 2

    async def test_different_questions_per_turn(self):
        """The orchestrator should NOT ask the same question twice in a row."""
        state = load_initial_state(INTERVIEWEE)
        results = await run_interview(
            state, scripted(["a"] * 4), max_turns=4,
        )
        questions = [r.orchestrator_output.next_question for r in results]
        assert len(set(questions)) == len(questions), (
            f"Duplicate questions asked: {questions}"
        )

    async def test_asked_question_ids_accumulate(self):
        state = load_initial_state(INTERVIEWEE)
        await run_interview(state, scripted(["a"] * 3), max_turns=3)
        assert len(state.asked_question_ids) == 3
        assert len(set(state.asked_question_ids)) == 3


# ── Updater wiring ────────────────────────────────────────────────────────────

class TestUpdaterWiring:
    async def test_empty_stub_output_produces_empty_apply_result(self):
        """With all stubs returning empty, the updater has nothing to commit."""
        state = load_initial_state(INTERVIEWEE)
        result = await run_turn(state, scripted(["answer"]))
        assert result.apply_result.node_changes == []
        assert result.apply_result.edge_changes == []
        assert result.apply_result.has_rejections is False

    async def test_graph_is_not_mutated_by_empty_stubs(self):
        """Stubs are empty, so canonical graph must be unchanged."""
        state = load_initial_state(INTERVIEWEE)
        nodes_before = len(state.graph.nodes)
        edges_before = len(state.graph.edges)
        await run_turn(state, scripted(["answer"]))
        assert len(state.graph.nodes) == nodes_before
        assert len(state.graph.edges) == edges_before

    async def test_graph_mapper_output_reaches_updater(self, monkeypatch):
        """
        Patch the graph mapper to propose creating a new node, and verify
        that node appears in state.graph after the turn.
        """
        async def mapper_that_proposes_node(_e, _r, _a) -> GraphMappingOutput:
            from app.core.models import NodeUpdateOp
            new_node = GraphNode(
                id="person_new_from_stub",
                type="Person",
                label="New Person",
                confidence=0.85,
                provenance=["turn_stub_injection"],
            )
            return GraphMappingOutput(
                node_updates=[NodeUpdateOp(op="upsert", node=new_node)],
                edge_updates=[],
            )

        monkeypatch.setattr(
            turn_loop, "map_to_graph_updates", mapper_that_proposes_node
        )

        state = load_initial_state(INTERVIEWEE)
        await run_turn(state, scripted(["answer"]))
        node_ids = {n.id for n in state.graph.nodes}
        assert "person_new_from_stub" in node_ids
        new_node = next(n for n in state.graph.nodes if n.id == "person_new_from_stub")
        assert new_node.status == "confirmed"  # confidence 0.85 auto-promotes


# ── Clarifications feed back into open questions ──────────────────────────────

class TestClarificationFeedback:
    async def test_clarifications_become_open_questions(self, monkeypatch):
        async def clarification_stub(_turn, _aliases) -> ClarificationOutput:
            return ClarificationOutput(clarifications=[
                Clarification(
                    kind="ambiguous_entity",
                    target="some-thing",
                    reason="unclear",
                    suggested_question="Can you clarify that?",
                    priority="medium",
                )
            ])

        monkeypatch.setattr(turn_loop, "detect_clarifications", clarification_stub)

        state = load_initial_state(INTERVIEWEE)
        seeded_count = len(state.open_questions)
        await run_turn(state, scripted(["answer"]))
        assert len(state.open_questions) == seeded_count + 1
        assert state.open_questions[-1].text == "Can you clarify that?"
