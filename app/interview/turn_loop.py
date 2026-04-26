"""
Interview turn loop.

A single turn runs as follows:
  1. Orchestrator selects the next question (rule-based in Phase 4).
  2. Answer provider supplies the interviewee's answer.
  3. Five specialist analyzers run CONCURRENTLY via asyncio.gather
     (Constraint §26-1: Entity / Relationship / Attribute / Clarification /
     Coverage must not block each other).
  4. Graph mapper synthesizes the extractor outputs into graph ops.
  5. Updater commits the ProposedUpdate (Phase 3 module).
  6. Coverage and open questions are book-kept back onto state.

run_interview() loops run_turn() until max_turns or should_stop().
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Awaitable, Callable, Union

from pydantic import BaseModel

from app.agents.orchestrator import select_next_question
from app.agents.attribute_extractor import extract_attributes
from app.agents.clarification_detector import detect_clarifications
from app.agents.coverage_updater import update_coverage
from app.agents.entity_extractor import extract_entities
from app.agents.graph_mapper import map_to_graph_updates
from app.agents.relationship_extractor import extract_relationships
from app.core.models import (
    ClarificationOutput,
    EntityExtractionOutput,
    InterviewTurn,
    OpenQuestion,
    OrchestratorOutput,
    ProposedUpdate,
    SharedInterviewState,
)
from app.graph.updater import ApplyResult, apply_proposed_update

logger = logging.getLogger(__name__)

DEFAULT_MAX_TURNS: int = 12

# Answer providers may be sync or async. In tests we use scripted sync callables;
# in production this will be bound to a FastAPI/WebSocket handler.
AnswerProvider = Union[
    Callable[[str], Awaitable[str]],
    Callable[[str], str],
]


class TurnResult(BaseModel):
    """Outcome of a single turn, returned to the caller for inspection."""
    model_config = {"arbitrary_types_allowed": True}

    orchestrator_output: OrchestratorOutput
    turn: InterviewTurn
    proposed_update: ProposedUpdate
    apply_result: ApplyResult


# ── Single-turn pipeline ──────────────────────────────────────────────────────

async def run_turn(
    state: SharedInterviewState,
    answer_provider: AnswerProvider,
    selected_question: OrchestratorOutput | None = None,
) -> TurnResult:
    """Run one full interview turn end-to-end.

    If *selected_question* is provided (e.g. chosen by the user from a menu),
    it is used directly and the orchestrator is not called. Default (None)
    preserves existing behaviour — the orchestrator picks the question.
    """
    # 1. Orchestrator picks next question unless the caller pre-selected one.
    orchestrator_output = selected_question or select_next_question(state)
    state.asked_question_ids.append(orchestrator_output.question_id)

    # 2. Elicit the answer — support sync or async providers
    raw_answer = answer_provider(orchestrator_output.next_question)
    answer: str = await raw_answer if inspect.isawaitable(raw_answer) else raw_answer  # type: ignore[assignment]

    # 3. Record the turn before analysis so extractors always have a turn_id
    turn = InterviewTurn(
        turn_number=len(state.turns) + 1,
        question=orchestrator_output.next_question,
        question_rationale=orchestrator_output.rationale,
        answer=answer,
    )
    state.turns.append(turn)

    # 4. Parallel fan-out of the five analyzers (Constraint §26-1)
    known_node_ids = [n.id for n in state.graph.nodes if n.status != "superseded"]
    # surface_form → [node_ids] so entity extractor can flag is_ambiguous correctly
    alias_to_nodes = _alias_to_nodes_map(state)
    ambiguous_aliases = {k: v for k, v in alias_to_nodes.items() if len(v) > 1}

    entity_out, relationship_out, attribute_out, clarification_out, coverage_out = (
        await asyncio.gather(
            extract_entities(turn, alias_to_nodes),
            extract_relationships(turn, known_node_ids),
            extract_attributes(turn, known_node_ids),
            detect_clarifications(turn, ambiguous_aliases),
            update_coverage(turn, state.coverage),
        )
    )

    # 5. Resolve any open ambiguity that this turn's answer addressed
    _resolve_answered_ambiguities(state, orchestrator_output, entity_out)

    # 6. Graph mapper runs AFTER the extractors because it consumes their outputs
    mapping_out = await map_to_graph_updates(
        entity_out, relationship_out, attribute_out
    )

    # 7. Bundle into a ProposedUpdate and commit via the Phase 3 updater
    update = ProposedUpdate(
        source_turn_id=turn.turn_id,
        entity_extraction=entity_out,
        relationship_extraction=relationship_out,
        attribute_extraction=attribute_out,
        clarifications=clarification_out,
        graph_mapping=mapping_out,
    )
    state.proposed_updates.append(update)
    apply_result = apply_proposed_update(state, update)

    # 8. Book-keep coverage + convert clarifications into open questions
    state.coverage = coverage_out.updated_scores
    _append_clarifications_as_open_questions(state, clarification_out)

    if apply_result.has_rejections:
        logger.info(
            "Turn %d committed with rejections; see ApplyResult for reasons.",
            turn.turn_number,
        )

    return TurnResult(
        orchestrator_output=orchestrator_output,
        turn=turn,
        proposed_update=update,
        apply_result=apply_result,
    )


# ── Multi-turn loop ───────────────────────────────────────────────────────────

async def run_interview(
    state: SharedInterviewState,
    answer_provider: AnswerProvider,
    max_turns: int = DEFAULT_MAX_TURNS,
    should_stop: Callable[[SharedInterviewState], bool] | None = None,
) -> list[TurnResult]:
    """
    Run run_turn repeatedly until either max_turns is reached or
    should_stop(state) returns True. Returns one TurnResult per completed turn.
    """
    results: list[TurnResult] = []
    for _ in range(max_turns):
        if should_stop is not None and should_stop(state):
            break
        results.append(await run_turn(state, answer_provider))
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _alias_to_nodes_map(state: SharedInterviewState) -> dict[str, list[str]]:
    """
    Map every surface form (label + aliases) to the list of non-superseded node
    IDs that carry it. Passed to the entity extractor so it can flag is_ambiguous
    when a name matches multiple existing nodes.
    """
    result: dict[str, list[str]] = {}
    for node in state.graph.nodes:
        if node.status == "superseded":
            continue
        for surface in [node.label, *node.aliases]:
            result.setdefault(surface, []).append(node.id)
    return result


def _resolve_answered_ambiguities(
    state: SharedInterviewState,
    orchestrator_output: OrchestratorOutput,
    entity_out: EntityExtractionOutput,
) -> None:
    """
    After every turn, check whether any unresolved ambiguity was clarified.

    Resolution heuristic: the interviewee named an unambiguous entity whose
    label contains the ambiguity's target string (e.g. "Richard Jones" resolves
    the "Richard" ambiguity).  We check all ambiguities — not just the one the
    orchestrator asked about — so that user-chosen alternate questions can still
    trigger resolution when the answer happens to name the right entity.
    """
    unambiguous = [e for e in entity_out.entities if not e.is_ambiguous]
    for amb in state.ambiguities:
        if amb.resolved:
            continue
        for entity in unambiguous:
            if amb.target.lower() in entity.label.lower():
                amb.resolved = True
                logger.info(
                    "Ambiguity %r resolved — interviewee named %r.",
                    amb.ambiguity_id,
                    entity.label,
                )
                break


def _append_clarifications_as_open_questions(
    state: SharedInterviewState,
    clarification_out: ClarificationOutput,
) -> None:
    """
    Clarifications emitted during the turn become OpenQuestions that the
    orchestrator can draw from in later turns.
    """
    for c in clarification_out.clarifications:
        state.open_questions.append(
            OpenQuestion(
                text=c.suggested_question,
                rationale=c.reason,
                target_category="clarification",
                priority=c.priority,
            )
        )
