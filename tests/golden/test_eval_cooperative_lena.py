"""
Golden evaluation: "Cooperative Lena" — ERP Modernization Handoff

Research question: When a cooperative interviewee describes a complex cross-functional
engagement, does the pipeline accurately capture stakeholder relationships, undocumented
workflow deviations, and key dependencies?

Pass criteria defined in tests/fixtures/golden_interviews/cooperative_lena.py.
These tests call the real Anthropic API and are skipped without a key.
"""
from __future__ import annotations

import pytest

from app.ingestion.loaders import load_initial_state
from app.interview.turn_loop import run_interview
from tests.fixtures.golden_interviews import cooperative_lena as fixture


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
async def test_marcus_ambiguity_resolved():
    """Turn 1 names 'Marcus Lee' explicitly; pipeline must resolve amb_erp_001."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    amb = _find_ambiguity(state, fixture.RICHARD_AMBIGUITY_ID)
    assert amb is not None, "Ambiguity amb_erp_001 missing from state"
    assert amb.resolved, "Marcus ambiguity was NOT resolved despite explicit naming"


@pytest.mark.asyncio
async def test_janelle_brooks_captured():
    """
    Janelle Brooks is not in the seed. She is mentioned in turn 2 as the undocumented
    operations dependency. The pipeline must extract and add her.
    """
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    labels = _node_labels(state)
    assert any("Janelle" in label for label in labels), (
        f"Expected 'Janelle Brooks' in graph. Found: {sorted(labels)}"
    )


@pytest.mark.asyncio
async def test_elena_ruiz_captured():
    """Elena Ruiz is first mentioned in turn 4; must be extracted as a Person node."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    labels = _node_labels(state)
    assert any("Elena" in label for label in labels), (
        f"Expected 'Elena Ruiz' in graph. Found: {sorted(labels)}"
    )


@pytest.mark.asyncio
async def test_coverage_increases_for_expected_categories():
    """Turns 2-4 address workflows, undocumented knowledge, and risks; all must rise above 0."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    cov = state.coverage
    for category in fixture.EXPECTED_COVERAGE_ABOVE_ZERO:
        score = getattr(cov, category)
        assert score > 0.0, f"Coverage for '{category}' is still 0.0 after all turns"


@pytest.mark.asyncio
async def test_new_nodes_added():
    """At least MIN_NEW_NODES new nodes must appear (Janelle + Elena at minimum)."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    initial = len(state.graph.nodes)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    new = len(state.graph.nodes) - initial
    assert new >= fixture.MIN_NEW_NODES, (
        f"Expected ≥{fixture.MIN_NEW_NODES} new nodes; got {new}. "
        f"Nodes: {sorted(_node_labels(state))}"
    )


@pytest.mark.asyncio
async def test_all_required_labels_present():
    """Every label in REQUIRED_NODE_LABELS must appear in the final graph."""
    state = load_initial_state(fixture.INTERVIEWEE, path=fixture.SEED_PATH)
    await run_interview(state, _scripted(fixture.SCRIPTED_ANSWERS),
                        max_turns=len(fixture.SCRIPTED_ANSWERS))
    labels = _node_labels(state)
    missing = [r for r in fixture.REQUIRED_NODE_LABELS
               if not any(r.lower() in l.lower() for l in labels)]
    assert not missing, f"Missing required nodes: {missing}\nActual: {sorted(labels)}"
