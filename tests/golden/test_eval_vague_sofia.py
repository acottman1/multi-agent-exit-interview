"""
Golden evaluation: "Vague Sofia" — Client Onboarding Operations Transfer

Research question: When an interviewee summarizes outcomes instead of steps, does the
pipeline correctly reject vague completion signals, generate heavy clarification probing,
and abstain from hallucinating operational detail that was never stated?

Pass criteria defined in tests/fixtures/golden_interviews/vague_sofia.py.
These tests call the real Anthropic API and are skipped without a key.
"""
from __future__ import annotations

import pytest

from app.ingestion.loaders import load_initial_state
from app.interview.turn_loop import run_interview
from tests.fixtures.golden_interviews import vague_sofia as fixture


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
async def test_technical_team_ambiguity_remains_unresolved():
    """
    Sofia's 'it depends on the client' answer is deliberately non-committal.
    The ambiguity must remain unresolved.
    """
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    amb = _find_ambiguity(state, fixture.RICHARD_AMBIGUITY_ID)
    assert amb is not None, "Ambiguity amb_onboard_001 missing from state"
    assert not amb.resolved, (
        "Ambiguity was incorrectly resolved despite a non-committal 'it depends' answer"
    )


@pytest.mark.asyncio
async def test_heavy_clarification_probing():
    """
    Vague outcome-level answers should trigger heavy clarification probing.
    At least MIN_TOTAL_CLARIFICATIONS must be generated across all turns.
    """
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    results = await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                                  max_turns=len(fixture.SCRIPTED_ANSWERS))
    total = _total_clarifications(results)
    assert total >= fixture.MIN_TOTAL_CLARIFICATIONS, (
        f"Expected ≥{fixture.MIN_TOTAL_CLARIFICATIONS} clarifications from vague "
        f"answers; got {total}."
    )


@pytest.mark.asyncio
async def test_coverage_stays_low():
    """High-level answers convey little documentable knowledge; no category should spike."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    cov = state.coverage
    for field in type(cov).model_fields:
        score = getattr(cov, field)
        assert score <= fixture.MAX_COVERAGE_SCORE, (
            f"Coverage[{field}] = {score:.2f} exceeds threshold {fixture.MAX_COVERAGE_SCORE}. "
            f"Outcome-level answers should not drive high scores."
        )


@pytest.mark.asyncio
async def test_graph_barely_grows():
    """Sofia's vague answers should not produce more than MAX_NEW_NODES new nodes."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    initial = len(state.graph.nodes)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    new = len(state.graph.nodes) - initial
    assert new <= fixture.MAX_NEW_NODES, (
        f"Graph grew by {new} from vague answers — expected ≤{fixture.MAX_NEW_NODES}. "
        f"Nodes: {sorted(_node_labels(state))}"
    )


@pytest.mark.asyncio
async def test_no_hallucinated_entities_from_vague_language():
    """Generic summary phrases must not be extracted as named graph entities."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    labels = _node_labels(state)
    hallucinated = [n for n in fixture.LABELS_THAT_MUST_NOT_EXIST
                    if any(n.lower() in l.lower() for l in labels)]
    assert not hallucinated, (
        f"Hallucinated nodes from vague language: {hallucinated}"
    )
