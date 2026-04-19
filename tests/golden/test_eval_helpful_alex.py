"""
Golden evaluation: "Helpful Alex"

Research question: When an interviewee gives clear, specific answers, does the
multi-agent pipeline capture named people, systems, and workflows accurately?

Pass criteria are defined in tests/fixtures/golden_interviews/helpful_alex.py.
These tests call the real Anthropic API and are skipped without a key.
"""
from __future__ import annotations

import pytest

from app.ingestion.loaders import load_initial_state
from app.interview.turn_loop import run_interview
from tests.fixtures.golden_interviews import helpful_alex as fixture


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


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_richard_ambiguity_is_resolved():
    """
    Turn 1 answer names 'Richard Jones' explicitly.
    The pipeline must mark amb_seed_001 as resolved.
    """
    state = load_initial_state(fixture.INTERVIEWEE)
    initial_node_count = len(state.graph.nodes)

    await run_interview(
        state,
        _scripted(fixture.SCRIPTED_ANSWERS),
        max_turns=len(fixture.SCRIPTED_ANSWERS),
    )

    amb = _find_ambiguity(state, fixture.RICHARD_AMBIGUITY_ID)
    assert amb is not None, "Ambiguity amb_seed_001 missing from state"
    assert amb.resolved, (
        "Richard ambiguity was NOT resolved despite interviewee naming 'Richard Jones'"
    )


@pytest.mark.asyncio
async def test_sarah_chen_captured():
    """
    Sarah Chen is first mentioned in turn 3. The entity extractor must create
    a Person node for her and the updater must commit it.
    """
    state = load_initial_state(fixture.INTERVIEWEE)
    await run_interview(
        state,
        _scripted(fixture.SCRIPTED_ANSWERS),
        max_turns=len(fixture.SCRIPTED_ANSWERS),
    )

    labels = _node_labels(state)
    assert any("Sarah Chen" in label or "Sarah" in label for label in labels), (
        f"Expected 'Sarah Chen' in graph nodes. Found: {sorted(labels)}"
    )


@pytest.mark.asyncio
async def test_marcus_wright_captured():
    """
    Marcus Wright (VP of Data at NorthStar) is mentioned in turn 2.
    He is not in initial_state.json so he must be newly extracted.
    """
    state = load_initial_state(fixture.INTERVIEWEE)
    await run_interview(
        state,
        _scripted(fixture.SCRIPTED_ANSWERS),
        max_turns=len(fixture.SCRIPTED_ANSWERS),
    )

    labels = _node_labels(state)
    assert any("Marcus" in label for label in labels), (
        f"Expected 'Marcus Wright' in graph nodes. Found: {sorted(labels)}"
    )


@pytest.mark.asyncio
async def test_coverage_increases_for_expected_categories():
    """
    Turns 2-4 address workflows, systems, and risks explicitly.
    Coverage for all three must have risen above 0.
    """
    state = load_initial_state(fixture.INTERVIEWEE)
    await run_interview(
        state,
        _scripted(fixture.SCRIPTED_ANSWERS),
        max_turns=len(fixture.SCRIPTED_ANSWERS),
    )

    cov = state.coverage
    for category in fixture.EXPECTED_COVERAGE_ABOVE_ZERO:
        score = getattr(cov, category)
        assert score > 0.0, (
            f"Coverage for '{category}' is still 0.0 after {len(fixture.SCRIPTED_ANSWERS)} turns"
        )


@pytest.mark.asyncio
async def test_new_nodes_added():
    """
    At least MIN_NEW_NODES nodes must appear in the graph that were not there
    before the interview (Sarah Chen + Marcus Wright at minimum).
    """
    state = load_initial_state(fixture.INTERVIEWEE)
    initial_count = len(state.graph.nodes)

    await run_interview(
        state,
        _scripted(fixture.SCRIPTED_ANSWERS),
        max_turns=len(fixture.SCRIPTED_ANSWERS),
    )

    new_count = len(state.graph.nodes) - initial_count
    assert new_count >= fixture.MIN_NEW_NODES, (
        f"Expected ≥{fixture.MIN_NEW_NODES} new nodes; got {new_count}. "
        f"Nodes: {sorted(_node_labels(state))}"
    )


@pytest.mark.asyncio
async def test_required_node_labels_present():
    """
    Parametrised check: every label in REQUIRED_NODE_LABELS must appear
    somewhere in the final graph (case-insensitive substring match).
    """
    state = load_initial_state(fixture.INTERVIEWEE)
    await run_interview(
        state,
        _scripted(fixture.SCRIPTED_ANSWERS),
        max_turns=len(fixture.SCRIPTED_ANSWERS),
    )

    labels = _node_labels(state)
    missing = []
    for required in fixture.REQUIRED_NODE_LABELS:
        if not any(required.lower() in label.lower() for label in labels):
            missing.append(required)

    assert not missing, (
        f"Missing required nodes: {missing}\nActual labels: {sorted(labels)}"
    )
