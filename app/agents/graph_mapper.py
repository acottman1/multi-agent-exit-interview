"""
Graph mapper (Phase 5).

Converts structured extractor outputs into concrete NodeUpdateOp / EdgeUpdateOp
objects that the updater can commit to the canonical graph.

This module is deliberately NOT LLM-backed: its inputs are already validated
Pydantic models, so deterministic Python is more reliable and cheaper than
asking an LLM to re-interpret structured data.

Constraint §26-3: the public signature is the slice-contract that the turn
loop depends on — do not add SharedInterviewState here.
"""
from __future__ import annotations

import re

from app.core.models import (
    AttributeExtractionOutput,
    EdgeUpdateOp,
    EntityExtractionOutput,
    GraphMappingOutput,
    NodeUpdateOp,
    RelationshipExtractionOutput,
)
from app.graph.schema import GraphEdge, GraphNode


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s_-]", "", text)
    text = re.sub(r"[\s\-]+", "_", text.strip())
    return text


def _node_id(entity_type: str, label: str) -> str:
    return f"{_slugify(entity_type)}_{_slugify(label)}"


def _edge_id(source: str, rel_type: str, target: str) -> str:
    return f"{source}__{rel_type.lower()}__{target}"


async def map_to_graph_updates(
    entity_output: EntityExtractionOutput,
    relationship_output: RelationshipExtractionOutput,
    attribute_output: AttributeExtractionOutput,
) -> GraphMappingOutput:
    """
    Translate extractor outputs into graph ops.

    - Ambiguous entities (is_ambiguous=True) are skipped: they need human
      clarification before we can safely create or merge a node.
    - Attributes are merged into node `attributes` dicts so the updater can
      apply them via the upsert op.
    """
    # Index attributes by entity_ref so we can attach them to nodes / edges.
    attr_by_ref: dict[str, dict] = {}
    for attr in attribute_output.attributes:
        attr_by_ref.setdefault(attr.entity_ref, {})[attr.attribute_key] = (
            attr.attribute_value
        )

    # Build a temp_id → stable node_id map for relationship resolution.
    temp_to_node_id: dict[str, str] = {}

    node_updates: list[NodeUpdateOp] = []
    for entity in entity_output.entities:
        if entity.is_ambiguous:
            # Cannot safely place an ambiguous entity — orchestrator will ask.
            continue

        stable_id = _node_id(entity.type, entity.label)
        temp_to_node_id[entity.temp_id] = stable_id

        node = GraphNode(
            id=stable_id,
            type=entity.type,
            label=entity.label,
            aliases=entity.aliases,
            attributes=attr_by_ref.get(entity.temp_id, {}),
            confidence=entity.confidence,
            provenance=[entity.evidence[:120]],
        )
        node_updates.append(NodeUpdateOp(op="upsert", node=node))

    edge_updates: list[EdgeUpdateOp] = []
    for rel in relationship_output.relationships:
        # Resolve temp_ids to stable node ids where possible.
        source = temp_to_node_id.get(rel.source_ref, rel.source_ref)
        target = temp_to_node_id.get(rel.target_ref, rel.target_ref)

        edge = GraphEdge(
            id=_edge_id(source, rel.type, target),
            type=rel.type,
            source_id=source,
            target_id=target,
            attributes=attr_by_ref.get(rel.temp_id, {}),
            confidence=rel.confidence,
            provenance=[rel.evidence[:120]],
        )
        edge_updates.append(EdgeUpdateOp(op="upsert", edge=edge))

    return GraphMappingOutput(node_updates=node_updates, edge_updates=edge_updates)
