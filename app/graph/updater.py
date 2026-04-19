"""
Graph updater — the ONLY module allowed to write to the canonical KnowledgeGraph.

Invariants enforced here (see spec Section 8):
  #7  Agents propose; this module commits.
  #8  Only this module promotes provisional → confirmed.
  #9  Every committed item must carry provenance.
  #12 Edge commits require both endpoints to exist as non-superseded nodes.
  #15 Auto-confirmation requires confidence ≥ CONFIRMED_THRESHOLD.
  #16 Superseded items retain merged provenance; history is never discarded.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from app.core.models import (
    EdgeUpdateOp,
    NodeUpdateOp,
    ProposedUpdate,
    SharedInterviewState,
)
from app.graph.schema import GraphEdge, GraphNode

logger = logging.getLogger(__name__)

# ── Confidence thresholds (spec Section 15) ───────────────────────────────────
INSUFFICIENT_THRESHOLD: float = 0.50  # below → reject, request follow-up
CONFIRMED_THRESHOLD: float = 0.80     # at or above → auto-promote to confirmed


# ── Result types ──────────────────────────────────────────────────────────────

ChangeOp = Literal["created", "updated", "promoted", "superseded", "rejected", "skipped"]


class NodeChange(BaseModel):
    node_id: str
    op: ChangeOp
    reason: str | None = None


class EdgeChange(BaseModel):
    edge_id: str
    op: ChangeOp
    reason: str | None = None


class ApplyResult(BaseModel):
    node_changes: list[NodeChange] = []
    edge_changes: list[EdgeChange] = []

    @property
    def has_rejections(self) -> bool:
        return any(
            c.op == "rejected"
            for c in (*self.node_changes, *self.edge_changes)
        )

    @property
    def created_count(self) -> int:
        return sum(
            1 for c in (*self.node_changes, *self.edge_changes) if c.op == "created"
        )

    @property
    def promoted_count(self) -> int:
        return sum(
            1 for c in (*self.node_changes, *self.edge_changes) if c.op == "promoted"
        )


# ── Public API ────────────────────────────────────────────────────────────────

def apply_proposed_update(
    state: SharedInterviewState,
    update: ProposedUpdate,
) -> ApplyResult:
    """
    Apply a ProposedUpdate's graph_mapping to the canonical KnowledgeGraph.

    Node ops are processed before edge ops so that an upsert that creates a
    new node and an edge referencing it can succeed in a single call.

    Always sets update.committed = True, even when individual ops are rejected,
    so the caller does not retry blindly. The ApplyResult surfaces any rejections.
    """
    if update.graph_mapping is None:
        update.committed = True
        return ApplyResult()

    result = ApplyResult()
    now = datetime.now(tz=timezone.utc)

    for node_op in update.graph_mapping.node_updates:
        result.node_changes.append(_apply_node_op(state, node_op, now))

    for edge_op in update.graph_mapping.edge_updates:
        result.edge_changes.append(_apply_edge_op(state, edge_op, now))

    update.committed = True

    rejection_count = sum(
        1 for c in (*result.node_changes, *result.edge_changes) if c.op == "rejected"
    )
    if rejection_count:
        logger.warning(
            "apply_proposed_update: %s committed with %d rejection(s)",
            update.update_id,
            rejection_count,
        )

    return result


def promote_node(state: SharedInterviewState, node_id: str) -> NodeChange:
    """
    Explicitly promote a node to confirmed status.

    Called when the interviewee verbally confirms a fact, bypassing the
    automated confidence threshold. The turn loop is responsible for deciding
    when to call this; the updater only performs the state mutation.
    """
    node = _find_node(state, node_id)
    if node is None:
        return NodeChange(
            node_id=node_id,
            op="rejected",
            reason=f"Node {node_id!r} not found in graph.",
        )
    if node.status == "superseded":
        return NodeChange(
            node_id=node_id,
            op="rejected",
            reason=f"Node {node_id!r} is superseded and cannot be promoted.",
        )
    if node.status == "confirmed":
        return NodeChange(node_id=node_id, op="skipped", reason="Already confirmed.")

    node.status = "confirmed"
    node.updated_at = datetime.now(tz=timezone.utc)
    return NodeChange(node_id=node_id, op="promoted")


def promote_edge(state: SharedInterviewState, edge_id: str) -> EdgeChange:
    """Explicitly promote an edge to confirmed status."""
    edge = _find_edge(state, edge_id)
    if edge is None:
        return EdgeChange(
            edge_id=edge_id,
            op="rejected",
            reason=f"Edge {edge_id!r} not found in graph.",
        )
    if edge.status == "superseded":
        return EdgeChange(
            edge_id=edge_id,
            op="rejected",
            reason=f"Edge {edge_id!r} is superseded and cannot be promoted.",
        )
    if edge.status == "confirmed":
        return EdgeChange(edge_id=edge_id, op="skipped", reason="Already confirmed.")

    edge.status = "confirmed"
    edge.updated_at = datetime.now(tz=timezone.utc)
    return EdgeChange(edge_id=edge_id, op="promoted")


# ── Node op dispatch ──────────────────────────────────────────────────────────

def _apply_node_op(
    state: SharedInterviewState,
    node_op: NodeUpdateOp,
    now: datetime,
) -> NodeChange:
    incoming = node_op.node

    if node_op.op == "delete":
        return _supersede_node(state, incoming.id, incoming.provenance, now)

    # upsert path — confidence gate first
    if incoming.confidence < INSUFFICIENT_THRESHOLD:
        return NodeChange(
            node_id=incoming.id,
            op="rejected",
            reason=(
                f"Confidence {incoming.confidence:.2f} is below the provisional "
                f"threshold {INSUFFICIENT_THRESHOLD:.2f}. "
                "Follow-up required before this node can enter the canonical graph."
            ),
        )

    existing = _find_node(state, incoming.id)
    if existing is None:
        return _create_node(state, incoming, now)
    return _update_node(existing, incoming, now)


def _create_node(
    state: SharedInterviewState,
    node: GraphNode,
    now: datetime,
) -> NodeChange:
    status = "confirmed" if node.confidence >= CONFIRMED_THRESHOLD else "provisional"
    state.graph.nodes.append(
        node.model_copy(update={"status": status, "created_at": now, "updated_at": now})
    )
    return NodeChange(node_id=node.id, op="created")


def _update_node(
    existing: GraphNode,
    incoming: GraphNode,
    now: datetime,
) -> NodeChange:
    if existing.status == "superseded":
        return NodeChange(
            node_id=existing.id,
            op="rejected",
            reason=f"Node {existing.id!r} is superseded and cannot be updated.",
        )

    existing.provenance = _merge_provenance(existing.provenance, incoming.provenance)
    existing.attributes = {**existing.attributes, **incoming.attributes}
    existing.updated_at = now

    if incoming.confidence > existing.confidence:
        existing.confidence = incoming.confidence

    # Never demote a confirmed node; only promote upward.
    if existing.status != "confirmed" and existing.confidence >= CONFIRMED_THRESHOLD:
        existing.status = "confirmed"
        return NodeChange(node_id=existing.id, op="promoted")

    return NodeChange(node_id=existing.id, op="updated")


def _supersede_node(
    state: SharedInterviewState,
    node_id: str,
    new_provenance: list[str],
    now: datetime,
) -> NodeChange:
    """
    Mark a node as superseded, preserving merged provenance (Invariant 16).

    The node is retained in the graph so the system can explain why a fact
    changed. It is simply ineligible for further updates or promotion.
    """
    existing = _find_node(state, node_id)
    if existing is None:
        return NodeChange(
            node_id=node_id,
            op="rejected",
            reason=f"Cannot supersede node {node_id!r}: not found in graph.",
        )
    if existing.status == "superseded":
        return NodeChange(
            node_id=node_id,
            op="skipped",
            reason=f"Node {node_id!r} is already superseded.",
        )

    existing.provenance = _merge_provenance(existing.provenance, new_provenance)
    existing.status = "superseded"
    existing.updated_at = now
    return NodeChange(node_id=node_id, op="superseded")


# ── Edge op dispatch ──────────────────────────────────────────────────────────

def _apply_edge_op(
    state: SharedInterviewState,
    edge_op: EdgeUpdateOp,
    now: datetime,
) -> EdgeChange:
    incoming = edge_op.edge

    if edge_op.op == "delete":
        return _supersede_edge(state, incoming.id, incoming.provenance, now)

    # upsert path — confidence gate first
    if incoming.confidence < INSUFFICIENT_THRESHOLD:
        return EdgeChange(
            edge_id=incoming.id,
            op="rejected",
            reason=(
                f"Confidence {incoming.confidence:.2f} is below the provisional "
                f"threshold {INSUFFICIENT_THRESHOLD:.2f}. Follow-up required."
            ),
        )

    # Invariant 12: both endpoints must exist as non-superseded nodes.
    endpoint_check = _check_endpoints(state, incoming)
    if endpoint_check is not None:
        return EdgeChange(edge_id=incoming.id, op="rejected", reason=endpoint_check)

    existing = _find_edge(state, incoming.id)
    if existing is None:
        return _create_edge(state, incoming, now)
    return _update_edge(existing, incoming, now)


def _check_endpoints(state: SharedInterviewState, edge: GraphEdge) -> str | None:
    """Return a rejection reason string if either endpoint is missing or superseded."""
    node_map: dict[str, GraphNode] = {n.id: n for n in state.graph.nodes}

    for endpoint_id, role in ((edge.source_id, "source"), (edge.target_id, "target")):
        node = node_map.get(endpoint_id)
        if node is None:
            return f"Edge {edge.id!r} {role} node {endpoint_id!r} does not exist in graph."
        if node.status == "superseded":
            return f"Edge {edge.id!r} {role} node {endpoint_id!r} is superseded."

    return None


def _create_edge(
    state: SharedInterviewState,
    edge: GraphEdge,
    now: datetime,
) -> EdgeChange:
    status = "confirmed" if edge.confidence >= CONFIRMED_THRESHOLD else "provisional"
    state.graph.edges.append(
        edge.model_copy(update={"status": status, "created_at": now, "updated_at": now})
    )
    return EdgeChange(edge_id=edge.id, op="created")


def _update_edge(
    existing: GraphEdge,
    incoming: GraphEdge,
    now: datetime,
) -> EdgeChange:
    if existing.status == "superseded":
        return EdgeChange(
            edge_id=existing.id,
            op="rejected",
            reason=f"Edge {existing.id!r} is superseded and cannot be updated.",
        )

    existing.provenance = _merge_provenance(existing.provenance, incoming.provenance)
    existing.attributes = {**existing.attributes, **incoming.attributes}
    existing.updated_at = now

    if incoming.confidence > existing.confidence:
        existing.confidence = incoming.confidence

    if existing.status != "confirmed" and existing.confidence >= CONFIRMED_THRESHOLD:
        existing.status = "confirmed"
        return EdgeChange(edge_id=existing.id, op="promoted")

    return EdgeChange(edge_id=existing.id, op="updated")


def _supersede_edge(
    state: SharedInterviewState,
    edge_id: str,
    new_provenance: list[str],
    now: datetime,
) -> EdgeChange:
    existing = _find_edge(state, edge_id)
    if existing is None:
        return EdgeChange(
            edge_id=edge_id,
            op="rejected",
            reason=f"Cannot supersede edge {edge_id!r}: not found in graph.",
        )
    if existing.status == "superseded":
        return EdgeChange(
            edge_id=edge_id,
            op="skipped",
            reason=f"Edge {edge_id!r} is already superseded.",
        )

    existing.provenance = _merge_provenance(existing.provenance, new_provenance)
    existing.status = "superseded"
    existing.updated_at = now
    return EdgeChange(edge_id=edge_id, op="superseded")


# ── Shared helpers ────────────────────────────────────────────────────────────

def _find_node(state: SharedInterviewState, node_id: str) -> GraphNode | None:
    return next((n for n in state.graph.nodes if n.id == node_id), None)


def _find_edge(state: SharedInterviewState, edge_id: str) -> GraphEdge | None:
    return next((e for e in state.graph.edges if e.id == edge_id), None)


def _merge_provenance(existing: list[str], incoming: list[str]) -> list[str]:
    """
    Union of provenance sources, deduplicating while preserving insertion order.
    Existing sources come first so the oldest evidence is always surfaced first.
    """
    seen: dict[str, None] = dict.fromkeys(existing)
    for source in incoming:
        seen[source] = None
    return list(seen.keys())
