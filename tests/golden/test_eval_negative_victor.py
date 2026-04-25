"""
Golden evaluation: "Negative Victor" — Data Platform Contractor Exit

Research question: When an interviewee is frustrated and sarcastic, does the pipeline
still extract high-value risk and dependency signals without hallucinating entities
from venting language?

Pass criteria defined in tests/fixtures/golden_interviews/negative_victor.py.
These tests call the real Anthropic API and are skipped without a key.
"""
from __future__ import annotations

import pytest

from app.ingestion.loaders import load_initial_state
from app.interview.turn_loop import run_interview
from tests.fixtures.golden_interviews import negative_victor as fixture


# ── Helpers ───────────────────────────────────────────────────────────────────

def _scripted(answers):
    it = iter(answers)
    def provider(_q): return next(it, "(no further answer)")
    return provider

def _node_labels(state) -> set[str]:
    return {n.label for n in state.graph.nodes}

def _find_ambiguity(state, ambiguity_id):
    return next((a for a in state.ambiguities if a.ambiguity_id == ambiguity_id), None)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_priyanka_ambiguity_resolved():
    """Turn 1 names 'Priyanka Suresh' on analytics; pipeline must resolve amb_data_001."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    amb = _find_ambiguity(state, fixture.RICHARD_AMBIGUITY_ID)
    assert amb is not None, "Ambiguity amb_data_001 missing from state"
    assert amb.resolved, "Priyanka ambiguity NOT resolved despite explicit full name given"


@pytest.mark.asyncio
async def test_required_entities_captured_despite_frustration():
    """
    Victor's frustration carries real signal. All REQUIRED_NODE_LABELS must be
    extracted regardless of his negative tone.
    """
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    labels = _node_labels(state)
    missing = [r for r in fixture.REQUIRED_NODE_LABELS
               if not any(r.lower() in l.lower() for l in labels)]
    assert not missing, f"Missing nodes: {missing}\nActual: {sorted(labels)}"


@pytest.mark.asyncio
async def test_no_hallucinated_entities_from_venting():
    """Generic organizational terms from venting must not become graph entities."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    labels = _node_labels(state)
    hallucinated = [n for n in fixture.LABELS_THAT_MUST_NOT_EXIST
                    if any(n.lower() in l.lower() for l in labels)]
    assert not hallucinated, (
        f"Hallucinated nodes from venting language: {hallucinated}"
    )


@pytest.mark.asyncio
async def test_risk_and_knowledge_coverage_increases():
    """Victor's answers are rich in risk and undocumented knowledge; both must rise above 0."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    cov = state.coverage
    for category in fixture.EXPECTED_COVERAGE_ABOVE_ZERO:
        score = getattr(cov, category)
        assert score > 0.0, (
            f"Coverage for '{category}' still 0.0 despite Victor's explicit descriptions"
        )


@pytest.mark.asyncio
async def test_new_nodes_added():
    """At least MIN_NEW_NODES new nodes must be created (Priyanka Suresh at minimum)."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    initial = len(state.graph.nodes)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    new = len(state.graph.nodes) - initial
    assert new >= fixture.MIN_NEW_NODES, (
        f"Expected ≥{fixture.MIN_NEW_NODES} new nodes; got {new}. "
        f"Nodes: {sorted(_node_labels(state))}"
    )
