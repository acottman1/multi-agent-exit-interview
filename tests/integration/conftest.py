"""
Integration-test fixtures.

The integration tests exercise the full turn-loop pipeline but must not make
real Anthropic API calls. This conftest patches each LLM-backed agent binding
in turn_loop back to the corresponding stub so all integration tests remain
fast, deterministic, and API-key-free.

Tests that need to probe specific agent behaviour (e.g. TestConcurrency,
TestUpdaterWiring.test_graph_mapper_output_reaches_updater) apply their own
monkeypatches which override these autouse patches within that test.
"""
import pytest

from app.agents.stubs import (
    detect_clarifications,
    extract_attributes,
    extract_entities,
    extract_relationships,
    map_to_graph_updates,
    update_coverage,
)
from app.interview import turn_loop


@pytest.fixture(autouse=True)
def patch_agents_to_stubs(monkeypatch):
    """Replace real LLM agents with stubs for every integration test."""
    monkeypatch.setattr(turn_loop, "extract_entities", extract_entities)
    monkeypatch.setattr(turn_loop, "extract_relationships", extract_relationships)
    monkeypatch.setattr(turn_loop, "extract_attributes", extract_attributes)
    monkeypatch.setattr(turn_loop, "detect_clarifications", detect_clarifications)
    monkeypatch.setattr(turn_loop, "update_coverage", update_coverage)
    monkeypatch.setattr(turn_loop, "map_to_graph_updates", map_to_graph_updates)
