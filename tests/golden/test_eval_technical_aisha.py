"""
Golden evaluation: "Technical Aisha" — Cybersecurity Compliance Transition

Research question: When a technical interviewee gives dense, terse, entity-rich
answers, does the pipeline capture the full system/control/ownership graph and
extract relationships correctly?

Pass criteria defined in tests/fixtures/golden_interviews/technical_aisha.py.
These tests call the real Anthropic API and are skipped without a key.
"""
from __future__ import annotations

import pytest

from app.ingestion.loaders import load_initial_state
from app.interview.turn_loop import run_interview
from tests.fixtures.golden_interviews import technical_aisha as fixture


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
async def test_priya_ambiguity_resolved():
    """Turn 1 names 'Priya Nair' in IT support; pipeline must resolve amb_cyber_001."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    amb = _find_ambiguity(state, fixture.RICHARD_AMBIGUITY_ID)
    assert amb is not None, "Ambiguity amb_cyber_001 missing from state"
    assert amb.resolved, "Priya ambiguity NOT resolved despite full name 'Priya Nair' given"


@pytest.mark.asyncio
async def test_all_required_labels_captured():
    """
    Aisha's terse answers are entity-dense. All REQUIRED_NODE_LABELS must be
    extracted including people, systems, and governance roles.
    """
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    labels = _node_labels(state)
    missing = [r for r in fixture.REQUIRED_NODE_LABELS
               if not any(r.lower() in l.lower() for l in labels)]
    assert not missing, f"Missing required nodes: {missing}\nActual: {sorted(labels)}"


@pytest.mark.asyncio
async def test_broad_coverage_increase():
    """Aisha's domain spans systems, workflows, knowledge gaps, and risks; all must rise."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    cov = state.coverage
    for category in fixture.EXPECTED_COVERAGE_ABOVE_ZERO:
        score = getattr(cov, category)
        assert score > 0.0, (
            f"Coverage for '{category}' still 0.0 after Aisha's detailed answers"
        )


@pytest.mark.asyncio
async def test_new_nodes_added():
    """At least MIN_NEW_NODES new nodes must appear (Priya Nair resolved from ambiguity)."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    initial = len(state.graph.nodes)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    new = len(state.graph.nodes) - initial
    assert new >= fixture.MIN_NEW_NODES, (
        f"Expected ≥{fixture.MIN_NEW_NODES} new nodes; got {new}. "
        f"Nodes: {sorted(_node_labels(state))}"
    )
