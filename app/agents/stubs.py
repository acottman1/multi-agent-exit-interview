"""
Stub implementations of the six specialist agents for Phase 4.

These return empty outputs so the async pipeline can be exercised end-to-end
without LLM calls. Phase 5+ will replace each stub with an instructor-backed
implementation that matches the same signature.

Each stub's signature is the payload-slicing contract the real agent will
honour (Constraint §26-3): it takes only the fields it will actually need,
never the full SharedInterviewState. When the LLM version lands, the turn
loop should not need to change.

The short sleep inside each stub exists so tests can verify that the turn
loop runs extractors concurrently rather than sequentially.
"""
from __future__ import annotations

import asyncio

from app.core.models import (
    AttributeExtractionOutput,
    ClarificationOutput,
    CoverageOutput,
    CoverageScores,
    EntityExtractionOutput,
    GraphMappingOutput,
    InterviewTurn,
    RelationshipExtractionOutput,
)

# Tiny sleep so we can observe parallel vs. sequential dispatch in tests.
STUB_DELAY_SECONDS: float = 0.02


async def extract_entities(
    turn: InterviewTurn,
    existing_aliases: dict[str, list[str]],
) -> EntityExtractionOutput:
    """
    Slice contract: the current turn text + a map of existing node id → aliases,
    so the real agent can flag fuzzy matches without seeing the whole graph.
    """
    await asyncio.sleep(STUB_DELAY_SECONDS)
    return EntityExtractionOutput(entities=[])


async def extract_relationships(
    turn: InterviewTurn,
    known_node_ids: list[str],
) -> RelationshipExtractionOutput:
    """
    Slice contract: the turn text + the list of existing node ids so the
    real agent can reference them by id without seeing full node data.
    """
    await asyncio.sleep(STUB_DELAY_SECONDS)
    return RelationshipExtractionOutput(relationships=[])


async def extract_attributes(
    turn: InterviewTurn,
    known_node_ids: list[str],
) -> AttributeExtractionOutput:
    await asyncio.sleep(STUB_DELAY_SECONDS)
    return AttributeExtractionOutput(attributes=[])


async def detect_clarifications(
    turn: InterviewTurn,
    ambiguous_aliases: dict[str, list[str]],
) -> ClarificationOutput:
    """
    Slice contract: turn text + a map of surface-form → node ids that share
    that alias, so the real agent can spot ambiguous references cheaply.
    """
    await asyncio.sleep(STUB_DELAY_SECONDS)
    return ClarificationOutput(clarifications=[])


async def update_coverage(
    turn: InterviewTurn,
    current_coverage: CoverageScores,
) -> CoverageOutput:
    await asyncio.sleep(STUB_DELAY_SECONDS)
    return CoverageOutput(
        updated_scores=current_coverage,
        priority_topics=[],
        missing_categories=[],
        rationale="stub: no coverage change",
    )


async def map_to_graph_updates(
    entity_output: EntityExtractionOutput,
    relationship_output: RelationshipExtractionOutput,
    attribute_output: AttributeExtractionOutput,
) -> GraphMappingOutput:
    """
    Runs AFTER the extractors because it consumes their outputs.
    Phase 4 stub returns an empty mapping so the updater has nothing to commit.
    """
    await asyncio.sleep(STUB_DELAY_SECONDS)
    return GraphMappingOutput(node_updates=[], edge_updates=[])
