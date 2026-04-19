"""
Unit tests for Phase 2: initial_state.json loader.

All tests are pure in-process — no LLM calls, no network I/O.
"""
import json
import pytest
from pathlib import Path

from app.core.models import Interviewee, SharedInterviewState
from app.ingestion.loaders import load_initial_state, validate_graph_integrity


DUMMY_PATH = Path(__file__).parents[2] / "app" / "ingestion" / "dummy_data" / "initial_state.json"

ALEX = Interviewee(
    name="Alex Miller",
    role="Contractor - Data Analyst",
    project_ids=["project_falcon"],
)


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def loaded_state() -> SharedInterviewState:
    return load_initial_state(ALEX)


# ── Happy-path load ───────────────────────────────────────────────────────────

class TestLoadInitialState:
    def test_returns_shared_interview_state(self, loaded_state):
        assert isinstance(loaded_state, SharedInterviewState)

    def test_interviewee_is_injected(self, loaded_state):
        assert loaded_state.interviewee.name == "Alex Miller"

    def test_graph_has_nodes(self, loaded_state):
        assert len(loaded_state.graph.nodes) > 0

    def test_graph_has_edges(self, loaded_state):
        assert len(loaded_state.graph.edges) > 0

    def test_expected_node_count(self, loaded_state):
        assert len(loaded_state.graph.nodes) == 13

    def test_expected_edge_count(self, loaded_state):
        assert len(loaded_state.graph.edges) == 9

    def test_seed_open_questions_loaded(self, loaded_state):
        assert len(loaded_state.open_questions) == 3

    def test_seed_ambiguities_loaded(self, loaded_state):
        assert len(loaded_state.ambiguities) == 1

    def test_seed_ambiguity_is_about_richard(self, loaded_state):
        amb = loaded_state.ambiguities[0]
        assert amb.target == "Richard"
        assert amb.resolved is False
        assert amb.priority == "high"

    def test_coverage_starts_at_zero(self, loaded_state):
        cov = loaded_state.coverage
        assert cov.people == 0.0
        assert cov.systems == 0.0
        assert cov.workflows == 0.0

    def test_session_starts_with_no_turns(self, loaded_state):
        assert loaded_state.turns == []

    def test_session_id_is_generated(self, loaded_state):
        assert loaded_state.session_id.startswith("sess_")


# ── Node content ──────────────────────────────────────────────────────────────

class TestGraphNodeContent:
    def test_project_falcon_is_confirmed(self, loaded_state):
        node = next(n for n in loaded_state.graph.nodes if n.id == "project_falcon")
        assert node.status == "confirmed"
        assert node.confidence == 1.0

    def test_workflow_node_is_low_confidence(self, loaded_state):
        node = next(n for n in loaded_state.graph.nodes if n.id == "workflow_change_request")
        assert node.confidence < 0.5
        assert node.status == "provisional"

    def test_both_richard_nodes_exist(self, loaded_state):
        node_ids = loaded_state.graph.node_ids()
        assert "person_richard_jones" in node_ids
        assert "person_richard_smith" in node_ids

    def test_richard_nodes_share_alias(self, loaded_state):
        richard_nodes = [
            n for n in loaded_state.graph.nodes
            if n.id in ("person_richard_jones", "person_richard_smith")
        ]
        for node in richard_nodes:
            assert "Richard" in node.aliases

    def test_all_nodes_have_provenance(self, loaded_state):
        for node in loaded_state.graph.nodes:
            assert len(node.provenance) >= 1, f"Node {node.id} has empty provenance"

    def test_all_edges_have_provenance(self, loaded_state):
        for edge in loaded_state.graph.edges:
            assert len(edge.provenance) >= 1, f"Edge {edge.id} has empty provenance"


# ── Graph integrity ───────────────────────────────────────────────────────────

class TestGraphIntegrity:
    def test_no_integrity_violations(self, loaded_state):
        errors = validate_graph_integrity(loaded_state)
        assert errors == [], f"Graph integrity errors: {errors}"

    def test_detects_dangling_edge(self):
        state = load_initial_state(ALEX)
        from app.graph.schema import GraphEdge
        from datetime import datetime, timezone
        dangling = GraphEdge(
            id="edge_dangling",
            type="WORKS_ON",
            source_id="person_nobody",
            target_id="project_falcon",
            confidence=0.9,
            provenance=["test"],
        )
        state.graph.edges.append(dangling)
        errors = validate_graph_integrity(state)
        assert any("person_nobody" in e for e in errors)

    def test_detects_duplicate_node_id(self):
        state = load_initial_state(ALEX)
        dupe = state.graph.nodes[0].model_copy()
        state.graph.nodes.append(dupe)
        errors = validate_graph_integrity(state)
        assert any("Duplicate node" in e for e in errors)


# ── Error handling ────────────────────────────────────────────────────────────

class TestLoaderErrors:
    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_initial_state(ALEX, path=tmp_path / "nonexistent.json")

    def test_raises_on_missing_graph_key(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"open_questions": []}), encoding="utf-8")
        with pytest.raises(ValueError, match="'graph' section"):
            load_initial_state(ALEX, path=bad)

    def test_raises_on_invalid_node_type(self, tmp_path):
        bad_graph = {
            "graph": {
                "nodes": [
                    {
                        "id": "x",
                        "type": "Unicorn",
                        "label": "X",
                        "confidence": 0.9,
                        "provenance": ["test"]
                    }
                ],
                "edges": []
            }
        }
        bad = tmp_path / "bad_type.json"
        bad.write_text(json.dumps(bad_graph), encoding="utf-8")
        with pytest.raises(ValueError, match="'graph' section"):
            load_initial_state(ALEX, path=bad)
