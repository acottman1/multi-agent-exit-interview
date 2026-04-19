"""
Golden evaluation: "Vague Jordan"

Research question: When an interviewee gives evasive, content-free answers,
does the pipeline correctly abstain from hallucinating knowledge, surface
clarification needs, and leave coverage low?

Pass criteria are defined in tests/fixtures/golden_interviews/vague_jordan.py.
These tests call the real Anthropic API and are skipped without a key.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.ingestion.loaders import load_initial_state
from app.interview.turn_loop import run_interview
from tests.fixtures.golden_interviews import vague_jordan as fixture


# ── Helper ────────────────────────────────────────────────────────────────────

def _scripted(answers: list[str]):
    it = iter(answers)
    def provider(_question: str) -> str:
        return next(it, "(no further answer)")
    return provider


def _node_labels(state) -> set[str]:
    return {n.label for n in state.graph.nodes}


def _find_ambiguity(state, ambiguity_id: str):
    return next(
        (a for a in state.ambiguities if a.ambiguity_id == ambiguity_id), None
    )


def _total_clarifications(results) -> int:
    total = 0
    for r in results:
        if r.proposed_update.clarifications:
            total += len(r.proposed_update.clarifications.clarifications)
    return total


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_richard_ambiguity_remains_unresolved():
    """
    Jordan's answer 'I'm not sure which Richard that was' is deliberately
    non-committal. The ambiguity must stay unresolved.
    """
    state = load_initial_state(fixture.INTERVIEWEE)
    await run_interview(
        state,
        _scripted(fixture.SCRIPTED_ANSWERS),
        max_turns=len(fixture.SCRIPTED_ANSWERS),
    )

    amb = _find_ambiguity(state, fixture.RICHARD_AMBIGUITY_ID)
    assert amb is not None
    assert not amb.resolved, (
        "Richard ambiguity was incorrectly resolved despite a non-committal answer."
    )


@pytest.mark.asyncio
async def test_no_hallucinated_named_entities():
    """
    Sarah Chen and Marcus Wright were never mentioned by Jordan. They must NOT
    appear in the graph — the extractors must not hallucinate from prior turns
    or model knowledge.
    """
    state = load_initial_state(fixture.INTERVIEWEE)
    await run_interview(
        state,
        _scripted(fixture.SCRIPTED_ANSWERS),
        max_turns=len(fixture.SCRIPTED_ANSWERS),
    )

    labels = _node_labels(state)
    hallucinated = [
        name for name in fixture.LABELS_THAT_MUST_NOT_EXIST
        if any(name.lower() in label.lower() for label in labels)
    ]
    assert not hallucinated, (
        f"Pipeline hallucinated nodes that were never mentioned: {hallucinated}"
    )


@pytest.mark.asyncio
async def test_clarifications_generated_for_vague_answers():
    """
    Vague answers should trigger clarification requests. At least
    MIN_TOTAL_CLARIFICATIONS must be generated across all turns.
    """
    state = load_initial_state(fixture.INTERVIEWEE)
    results = await run_interview(
        state,
        _scripted(fixture.SCRIPTED_ANSWERS),
        max_turns=len(fixture.SCRIPTED_ANSWERS),
    )

    total = _total_clarifications(results)
    assert total >= fixture.MIN_TOTAL_CLARIFICATIONS, (
        f"Expected ≥{fixture.MIN_TOTAL_CLARIFICATIONS} clarifications; "
        f"got {total}. Vague answers should trigger follow-up questions."
    )


@pytest.mark.asyncio
async def test_coverage_stays_low():
    """
    No category should exceed MAX_COVERAGE_SCORE — vague answers convey
    almost no documentable knowledge.
    """
    state = load_initial_state(fixture.INTERVIEWEE)
    await run_interview(
        state,
        _scripted(fixture.SCRIPTED_ANSWERS),
        max_turns=len(fixture.SCRIPTED_ANSWERS),
    )

    cov = state.coverage
    for field in cov.model_fields:
        score = getattr(cov, field)
        assert score <= fixture.MAX_COVERAGE_SCORE, (
            f"Coverage for '{field}' is {score:.2f}, exceeds threshold "
            f"{fixture.MAX_COVERAGE_SCORE}. Vague answers should not drive "
            f"high coverage scores."
        )


@pytest.mark.asyncio
async def test_graph_barely_grows():
    """
    Graph node count must not grow by more than MAX_NEW_NODES. Vague answers
    should not produce a flood of low-quality provisional nodes.
    """
    state = load_initial_state(fixture.INTERVIEWEE)
    initial_count = len(state.graph.nodes)

    await run_interview(
        state,
        _scripted(fixture.SCRIPTED_ANSWERS),
        max_turns=len(fixture.SCRIPTED_ANSWERS),
    )

    new_count = len(state.graph.nodes) - initial_count
    assert new_count <= fixture.MAX_NEW_NODES, (
        f"Graph grew by {new_count} nodes from vague answers — "
        f"expected ≤{fixture.MAX_NEW_NODES}. "
        f"Possible hallucination: {sorted(_node_labels(state))}"
    )
