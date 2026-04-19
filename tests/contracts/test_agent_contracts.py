"""
Contract tests for the five LLM-backed specialist agents and the graph mapper.

These tests verify:
  1. Each agent accepts exactly the state slice its stub declared (§26-3/§26-4).
  2. Each agent returns the correct Pydantic model.
  3. The entity extractor correctly surfaces is_ambiguous + possible_matches (§26-5).
  4. The graph mapper skips ambiguous entities and produces stable IDs.

The instructor client is monkeypatched so no real API calls are made.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.models import (
    AttributeExtractionOutput,
    CandidateAttribute,
    CandidateEntity,
    CandidateRelationship,
    Clarification,
    ClarificationOutput,
    CoverageOutput,
    CoverageScores,
    EntityExtractionOutput,
    GraphMappingOutput,
    InterviewTurn,
    PossibleMatch,
    RelationshipExtractionOutput,
)
from app.graph.schema import GraphNode


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture()
def sample_turn() -> InterviewTurn:
    return InterviewTurn(
        turn_number=1,
        question="Who did you work with most closely?",
        question_rationale="Mapping key relationships.",
        answer="Mostly Richard on the client side and Jordan from our data team.",
    )


def _mock_client(return_value) -> MagicMock:
    """Return a mock instructor async client whose messages.create resolves to return_value."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=return_value)
    return client


# ── Entity extractor ──────────────────────────────────────────────────────────

class TestEntityExtractorContract:
    async def test_returns_entity_extraction_output(self, monkeypatch, sample_turn):
        from app.agents import entity_extractor

        expected = EntityExtractionOutput(entities=[
            CandidateEntity(
                temp_id="ent_jordan",
                type="Person",
                label="Jordan",
                confidence=0.9,
                evidence="Jordan from our data team",
            )
        ])
        monkeypatch.setattr(entity_extractor, "get_client", lambda: _mock_client(expected))

        result = await entity_extractor.extract_entities(sample_turn, {})

        assert isinstance(result, EntityExtractionOutput)
        assert len(result.entities) == 1
        assert result.entities[0].label == "Jordan"

    async def test_ambiguous_entity_carries_possible_matches(self, monkeypatch, sample_turn):
        """§26-5: is_ambiguous + possible_matches must be honoured by the contract."""
        from app.agents import entity_extractor

        expected = EntityExtractionOutput(entities=[
            CandidateEntity(
                temp_id="ent_richard",
                type="Person",
                label="Richard",
                confidence=0.7,
                evidence="Richard on the client side",
                is_ambiguous=True,
                possible_matches=[
                    PossibleMatch(node_id="person_richard_jones", label="Richard Jones", confidence=0.6),
                    PossibleMatch(node_id="person_richard_smith", label="Richard Smith", confidence=0.55),
                ],
            )
        ])
        monkeypatch.setattr(entity_extractor, "get_client", lambda: _mock_client(expected))

        existing_aliases = {"Richard": ["person_richard_jones", "person_richard_smith"]}
        result = await entity_extractor.extract_entities(sample_turn, existing_aliases)

        assert result.entities[0].is_ambiguous is True
        assert len(result.entities[0].possible_matches) == 2
        ids = {m.node_id for m in result.entities[0].possible_matches}
        assert "person_richard_jones" in ids

    async def test_empty_answer_returns_empty_entities(self, monkeypatch, sample_turn):
        from app.agents import entity_extractor

        expected = EntityExtractionOutput(entities=[])
        monkeypatch.setattr(entity_extractor, "get_client", lambda: _mock_client(expected))

        result = await entity_extractor.extract_entities(sample_turn, {})
        assert result.entities == []

    async def test_accepts_existing_aliases_slice_only(self, monkeypatch, sample_turn):
        """Confirm the function signature accepts only the contracted slice."""
        from app.agents import entity_extractor
        import inspect

        sig = inspect.signature(entity_extractor.extract_entities)
        params = list(sig.parameters.keys())
        assert params == ["turn", "existing_aliases"]


# ── Relationship extractor ────────────────────────────────────────────────────

class TestRelationshipExtractorContract:
    async def test_returns_relationship_extraction_output(self, monkeypatch, sample_turn):
        from app.agents import relationship_extractor

        expected = RelationshipExtractionOutput(relationships=[
            CandidateRelationship(
                temp_id="rel_alex_works_with_jordan",
                type="COMMUNICATES_WITH",
                source_ref="person_alex_miller",
                target_ref="person_jordan_lee",
                confidence=0.85,
                evidence="Jordan from our data team",
            )
        ])
        monkeypatch.setattr(relationship_extractor, "get_client", lambda: _mock_client(expected))

        result = await relationship_extractor.extract_relationships(
            sample_turn, ["person_alex_miller", "person_jordan_lee"]
        )

        assert isinstance(result, RelationshipExtractionOutput)
        assert result.relationships[0].type == "COMMUNICATES_WITH"

    async def test_accepts_known_node_ids_slice_only(self, monkeypatch):
        from app.agents import relationship_extractor
        import inspect

        sig = inspect.signature(relationship_extractor.extract_relationships)
        params = list(sig.parameters.keys())
        assert params == ["turn", "known_node_ids"]

    async def test_empty_answer_returns_empty_relationships(self, monkeypatch, sample_turn):
        from app.agents import relationship_extractor

        expected = RelationshipExtractionOutput(relationships=[])
        monkeypatch.setattr(relationship_extractor, "get_client", lambda: _mock_client(expected))

        result = await relationship_extractor.extract_relationships(sample_turn, [])
        assert result.relationships == []


# ── Attribute extractor ───────────────────────────────────────────────────────

class TestAttributeExtractorContract:
    async def test_returns_attribute_extraction_output(self, monkeypatch, sample_turn):
        from app.agents import attribute_extractor

        expected = AttributeExtractionOutput(attributes=[
            CandidateAttribute(
                entity_ref="person_jordan_lee",
                attribute_key="team",
                attribute_value="data team",
                confidence=0.9,
                evidence="Jordan from our data team",
            )
        ])
        monkeypatch.setattr(attribute_extractor, "get_client", lambda: _mock_client(expected))

        result = await attribute_extractor.extract_attributes(
            sample_turn, ["person_jordan_lee"]
        )

        assert isinstance(result, AttributeExtractionOutput)
        assert result.attributes[0].attribute_key == "team"

    async def test_accepts_known_node_ids_slice_only(self):
        from app.agents import attribute_extractor
        import inspect

        sig = inspect.signature(attribute_extractor.extract_attributes)
        assert list(sig.parameters.keys()) == ["turn", "known_node_ids"]


# ── Clarification detector ────────────────────────────────────────────────────

class TestClarificationDetectorContract:
    async def test_returns_clarification_output(self, monkeypatch, sample_turn):
        from app.agents import clarification_detector

        expected = ClarificationOutput(clarifications=[
            Clarification(
                kind="ambiguous_entity",
                target="Richard",
                reason="Two Richards exist; unclear which is meant.",
                suggested_question="Which Richard did you mean — Richard Jones or Richard Smith?",
                priority="high",
            )
        ])
        monkeypatch.setattr(clarification_detector, "get_client", lambda: _mock_client(expected))

        result = await clarification_detector.detect_clarifications(sample_turn, {})

        assert isinstance(result, ClarificationOutput)
        assert result.clarifications[0].priority == "high"

    async def test_returns_empty_when_no_clarifications_needed(self, monkeypatch, sample_turn):
        from app.agents import clarification_detector

        expected = ClarificationOutput(clarifications=[])
        monkeypatch.setattr(clarification_detector, "get_client", lambda: _mock_client(expected))

        result = await clarification_detector.detect_clarifications(
            sample_turn, {"Richard": ["person_richard_jones", "person_richard_smith"]}
        )
        assert result.clarifications == []

    async def test_accepts_ambiguous_aliases_slice_only(self):
        from app.agents import clarification_detector
        import inspect

        sig = inspect.signature(clarification_detector.detect_clarifications)
        assert list(sig.parameters.keys()) == ["turn", "ambiguous_aliases"]


# ── Coverage updater ──────────────────────────────────────────────────────────

class TestCoverageUpdaterContract:
    async def test_returns_coverage_output(self, monkeypatch, sample_turn):
        from app.agents import coverage_updater

        updated = CoverageScores(people=0.15)
        expected = CoverageOutput(
            updated_scores=updated,
            priority_topics=["identify all data team members"],
            missing_categories=["systems", "workflows", "risks"],
            rationale="Answer named two people; incrementing people coverage.",
        )
        monkeypatch.setattr(coverage_updater, "get_client", lambda: _mock_client(expected))

        result = await coverage_updater.update_coverage(sample_turn, CoverageScores())

        assert isinstance(result, CoverageOutput)
        assert result.updated_scores.people == 0.15
        assert "people" not in result.missing_categories

    async def test_scores_never_exceed_bounds(self, monkeypatch, sample_turn):
        """Contract: returned scores must satisfy Pydantic ge=0 le=1 constraints."""
        from app.agents import coverage_updater

        valid = CoverageOutput(
            updated_scores=CoverageScores(people=1.0, systems=0.0),
            priority_topics=[],
            missing_categories=[],
            rationale="Full coverage.",
        )
        monkeypatch.setattr(coverage_updater, "get_client", lambda: _mock_client(valid))

        result = await coverage_updater.update_coverage(sample_turn, CoverageScores())
        assert 0.0 <= result.updated_scores.people <= 1.0

    async def test_accepts_coverage_scores_slice_only(self):
        from app.agents import coverage_updater
        import inspect

        sig = inspect.signature(coverage_updater.update_coverage)
        assert list(sig.parameters.keys()) == ["turn", "current_coverage"]


# ── Graph mapper (Python — no LLM) ────────────────────────────────────────────

class TestGraphMapperContract:
    async def test_returns_graph_mapping_output(self):
        from app.agents.graph_mapper import map_to_graph_updates

        entity_out = EntityExtractionOutput(entities=[
            CandidateEntity(
                temp_id="ent_sarah",
                type="Person",
                label="Sarah Chen",
                confidence=0.88,
                evidence="Sarah handles the onboarding workflow",
            )
        ])
        rel_out = RelationshipExtractionOutput(relationships=[])
        attr_out = AttributeExtractionOutput(attributes=[])

        result = await map_to_graph_updates(entity_out, rel_out, attr_out)

        assert isinstance(result, GraphMappingOutput)
        assert len(result.node_updates) == 1
        assert result.node_updates[0].node.id == "person_sarah_chen"
        assert result.node_updates[0].node.type == "Person"

    async def test_ambiguous_entity_is_skipped(self):
        from app.agents.graph_mapper import map_to_graph_updates

        entity_out = EntityExtractionOutput(entities=[
            CandidateEntity(
                temp_id="ent_richard",
                type="Person",
                label="Richard",
                confidence=0.7,
                evidence="Richard on the client side",
                is_ambiguous=True,
                possible_matches=[
                    PossibleMatch(node_id="person_richard_jones", label="Richard Jones", confidence=0.6),
                ],
            )
        ])
        result = await map_to_graph_updates(
            entity_out,
            RelationshipExtractionOutput(relationships=[]),
            AttributeExtractionOutput(attributes=[]),
        )

        assert result.node_updates == []

    async def test_relationship_resolves_temp_ids(self):
        from app.agents.graph_mapper import map_to_graph_updates

        entity_out = EntityExtractionOutput(entities=[
            CandidateEntity(
                temp_id="ent_sarah",
                type="Person",
                label="Sarah Chen",
                confidence=0.88,
                evidence="Sarah Chen is the workflow owner",
            )
        ])
        rel_out = RelationshipExtractionOutput(relationships=[
            CandidateRelationship(
                temp_id="rel_sarah_owns_onboarding",
                type="OWNS",
                source_ref="ent_sarah",       # temp_id
                target_ref="workflow_onboarding",  # existing node id
                confidence=0.80,
                evidence="Sarah handles the onboarding workflow",
            )
        ])
        attr_out = AttributeExtractionOutput(attributes=[])

        result = await map_to_graph_updates(entity_out, rel_out, attr_out)

        assert len(result.edge_updates) == 1
        edge = result.edge_updates[0].edge
        assert edge.source_id == "person_sarah_chen"   # resolved from temp_id
        assert edge.target_id == "workflow_onboarding"  # kept as-is

    async def test_attributes_merged_into_node(self):
        from app.agents.graph_mapper import map_to_graph_updates

        entity_out = EntityExtractionOutput(entities=[
            CandidateEntity(
                temp_id="ent_sarah",
                type="Person",
                label="Sarah Chen",
                confidence=0.88,
                evidence="Sarah Chen",
            )
        ])
        rel_out = RelationshipExtractionOutput(relationships=[])
        attr_out = AttributeExtractionOutput(attributes=[
            CandidateAttribute(
                entity_ref="ent_sarah",
                attribute_key="department",
                attribute_value="Data Engineering",
                confidence=0.9,
                evidence="Sarah is on the data engineering team",
            )
        ])

        result = await map_to_graph_updates(entity_out, rel_out, attr_out)

        node = result.node_updates[0].node
        assert node.attributes.get("department") == "Data Engineering"

    async def test_node_provenance_is_non_empty(self):
        from app.agents.graph_mapper import map_to_graph_updates

        entity_out = EntityExtractionOutput(entities=[
            CandidateEntity(
                temp_id="ent_sarah",
                type="Person",
                label="Sarah Chen",
                confidence=0.88,
                evidence="Sarah Chen manages the pipeline",
            )
        ])
        result = await map_to_graph_updates(
            entity_out,
            RelationshipExtractionOutput(relationships=[]),
            AttributeExtractionOutput(attributes=[]),
        )

        assert result.node_updates[0].node.provenance  # non-empty list

    async def test_stable_id_generation(self):
        """Node IDs must be deterministic: {type_slug}_{label_slug}."""
        from app.agents.graph_mapper import _node_id

        assert _node_id("Person", "Sarah Chen") == "person_sarah_chen"
        assert _node_id("System", "Snowflake") == "system_snowflake"
        assert _node_id("Workflow", "Change Request") == "workflow_change_request"
