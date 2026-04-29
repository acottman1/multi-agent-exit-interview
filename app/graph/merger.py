"""
Graph merger — combines multiple SharedInterviewState objects into one.

Supports project-level merging (multiple witnesses on the same project) and
company-level merging (multiple projects). The operation is identical at both
levels; what you feed in determines the scope.

Key merge properties
--------------------
- Node IDs are deterministic across sessions ({type_slug}_{label_slug}), so
  the same real-world entity always produces the same graph ID.
- Multi-witness consensus raises confidence toward CONFIRMED_THRESHOLD.
- Attribute disagreements between sources (A says x, B says y) surface as
  Ambiguity entries in the merged state AND as lines in the conflict log.
- Provenance chains grow: merged nodes carry evidence from every contributor.
- Status: never demotes (confirmed stays confirmed); merges across provisional
  states by taking max confidence and auto-promoting at ≥ CONFIRMED_THRESHOLD.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.core.models import (
    Ambiguity,
    CoverageScores,
    Interviewee,
    OpenQuestion,
    SharedInterviewState,
)
from app.graph.schema import GraphEdge, GraphNode, KnowledgeGraph
from app.graph.updater import CONFIRMED_THRESHOLD


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tag(name: str) -> str:
    """Convert an interviewee name into a short provenance tag, e.g. 'Alex Miller' → 'alex_miller'."""
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    return re.sub(r"\s+", "_", name.strip())


def _merge_provenance(existing: list[str], incoming: list[str]) -> list[str]:
    """Union of provenance sources, preserving insertion order."""
    seen: dict[str, None] = dict.fromkeys(existing)
    for source in incoming:
        seen[source] = None
    return list(seen.keys())


def _merged_status(existing_status: str, incoming_status: str, new_confidence: float) -> str:
    """
    Resolve the status of a merged node/edge.

    Rules (match updater invariants):
    - Confirmed is never demoted.
    - Superseded is terminal (a source that contradicted this node wins on
      finality, but only if the existing side is not already confirmed).
    - Auto-promote provisional → confirmed when merged confidence ≥ threshold.
    """
    if existing_status == "confirmed":
        return "confirmed"
    if existing_status == "superseded":
        return "superseded"
    # existing is provisional
    if incoming_status == "confirmed":
        return "confirmed"
    if new_confidence >= CONFIRMED_THRESHOLD:
        return "confirmed"
    if incoming_status == "superseded":
        return "superseded"
    return "provisional"


# ── Public API ────────────────────────────────────────────────────────────────

def merge_states(
    states: list[SharedInterviewState],
    merged_name: str,
) -> tuple[SharedInterviewState, list[str]]:
    """
    Merge multiple interview states into one SharedInterviewState.

    Parameters
    ----------
    states:
        Two or more session states to merge. Order matters for provenance
        ordering (earlier = listed first in merged provenance chains).
    merged_name:
        Human-readable name for the merged entity, e.g. "Project Falcon".

    Returns
    -------
    (merged_state, conflict_log)
        merged_state — a valid SharedInterviewState usable as a vault source
            or as a seed for future interviews.
        conflict_log — human-readable strings for every attribute conflict
            detected; empty when all sources agree.
    """
    if not states:
        raise ValueError("merge_states requires at least one state")

    conflict_log: list[str] = []
    now = datetime.now(tz=timezone.utc)

    node_map: dict[str, GraphNode] = {}
    edge_map: dict[str, GraphEdge] = {}
    merged_ambiguities: list[Ambiguity] = []
    open_question_map: dict[str, OpenQuestion] = {}
    coverage_by_field: dict[str, list[float]] = {
        "people": [], "systems": [], "workflows": [],
        "stakeholders": [], "risks": [], "undocumented_knowledge": [],
    }

    for state in states:
        interviewee_tag = _tag(state.interviewee.name)

        # ── Nodes ─────────────────────────────────────────────────────────────
        for node in state.graph.nodes:
            # Prepend the witness name so merged provenance shows who said what.
            tagged_prov = _merge_provenance([interviewee_tag], node.provenance)

            if node.id not in node_map:
                node_map[node.id] = node.model_copy(
                    update={"provenance": tagged_prov, "updated_at": now}
                )
            else:
                existing = node_map[node.id]

                # Detect attribute conflicts before overwriting.
                for key, incoming_val in node.attributes.items():
                    if key in existing.attributes and existing.attributes[key] != incoming_val:
                        first_witness = next(
                            (p for p in existing.provenance if p not in node.provenance),
                            existing.provenance[0] if existing.provenance else "unknown",
                        )
                        msg = (
                            f"Conflict on '{node.label}' ({node.id}), "
                            f"attribute '{key}': "
                            f"'{first_witness}' says {existing.attributes[key]!r}, "
                            f"'{interviewee_tag}' says {incoming_val!r}"
                        )
                        conflict_log.append(msg)
                        merged_ambiguities.append(
                            Ambiguity(
                                kind="ambiguous_entity",
                                target=node.label,
                                reason=msg,
                                suggested_question=(
                                    f"Two sources disagree about {node.label!r}: "
                                    f"one says {key}={existing.attributes[key]!r} "
                                    f"and another says {key}={incoming_val!r}. "
                                    f"Which is correct?"
                                ),
                                priority="medium",
                                source_turn_id="merge",
                            )
                        )

                new_conf = max(existing.confidence, node.confidence)
                new_status = _merged_status(existing.status, node.status, new_conf)

                node_map[node.id] = existing.model_copy(update={
                    "provenance": _merge_provenance(existing.provenance, tagged_prov),
                    "attributes": {**existing.attributes, **node.attributes},
                    "confidence": new_conf,
                    "status": new_status,
                    "updated_at": now,
                })

        # ── Edges ─────────────────────────────────────────────────────────────
        for edge in state.graph.edges:
            tagged_prov = _merge_provenance([interviewee_tag], edge.provenance)

            if edge.id not in edge_map:
                edge_map[edge.id] = edge.model_copy(
                    update={"provenance": tagged_prov, "updated_at": now}
                )
            else:
                existing = edge_map[edge.id]
                new_conf = max(existing.confidence, edge.confidence)
                new_status = _merged_status(existing.status, edge.status, new_conf)

                edge_map[edge.id] = existing.model_copy(update={
                    "provenance": _merge_provenance(existing.provenance, tagged_prov),
                    "attributes": {**existing.attributes, **edge.attributes},
                    "confidence": new_conf,
                    "status": new_status,
                    "updated_at": now,
                })

        # ── Ambiguities (carry forward unresolved ones) ────────────────────
        for amb in state.ambiguities:
            if not amb.resolved:
                merged_ambiguities.append(amb)

        # ── Open questions (deduplicate by question_id) ────────────────────
        for q in state.open_questions:
            if q.question_id not in open_question_map:
                open_question_map[q.question_id] = q

        # ── Coverage accumulation ──────────────────────────────────────────
        for field in coverage_by_field:
            coverage_by_field[field].append(getattr(state.coverage, field))

    # ── Build merged coverage (optimistic: max per category) ──────────────────
    merged_coverage = CoverageScores(
        **{field: max(vals) for field, vals in coverage_by_field.items()}
    )

    merged_state = SharedInterviewState(
        interviewee=Interviewee(name=merged_name, role="Merged", project_ids=[]),
        graph=KnowledgeGraph(
            nodes=list(node_map.values()),
            edges=list(edge_map.values()),
        ),
        coverage=merged_coverage,
        ambiguities=merged_ambiguities,
        open_questions=list(open_question_map.values()),
        # Empty so merged state can be used as a seed without blocking re-asking
        # questions that individual witnesses already answered.
        asked_question_ids=[],
        turns=[],
    )

    return merged_state, conflict_log
