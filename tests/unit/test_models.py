"""
Unit tests for Phase 1 data contracts.

These tests are purely about model validation — no LLM calls, no I/O.
They act as the guard-rail that ensures our Pydantic schema stays sound
before any agent logic is layered on top.
"""
import pytest
from pydantic import ValidationError

from app.graph.schema import GraphEdge, GraphNode, KnowledgeGraph
from app.core.models import (
    Ambiguity,
    AttributeExtractionOutput,
    CandidateAttribute,
    CandidateEntity,
    CandidateRelationship,
    Clarification,
    ClarificationOutput,
    CoverageScores,
    EdgeUpdateOp,
    EntityExtractionOutput,
    GraphMappingOutput,
    Interviewee,
    InterviewTurn,
    NodeUpdateOp,
    OrchestratorOutput,
    PossibleMatch,
    ProposedUpdate,
    RelationshipExtractionOutput,
    SharedInterviewState,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_node(**overrides) -> dict:
    base = {
        "id": "person_alex_miller",
        "type": "Person",
        "label": "Alex Miller",
        "confidence": 0.9,
        "provenance": ["initial_state.json"],
    }
    return {**base, **overrides}


def make_edge(**overrides) -> dict:
    base = {
        "id": "edge_001",
        "type": "WORKS_ON",
        "source_id": "person_alex_miller",
        "target_id": "project_falcon",
        "confidence": 0.85,
        "provenance": ["turn_01"],
    }
    return {**base, **overrides}


# ── GraphNode ─────────────────────────────────────────────────────────────────

class TestGraphNode:
    def test_valid_node(self):
        node = GraphNode(**make_node())
        assert node.status == "provisional"
        assert node.type == "Person"

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            GraphNode(**make_node(confidence=1.1))
        with pytest.raises(ValidationError):
            GraphNode(**make_node(confidence=-0.1))

    def test_invalid_node_type(self):
        with pytest.raises(ValidationError):
            GraphNode(**make_node(type="Animal"))

    def test_provenance_required_and_nonempty(self):
        with pytest.raises(ValidationError):
            GraphNode(**make_node(provenance=[]))

    def test_superseded_status(self):
        node = GraphNode(**make_node(status="superseded", superseded_by="person_alex_m2"))
        assert node.status == "superseded"
        assert node.superseded_by == "person_alex_m2"


# ── GraphEdge ─────────────────────────────────────────────────────────────────

class TestGraphEdge:
    def test_valid_edge(self):
        edge = GraphEdge(**make_edge())
        assert edge.type == "WORKS_ON"

    def test_invalid_relationship_type(self):
        with pytest.raises(ValidationError):
            GraphEdge(**make_edge(type="HATES"))

    def test_provenance_required(self):
        with pytest.raises(ValidationError):
            GraphEdge(**make_edge(provenance=[]))


# ── KnowledgeGraph ────────────────────────────────────────────────────────────

class TestKnowledgeGraph:
    def test_empty_graph(self):
        g = KnowledgeGraph()
        assert g.nodes == []
        assert g.edges == []

    def test_node_ids_helper(self):
        node = GraphNode(**make_node())
        g = KnowledgeGraph(nodes=[node])
        assert "person_alex_miller" in g.node_ids()


# ── SharedInterviewState ──────────────────────────────────────────────────────

class TestSharedInterviewState:
    def _interviewee(self) -> Interviewee:
        return Interviewee(
            name="Alex Miller",
            role="Contractor - Data Analyst",
            project_ids=["project_falcon"],
        )

    def test_default_construction(self):
        state = SharedInterviewState(interviewee=self._interviewee())
        assert state.session_id.startswith("sess_")
        assert state.graph.nodes == []
        assert state.coverage.people == 0.0
        assert state.ended_at is None

    def test_turn_appended(self):
        state = SharedInterviewState(interviewee=self._interviewee())
        turn = InterviewTurn(
            turn_number=1,
            question="What were your day-to-day responsibilities?",
            question_rationale="Seed question for role coverage.",
            answer="I managed data pipeline maintenance and ad-hoc reporting.",
        )
        state.turns.append(turn)
        assert len(state.turns) == 1
        assert state.turns[0].turn_id.startswith("turn_")


# ── CandidateEntity (entity extraction contract) ──────────────────────────────

class TestCandidateEntity:
    def test_unambiguous_entity(self):
        ent = CandidateEntity(
            temp_id="ent_tmp_01",
            type="Person",
            label="Richard",
            confidence=0.71,
            evidence="I worked with Richard on the client side.",
        )
        assert ent.is_ambiguous is False
        assert ent.possible_matches == []

    def test_ambiguous_entity_carries_matches(self):
        ent = CandidateEntity(
            temp_id="ent_tmp_02",
            type="Person",
            label="Richard",
            confidence=0.55,
            evidence="Richard approved the change request.",
            is_ambiguous=True,
            possible_matches=[
                PossibleMatch(node_id="person_richard_jones", label="Richard Jones", confidence=0.6),
                PossibleMatch(node_id="person_richard_smith", label="Richard Smith", confidence=0.55),
            ],
        )
        assert ent.is_ambiguous is True
        assert len(ent.possible_matches) == 2

    def test_invalid_node_type_rejected(self):
        with pytest.raises(ValidationError):
            CandidateEntity(
                temp_id="ent_tmp_03",
                type="Animal",
                label="Fido",
                confidence=0.9,
                evidence="...",
            )


# ── Agent output schemas ──────────────────────────────────────────────────────

class TestAgentOutputSchemas:
    def test_entity_extraction_output(self):
        out = EntityExtractionOutput(
            entities=[
                CandidateEntity(
                    temp_id="e1",
                    type="System",
                    label="Tableau",
                    confidence=0.88,
                    evidence="We used Tableau for all dashboards.",
                )
            ]
        )
        assert len(out.entities) == 1

    def test_relationship_extraction_output(self):
        out = RelationshipExtractionOutput(
            relationships=[
                CandidateRelationship(
                    temp_id="r1",
                    type="USES",
                    source_ref="person_alex_miller",
                    target_ref="e1",
                    confidence=0.82,
                    evidence="We used Tableau for all dashboards.",
                )
            ]
        )
        assert out.relationships[0].type == "USES"

    def test_invalid_relationship_type_rejected(self):
        with pytest.raises(ValidationError):
            CandidateRelationship(
                temp_id="r2",
                type="HATES",
                source_ref="x",
                target_ref="y",
                confidence=0.5,
                evidence="...",
            )

    def test_clarification_output(self):
        out = ClarificationOutput(
            clarifications=[
                Clarification(
                    kind="ambiguous_entity",
                    target="Richard",
                    reason="Multiple plausible matches exist in current graph state.",
                    suggested_question="You mentioned Richard — was that Richard Jones or Richard Smith?",
                    priority="high",
                )
            ]
        )
        assert out.clarifications[0].priority == "high"

    def test_graph_mapping_output_roundtrip(self):
        node_op = NodeUpdateOp(op="upsert", node=GraphNode(**{
            "id": "person_richard_jones",
            "type": "Person",
            "label": "Richard Jones",
            "confidence": 0.82,
            "provenance": ["turn_04"],
            "status": "provisional",
        }))
        edge_op = EdgeUpdateOp(op="upsert", edge=GraphEdge(**{
            "id": "edge_002",
            "type": "COMMUNICATES_WITH",
            "source_id": "person_alex_miller",
            "target_id": "person_richard_jones",
            "confidence": 0.77,
            "provenance": ["turn_04"],
        }))
        out = GraphMappingOutput(node_updates=[node_op], edge_updates=[edge_op])
        serialised = out.model_dump()
        restored = GraphMappingOutput(**serialised)
        assert restored.node_updates[0].node.label == "Richard Jones"


# ── ProposedUpdate ────────────────────────────────────────────────────────────

class TestProposedUpdate:
    def test_uncommitted_by_default(self):
        upd = ProposedUpdate(source_turn_id="turn_01")
        assert upd.committed is False
        assert upd.update_id.startswith("upd_")

    def test_all_fields_optional_except_source_turn(self):
        upd = ProposedUpdate(source_turn_id="turn_02")
        assert upd.entity_extraction is None
        assert upd.graph_mapping is None


# ── CoverageScores ────────────────────────────────────────────────────────────

class TestCoverageScores:
    def test_defaults_zero(self):
        cov = CoverageScores()
        assert cov.people == 0.0
        assert cov.risks == 0.0

    def test_bounds_enforced(self):
        with pytest.raises(ValidationError):
            CoverageScores(people=1.5)
        with pytest.raises(ValidationError):
            CoverageScores(systems=-0.1)
