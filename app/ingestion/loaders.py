"""
Ingestion loaders.

Two independent loaders coexist here:
  load_initial_state()    — graph engine (v1): reads initial_state.json into
                            SharedInterviewState. Unchanged from Phase 2.
  load_context_briefing() — brief engine (v2): reads context_briefing.json
                            into ContextBriefing. Lightweight preload context.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.config.context_briefing import ContextBriefing
from app.core.models import (
    Ambiguity,
    Interviewee,
    OpenQuestion,
    SharedInterviewState,
)
from app.graph.schema import KnowledgeGraph

_DEFAULT_PATH = Path(__file__).parent / "dummy_data" / "initial_state.json"
_DEFAULT_CONTEXT_PATH = Path(__file__).parent / "dummy_data" / "context_briefing.json"


def load_initial_state(
    interviewee: Interviewee,
    path: Path = _DEFAULT_PATH,
) -> SharedInterviewState:
    """
    Build the opening SharedInterviewState from a static JSON file.

    Args:
        interviewee: The session's interviewee, supplied at runtime.
        path: Path to the initial_state.json file. Defaults to the bundled dummy data.

    Raises:
        FileNotFoundError: If the JSON file does not exist.
        ValueError: If the JSON fails Pydantic schema validation.
    """
    if not path.exists():
        raise FileNotFoundError(f"Initial state file not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))

    try:
        graph = KnowledgeGraph.model_validate(raw["graph"])
    except (KeyError, ValidationError) as exc:
        raise ValueError(f"'graph' section failed schema validation: {exc}") from exc

    try:
        open_questions = [
            OpenQuestion.model_validate(q) for q in raw.get("open_questions", [])
        ]
    except ValidationError as exc:
        raise ValueError(f"'open_questions' section failed schema validation: {exc}") from exc

    try:
        ambiguities = [
            Ambiguity.model_validate(a) for a in raw.get("ambiguities", [])
        ]
    except ValidationError as exc:
        raise ValueError(f"'ambiguities' section failed schema validation: {exc}") from exc

    return SharedInterviewState(
        interviewee=interviewee,
        graph=graph,
        open_questions=open_questions,
        ambiguities=ambiguities,
    )


def load_context_briefing(path: Path = _DEFAULT_CONTEXT_PATH) -> ContextBriefing:
    """
    Load a ContextBriefing from a JSON file for the brief engine.

    Args:
        path: Path to context_briefing.json. Defaults to the bundled dummy data.

    Raises:
        FileNotFoundError: If the JSON file does not exist.
        ValueError: If the JSON fails Pydantic schema validation.
    """
    if not path.exists():
        raise FileNotFoundError(f"Context briefing file not found: {path}")
    try:
        return ContextBriefing.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValidationError, ValueError) as exc:
        raise ValueError(f"Context briefing failed schema validation: {exc}") from exc


def validate_graph_integrity(state: SharedInterviewState) -> list[str]:
    """
    Return a list of integrity violations in the loaded graph.

    Checks:
    - Every edge source_id and target_id references an existing node.
    - No duplicate node or edge IDs.

    Returns an empty list if the graph is clean.
    """
    errors: list[str] = []
    node_ids = state.graph.node_ids()

    seen_node_ids: set[str] = set()
    for node in state.graph.nodes:
        if node.id in seen_node_ids:
            errors.append(f"Duplicate node id: {node.id!r}")
        seen_node_ids.add(node.id)

    seen_edge_ids: set[str] = set()
    for edge in state.graph.edges:
        if edge.id in seen_edge_ids:
            errors.append(f"Duplicate edge id: {edge.id!r}")
        seen_edge_ids.add(edge.id)

        if edge.source_id not in node_ids:
            errors.append(
                f"Edge {edge.id!r}: source_id {edge.source_id!r} does not reference a known node"
            )
        if edge.target_id not in node_ids:
            errors.append(
                f"Edge {edge.id!r}: target_id {edge.target_id!r} does not reference a known node"
            )

    return errors
