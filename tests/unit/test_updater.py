"""
Unit tests for app/graph/updater.py.

Each test class maps to one logical concern so a failure points to exactly
which invariant or rule broke. No LLM calls, no I/O — pure state machine logic.
"""
from __future__ import annotations

import pytest

from app.core.models import (
    EdgeUpdateOp,
    GraphMappingOutput,
    Interviewee,
    NodeUpdateOp,
    ProposedUpdate,
    SharedInterviewState,
)
from app.graph.schema import GraphEdge, GraphNode, KnowledgeGraph
from app.graph.updater import (
    CONFIRMED_THRESHOLD,
    INSUFFICIENT_THRESHOLD,
    ApplyResult,
    apply_proposed_update,
    promote_edge,
    promote_node,
)


# ── Shared fixtures ───────────────────────────────────────────────────────────

INTERVIEWEE = Interviewee(
    name="Alex Miller",
    role="Contractor - Data Analyst",
    project_ids=["project_falcon"],
)


def _make_state(nodes: list[GraphNode] | None = None, edges: list[GraphEdge] | None = None) -> SharedInterviewState:
    return SharedInterviewState(
        interviewee=INTERVIEWEE,
        graph=KnowledgeGraph(nodes=nodes or [], edges=edges or []),
    )


def _node(
    node_id: str = "node_a",
    node_type: str = "Person",
    label: str = "Alpha",
    confidence: float = 0.75,
    status: str = "provisional",
    provenance: list[str] | None = None,
    attributes: dict | None = None,
) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=node_type,  # type: ignore[arg-type]
        label=label,
        confidence=confidence,
        status=status,  # type: ignore[arg-type]
        provenance=provenance or ["source_a"],
        attributes=attributes or {},
    )


def _edge(
    edge_id: str = "edge_ab",
    edge_type: str = "WORKS_ON",
    source_id: str = "node_a",
    target_id: str = "node_b",
    confidence: float = 0.75,
    status: str = "provisional",
    provenance: list[str] | None = None,
) -> GraphEdge:
    return GraphEdge(
        id=edge_id,
        type=edge_type,  # type: ignore[arg-type]
        source_id=source_id,
        target_id=target_id,
        confidence=confidence,
        status=status,  # type: ignore[arg-type]
        provenance=provenance or ["source_a"],
    )


def _upsert_node_op(node: GraphNode) -> NodeUpdateOp:
    return NodeUpdateOp(op="upsert", node=node)


def _delete_node_op(node: GraphNode) -> NodeUpdateOp:
    return NodeUpdateOp(op="delete", node=node)


def _upsert_edge_op(edge: GraphEdge) -> EdgeUpdateOp:
    return EdgeUpdateOp(op="upsert", edge=edge)


def _delete_edge_op(edge: GraphEdge) -> EdgeUpdateOp:
    return EdgeUpdateOp(op="delete", edge=edge)


def _proposed(
    node_ops: list[NodeUpdateOp] | None = None,
    edge_ops: list[EdgeUpdateOp] | None = None,
    source_turn_id: str = "turn_01",
) -> ProposedUpdate:
    return ProposedUpdate(
        source_turn_id=source_turn_id,
        graph_mapping=GraphMappingOutput(
            node_updates=node_ops or [],
            edge_updates=edge_ops or [],
        ),
    )


# ── Node creation ─────────────────────────────────────────────────────────────

class TestNodeCreation:
    def test_new_node_above_confirmed_threshold_is_confirmed(self):
        state = _make_state()
        result = apply_proposed_update(state, _proposed([_upsert_node_op(_node(confidence=0.85))]))
        assert result.node_changes[0].op == "created"
        assert state.graph.nodes[0].status == "confirmed"

    def test_new_node_between_thresholds_is_provisional(self):
        state = _make_state()
        result = apply_proposed_update(state, _proposed([_upsert_node_op(_node(confidence=0.65))]))
        assert result.node_changes[0].op == "created"
        assert state.graph.nodes[0].status == "provisional"

    def test_new_node_at_exact_confirmed_threshold_is_confirmed(self):
        state = _make_state()
        result = apply_proposed_update(state, _proposed([_upsert_node_op(_node(confidence=CONFIRMED_THRESHOLD))]))
        assert state.graph.nodes[0].status == "confirmed"

    def test_new_node_at_exact_insufficient_threshold_is_provisional(self):
        state = _make_state()
        result = apply_proposed_update(state, _proposed([_upsert_node_op(_node(confidence=INSUFFICIENT_THRESHOLD))]))
        assert result.node_changes[0].op == "created"
        assert state.graph.nodes[0].status == "provisional"

    def test_new_node_below_insufficient_threshold_is_rejected(self):
        state = _make_state()
        result = apply_proposed_update(state, _proposed([_upsert_node_op(_node(confidence=0.49))]))
        assert result.node_changes[0].op == "rejected"
        assert len(state.graph.nodes) == 0

    def test_rejection_reason_mentions_threshold(self):
        state = _make_state()
        result = apply_proposed_update(state, _proposed([_upsert_node_op(_node(confidence=0.30))]))
        assert "Follow-up required" in result.node_changes[0].reason

    def test_node_count_increases_on_creation(self):
        state = _make_state()
        apply_proposed_update(state, _proposed([_upsert_node_op(_node("n1", confidence=0.7))]))
        apply_proposed_update(state, _proposed([_upsert_node_op(_node("n2", confidence=0.7))]))
        assert len(state.graph.nodes) == 2


# ── Node update ───────────────────────────────────────────────────────────────

class TestNodeUpdate:
    def test_update_merges_provenance(self):
        existing = _node(provenance=["doc_a"])
        state = _make_state(nodes=[existing])
        incoming = _node(provenance=["doc_b"])
        apply_proposed_update(state, _proposed([_upsert_node_op(incoming)]))
        assert state.graph.nodes[0].provenance == ["doc_a", "doc_b"]

    def test_update_deduplicates_provenance(self):
        existing = _node(provenance=["doc_a", "doc_b"])
        state = _make_state(nodes=[existing])
        incoming = _node(provenance=["doc_b", "doc_c"])
        apply_proposed_update(state, _proposed([_upsert_node_op(incoming)]))
        assert state.graph.nodes[0].provenance == ["doc_a", "doc_b", "doc_c"]

    def test_update_merges_attributes_incoming_wins_on_conflict(self):
        existing = _node(attributes={"title": "Analyst", "team": "Data"})
        state = _make_state(nodes=[existing])
        incoming = _node(attributes={"title": "Senior Analyst", "location": "Remote"})
        apply_proposed_update(state, _proposed([_upsert_node_op(incoming)]))
        attrs = state.graph.nodes[0].attributes
        assert attrs["title"] == "Senior Analyst"
        assert attrs["team"] == "Data"
        assert attrs["location"] == "Remote"

    def test_update_raises_confidence_if_incoming_is_higher(self):
        existing = _node(confidence=0.60)
        state = _make_state(nodes=[existing])
        incoming = _node(confidence=0.75)
        apply_proposed_update(state, _proposed([_upsert_node_op(incoming)]))
        assert state.graph.nodes[0].confidence == 0.75

    def test_update_does_not_lower_confidence(self):
        existing = _node(confidence=0.90)
        state = _make_state(nodes=[existing])
        incoming = _node(confidence=0.60)
        apply_proposed_update(state, _proposed([_upsert_node_op(incoming)]))
        assert state.graph.nodes[0].confidence == 0.90

    def test_update_promotes_when_confidence_crosses_threshold(self):
        existing = _node(confidence=0.70, status="provisional")
        state = _make_state(nodes=[existing])
        incoming = _node(confidence=0.85)
        result = apply_proposed_update(state, _proposed([_upsert_node_op(incoming)]))
        assert result.node_changes[0].op == "promoted"
        assert state.graph.nodes[0].status == "confirmed"

    def test_update_does_not_demote_confirmed_node(self):
        existing = _node(confidence=0.90, status="confirmed")
        state = _make_state(nodes=[existing])
        incoming = _node(confidence=0.55)
        result = apply_proposed_update(state, _proposed([_upsert_node_op(incoming)]))
        assert state.graph.nodes[0].status == "confirmed"
        assert result.node_changes[0].op == "updated"

    def test_update_of_superseded_node_is_rejected(self):
        existing = _node(status="superseded")
        state = _make_state(nodes=[existing])
        incoming = _node(confidence=0.90)
        result = apply_proposed_update(state, _proposed([_upsert_node_op(incoming)]))
        assert result.node_changes[0].op == "rejected"


# ── Node supersede (delete op) ────────────────────────────────────────────────

class TestNodeSupersede:
    def test_delete_op_marks_node_superseded(self):
        existing = _node(status="confirmed")
        state = _make_state(nodes=[existing])
        result = apply_proposed_update(state, _proposed([_delete_node_op(_node(provenance=["turn_05"]))]))
        assert result.node_changes[0].op == "superseded"
        assert state.graph.nodes[0].status == "superseded"

    def test_supersede_merges_provenance(self):
        existing = _node(provenance=["doc_a"])
        state = _make_state(nodes=[existing])
        apply_proposed_update(state, _proposed([_delete_node_op(_node(provenance=["turn_07"]))]))
        assert "doc_a" in state.graph.nodes[0].provenance
        assert "turn_07" in state.graph.nodes[0].provenance

    def test_supersede_preserves_node_in_graph(self):
        """Invariant 16: history is never discarded, just marked superseded."""
        existing = _node()
        state = _make_state(nodes=[existing])
        apply_proposed_update(state, _proposed([_delete_node_op(existing)]))
        assert len(state.graph.nodes) == 1
        assert state.graph.nodes[0].status == "superseded"

    def test_delete_nonexistent_node_is_rejected(self):
        state = _make_state()
        result = apply_proposed_update(state, _proposed([_delete_node_op(_node("ghost"))]))
        assert result.node_changes[0].op == "rejected"

    def test_delete_already_superseded_node_is_skipped(self):
        existing = _node(status="superseded")
        state = _make_state(nodes=[existing])
        result = apply_proposed_update(state, _proposed([_delete_node_op(existing)]))
        assert result.node_changes[0].op == "skipped"


# ── Explicit promotion ────────────────────────────────────────────────────────

class TestExplicitPromotion:
    def test_promote_node_from_provisional(self):
        state = _make_state(nodes=[_node(status="provisional")])
        change = promote_node(state, "node_a")
        assert change.op == "promoted"
        assert state.graph.nodes[0].status == "confirmed"

    def test_promote_already_confirmed_node_is_skipped(self):
        state = _make_state(nodes=[_node(status="confirmed")])
        change = promote_node(state, "node_a")
        assert change.op == "skipped"
        assert state.graph.nodes[0].status == "confirmed"

    def test_promote_superseded_node_is_rejected(self):
        state = _make_state(nodes=[_node(status="superseded")])
        change = promote_node(state, "node_a")
        assert change.op == "rejected"

    def test_promote_nonexistent_node_is_rejected(self):
        state = _make_state()
        change = promote_node(state, "ghost")
        assert change.op == "rejected"

    def test_promote_edge_from_provisional(self):
        nodes = [_node("node_a"), _node("node_b")]
        edges = [_edge(status="provisional")]
        state = _make_state(nodes=nodes, edges=edges)
        change = promote_edge(state, "edge_ab")
        assert change.op == "promoted"
        assert state.graph.edges[0].status == "confirmed"

    def test_promote_already_confirmed_edge_is_skipped(self):
        nodes = [_node("node_a"), _node("node_b")]
        edges = [_edge(status="confirmed")]
        state = _make_state(nodes=nodes, edges=edges)
        change = promote_edge(state, "edge_ab")
        assert change.op == "skipped"

    def test_promote_superseded_edge_is_rejected(self):
        nodes = [_node("node_a"), _node("node_b")]
        edges = [_edge(status="superseded")]
        state = _make_state(nodes=nodes, edges=edges)
        change = promote_edge(state, "edge_ab")
        assert change.op == "rejected"


# ── Edge creation ─────────────────────────────────────────────────────────────

class TestEdgeCreation:
    def test_edge_created_when_both_endpoints_exist(self):
        state = _make_state(nodes=[_node("node_a"), _node("node_b")])
        result = apply_proposed_update(state, _proposed(edge_ops=[_upsert_edge_op(_edge())]))
        assert result.edge_changes[0].op == "created"
        assert len(state.graph.edges) == 1

    def test_edge_above_confirmed_threshold_is_confirmed(self):
        state = _make_state(nodes=[_node("node_a"), _node("node_b")])
        result = apply_proposed_update(state, _proposed(edge_ops=[_upsert_edge_op(_edge(confidence=0.90))]))
        assert state.graph.edges[0].status == "confirmed"

    def test_edge_between_thresholds_is_provisional(self):
        state = _make_state(nodes=[_node("node_a"), _node("node_b")])
        result = apply_proposed_update(state, _proposed(edge_ops=[_upsert_edge_op(_edge(confidence=0.65))]))
        assert state.graph.edges[0].status == "provisional"

    def test_edge_rejected_below_insufficient_threshold(self):
        state = _make_state(nodes=[_node("node_a"), _node("node_b")])
        result = apply_proposed_update(state, _proposed(edge_ops=[_upsert_edge_op(_edge(confidence=0.40))]))
        assert result.edge_changes[0].op == "rejected"
        assert len(state.graph.edges) == 0

    def test_edge_rejected_when_source_missing(self):
        """Invariant 12: both endpoints must exist."""
        state = _make_state(nodes=[_node("node_b")])
        result = apply_proposed_update(state, _proposed(edge_ops=[_upsert_edge_op(_edge())]))
        assert result.edge_changes[0].op == "rejected"
        assert "source" in result.edge_changes[0].reason

    def test_edge_rejected_when_target_missing(self):
        state = _make_state(nodes=[_node("node_a")])
        result = apply_proposed_update(state, _proposed(edge_ops=[_upsert_edge_op(_edge())]))
        assert result.edge_changes[0].op == "rejected"
        assert "target" in result.edge_changes[0].reason

    def test_edge_rejected_when_source_is_superseded(self):
        """Invariant 12: superseded nodes cannot anchor new edges."""
        nodes = [_node("node_a", status="superseded"), _node("node_b")]
        state = _make_state(nodes=nodes)
        result = apply_proposed_update(state, _proposed(edge_ops=[_upsert_edge_op(_edge())]))
        assert result.edge_changes[0].op == "rejected"
        assert "superseded" in result.edge_changes[0].reason

    def test_edge_rejected_when_target_is_superseded(self):
        nodes = [_node("node_a"), _node("node_b", status="superseded")]
        state = _make_state(nodes=nodes)
        result = apply_proposed_update(state, _proposed(edge_ops=[_upsert_edge_op(_edge())]))
        assert result.edge_changes[0].op == "rejected"


# ── Edge update ───────────────────────────────────────────────────────────────

class TestEdgeUpdate:
    def _state_with_edge(self, **edge_kwargs) -> SharedInterviewState:
        nodes = [_node("node_a"), _node("node_b")]
        edges = [_edge(**edge_kwargs)]
        return _make_state(nodes=nodes, edges=edges)

    def test_update_merges_provenance(self):
        state = self._state_with_edge(provenance=["doc_a"])
        incoming = _edge(provenance=["doc_b"])
        apply_proposed_update(state, _proposed(edge_ops=[_upsert_edge_op(incoming)]))
        assert state.graph.edges[0].provenance == ["doc_a", "doc_b"]

    def test_update_promotes_edge_when_confidence_crosses_threshold(self):
        state = self._state_with_edge(confidence=0.70, status="provisional")
        incoming = _edge(confidence=0.85)
        result = apply_proposed_update(state, _proposed(edge_ops=[_upsert_edge_op(incoming)]))
        assert result.edge_changes[0].op == "promoted"
        assert state.graph.edges[0].status == "confirmed"

    def test_update_does_not_demote_confirmed_edge(self):
        state = self._state_with_edge(confidence=0.90, status="confirmed")
        incoming = _edge(confidence=0.60)
        result = apply_proposed_update(state, _proposed(edge_ops=[_upsert_edge_op(incoming)]))
        assert state.graph.edges[0].status == "confirmed"

    def test_update_of_superseded_edge_is_rejected(self):
        state = self._state_with_edge(status="superseded")
        result = apply_proposed_update(state, _proposed(edge_ops=[_upsert_edge_op(_edge())]))
        assert result.edge_changes[0].op == "rejected"


# ── Edge supersede (delete op) ────────────────────────────────────────────────

class TestEdgeSupersede:
    def test_delete_op_marks_edge_superseded(self):
        nodes = [_node("node_a"), _node("node_b")]
        state = _make_state(nodes=nodes, edges=[_edge(status="confirmed")])
        result = apply_proposed_update(state, _proposed(edge_ops=[_delete_edge_op(_edge(provenance=["turn_05"]))]))
        assert result.edge_changes[0].op == "superseded"
        assert state.graph.edges[0].status == "superseded"

    def test_supersede_preserves_edge_in_graph(self):
        """Invariant 16: history is retained."""
        nodes = [_node("node_a"), _node("node_b")]
        state = _make_state(nodes=nodes, edges=[_edge()])
        apply_proposed_update(state, _proposed(edge_ops=[_delete_edge_op(_edge())]))
        assert len(state.graph.edges) == 1
        assert state.graph.edges[0].status == "superseded"

    def test_supersede_merges_provenance(self):
        nodes = [_node("node_a"), _node("node_b")]
        state = _make_state(nodes=nodes, edges=[_edge(provenance=["doc_a"])])
        apply_proposed_update(state, _proposed(edge_ops=[_delete_edge_op(_edge(provenance=["turn_08"]))]))
        assert "doc_a" in state.graph.edges[0].provenance
        assert "turn_08" in state.graph.edges[0].provenance

    def test_delete_nonexistent_edge_is_rejected(self):
        state = _make_state()
        result = apply_proposed_update(state, _proposed(edge_ops=[_delete_edge_op(_edge("ghost_edge"))]))
        assert result.edge_changes[0].op == "rejected"

    def test_delete_already_superseded_edge_is_skipped(self):
        nodes = [_node("node_a"), _node("node_b")]
        state = _make_state(nodes=nodes, edges=[_edge(status="superseded")])
        result = apply_proposed_update(state, _proposed(edge_ops=[_delete_edge_op(_edge())]))
        assert result.edge_changes[0].op == "skipped"


# ── apply_proposed_update bookkeeping ─────────────────────────────────────────

class TestApplyProposedUpdate:
    def test_marks_update_as_committed(self):
        state = _make_state()
        update = _proposed([_upsert_node_op(_node(confidence=0.70))])
        assert update.committed is False
        apply_proposed_update(state, update)
        assert update.committed is True

    def test_marks_committed_even_when_all_ops_rejected(self):
        state = _make_state()
        update = _proposed([_upsert_node_op(_node(confidence=0.10))])
        apply_proposed_update(state, update)
        assert update.committed is True

    def test_no_graph_mapping_returns_empty_result(self):
        state = _make_state()
        update = ProposedUpdate(source_turn_id="turn_01")
        result = apply_proposed_update(state, update)
        assert result.node_changes == []
        assert result.edge_changes == []
        assert update.committed is True

    def test_node_ops_applied_before_edge_ops(self):
        """
        A single call that creates both a new node and an edge referencing it
        must succeed — proving node ops run first.
        """
        state = _make_state(nodes=[_node("node_a")])
        new_node = _node("node_b", confidence=0.85)
        new_edge = _edge(source_id="node_a", target_id="node_b", confidence=0.85)
        result = apply_proposed_update(
            state,
            _proposed(
                node_ops=[_upsert_node_op(new_node)],
                edge_ops=[_upsert_edge_op(new_edge)],
            ),
        )
        assert result.node_changes[0].op == "created"
        assert result.edge_changes[0].op == "created"

    def test_has_rejections_property(self):
        state = _make_state()
        update = _proposed([_upsert_node_op(_node(confidence=0.10))])
        result = apply_proposed_update(state, update)
        assert result.has_rejections is True

    def test_no_rejections_property(self):
        state = _make_state()
        update = _proposed([_upsert_node_op(_node(confidence=0.75))])
        result = apply_proposed_update(state, update)
        assert result.has_rejections is False

    def test_created_count_property(self):
        state = _make_state()
        update = _proposed([
            _upsert_node_op(_node("n1", confidence=0.75)),
            _upsert_node_op(_node("n2", confidence=0.75)),
        ])
        result = apply_proposed_update(state, update)
        assert result.created_count == 2

    def test_promoted_count_property(self):
        existing_a = _node("n1", confidence=0.60, status="provisional")
        existing_b = _node("n2", confidence=0.60, status="provisional")
        state = _make_state(nodes=[existing_a, existing_b])
        update = _proposed([
            _upsert_node_op(_node("n1", confidence=0.90)),
            _upsert_node_op(_node("n2", confidence=0.85)),
        ])
        result = apply_proposed_update(state, update)
        assert result.promoted_count == 2


# ── Integration: realistic multi-op scenario ──────────────────────────────────

class TestRealisticScenario:
    def test_resolve_richard_ambiguity(self):
        """
        Simulates the turn-loop resolving the 'Richard' ambiguity from initial_state:
        interviewee confirms Richard Jones, so we promote that node to confirmed
        and supersede Richard Smith (the wrong candidate).
        """
        richard_jones = _node("person_richard_jones", "Person", "Richard Jones",
                               confidence=0.72, status="provisional",
                               provenance=["email_client_sync_jan"])
        richard_smith = _node("person_richard_smith", "Person", "Richard Smith",
                               confidence=0.58, status="provisional",
                               provenance=["ticket_falcon_42"])
        state = _make_state(nodes=[richard_jones, richard_smith])

        # Interviewee confirms Richard Jones
        confirm_result = promote_node(state, "person_richard_jones")
        assert confirm_result.op == "promoted"

        # Supersede Richard Smith — he was the wrong candidate
        supersede_update = _proposed([
            _delete_node_op(_node("person_richard_smith", provenance=["turn_03"]))
        ])
        supersede_result = apply_proposed_update(state, supersede_update)
        assert supersede_result.node_changes[0].op == "superseded"

        # Final state: Jones is confirmed, Smith is superseded but still in graph
        jones = next(n for n in state.graph.nodes if n.id == "person_richard_jones")
        smith = next(n for n in state.graph.nodes if n.id == "person_richard_smith")
        assert jones.status == "confirmed"
        assert smith.status == "superseded"
        assert "ticket_falcon_42" in smith.provenance  # original provenance preserved
        assert "turn_03" in smith.provenance            # correction evidence added
        assert len(state.graph.nodes) == 2              # history retained

    def test_workflow_node_gains_confidence_across_turns(self):
        """
        A low-confidence workflow node progressively crosses the confirmation
        threshold as the interview adds corroborating evidence.
        """
        workflow = _node("workflow_cr", "Workflow", "Change Request Workflow",
                          confidence=0.45, status="provisional",
                          provenance=["ticket_falcon_42"])
        state = _make_state(nodes=[workflow])

        # Turn 2: more evidence, still provisional
        update_1 = _proposed([_upsert_node_op(_node(
            "workflow_cr", "Workflow", "Change Request Workflow",
            confidence=0.62, provenance=["turn_02"],
        ))])
        r1 = apply_proposed_update(state, update_1)
        assert r1.node_changes[0].op == "updated"
        assert state.graph.nodes[0].status == "provisional"
        assert state.graph.nodes[0].confidence == 0.62

        # Turn 3: interviewee gives detailed walkthrough — crosses threshold
        update_2 = _proposed([_upsert_node_op(_node(
            "workflow_cr", "Workflow", "Change Request Workflow",
            confidence=0.88, provenance=["turn_03"],
            attributes={"steps_documented": True},
        ))])
        r2 = apply_proposed_update(state, update_2)
        assert r2.node_changes[0].op == "promoted"
        assert state.graph.nodes[0].status == "confirmed"
        assert "ticket_falcon_42" in state.graph.nodes[0].provenance
        assert "turn_02" in state.graph.nodes[0].provenance
        assert "turn_03" in state.graph.nodes[0].provenance
