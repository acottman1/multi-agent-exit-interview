"""
Golden evaluation: "Timid Noah" — Cloud Migration Support Rollover

Research question: When an interviewee is hesitant and gives partial answers,
does the pipeline generate sufficient clarification probes without over-extracting
entities from hedging language?

Pass criteria defined in tests/fixtures/golden_interviews/timid_noah.py.
These tests call the real Anthropic API and are skipped without a key.
"""
from __future__ import annotations

import pytest

from app.ingestion.loaders import load_initial_state
from app.interview.turn_loop import run_interview
from tests.fixtures.golden_interviews import timid_noah as fixture


# ── Helpers ───────────────────────────────────────────────────────────────────

def _scripted(answers):
    it = iter(answers)
    def provider(_q): return next(it, "(no further answer)")
    return provider

def _node_labels(state) -> set[str]:
    return {n.label for n in state.graph.nodes}

def _find_ambiguity(state, ambiguity_id):
    return next((a for a in state.ambiguities if a.ambiguity_id == ambiguity_id), None)

def _total_clarifications(results) -> int:
    return sum(
        len(r.proposed_update.clarifications.clarifications)
        for r in results
        if r.proposed_update.clarifications
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rachel_ambiguity_resolved():
    """Turn 1 names 'Rachel Kim' from app support; pipeline must resolve amb_cloud_001."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    amb = _find_ambiguity(state, fixture.RICHARD_AMBIGUITY_ID)
    assert amb is not None, "Ambiguity amb_cloud_001 missing from state"
    assert amb.resolved, "Rachel ambiguity was NOT resolved despite explicit naming"


@pytest.mark.asyncio
async def test_clarifications_generated_for_hedging_answers():
    """
    Noah's vague/hedging answers should trigger clarification probes.
    At least MIN_TOTAL_CLARIFICATIONS must be generated.
    """
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    results = await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                                  max_turns=len(fixture.SCRIPTED_ANSWERS))
    total = _total_clarifications(results)
    assert total >= fixture.MIN_TOTAL_CLARIFICATIONS, (
        f"Expected ≥{fixture.MIN_TOTAL_CLARIFICATIONS} clarifications from hesitant "
        f"answers; got {total}."
    )


@pytest.mark.asyncio
async def test_graph_does_not_over_grow():
    """Partial answers should not produce more than MAX_NEW_NODES new nodes."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    initial = len(state.graph.nodes)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    new = len(state.graph.nodes) - initial
    assert new <= fixture.MAX_NEW_NODES, (
        f"Graph grew by {new} nodes from hesitant answers — "
        f"expected ≤{fixture.MAX_NEW_NODES}. Nodes: {sorted(_node_labels(state))}"
    )


@pytest.mark.asyncio
async def test_coverage_stays_moderate():
    """Noah's incomplete answers should not push any category above MAX_COVERAGE_SCORE."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    cov = state.coverage
    for field in type(cov).model_fields:
        score = getattr(cov, field)
        assert score <= fixture.MAX_COVERAGE_SCORE, (
            f"Coverage[{field}] = {score:.2f} exceeds threshold {fixture.MAX_COVERAGE_SCORE}. "
            f"Hesitant answers should not drive high scores."
        )


@pytest.mark.asyncio
async def test_no_hallucinated_entities_from_hedging():
    """Generic hedging phrases must not be extracted as named entities."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    labels = _node_labels(state)
    hallucinated = [n for n in fixture.LABELS_THAT_MUST_NOT_EXIST
                    if any(n.lower() in l.lower() for l in labels)]
    assert not hallucinated, (
        f"Hallucinated nodes from hedging language: {hallucinated}"
    )
