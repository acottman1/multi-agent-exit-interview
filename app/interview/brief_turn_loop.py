"""
Brief-engine interview turn loop.

A single turn runs as follows:
  1. Orchestrator selects the next question from DomainConfig question banks.
  2. Answer provider supplies the interviewee's answer.
  3. Six agents run CONCURRENTLY via asyncio.gather (Constraint §26-1):
       responsibility_extractor, people_extractor, systems_extractor,
       implicit_knowledge_extractor, risk_extractor, clarification_detector.
  4. Brief updater merges extraction outputs into the RoleBrief in place.
  5. Coverage scores are recomputed from brief content (programmatic, no LLM).
  6. Clarifications become open questions for future turns.

run_brief_interview() loops run_brief_turn() until max_turns or should_stop().
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Awaitable, Callable, Union

from pydantic import BaseModel

from app.agents.brief_orchestrator import select_brief_question
from app.agents.clarification_detector import detect_clarifications
from app.agents.implicit_knowledge_extractor import extract_implicit_knowledge
from app.agents.people_extractor import extract_people
from app.agents.responsibility_extractor import extract_responsibilities
from app.agents.risk_extractor import extract_risks
from app.agents.systems_extractor import extract_systems
from app.brief.session import BriefSessionState
from app.brief.updater import BriefUpdateResult, merge_into_brief
from app.core.models import (
    ClarificationOutput,
    InterviewTurn,
    OpenQuestion,
    OrchestratorOutput,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_TURNS: int = 15

AnswerProvider = Union[
    Callable[[str], Awaitable[str]],
    Callable[[str], str],
]

# Items-to-reach-half-score per category (k in n / (n + k)).
# Lower k = faster ramp; higher k = more conservative scoring.
_COVERAGE_K: int = 3


class BriefTurnResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    orchestrator_output: OrchestratorOutput
    turn: InterviewTurn
    update_result: BriefUpdateResult


# ── Single-turn pipeline ──────────────────────────────────────────────────────

async def run_brief_turn(
    state: BriefSessionState,
    answer_provider: AnswerProvider,
    selected_question: OrchestratorOutput | None = None,
) -> BriefTurnResult:
    """
    Run one full brief-engine interview turn end-to-end.

    If *selected_question* is provided (e.g. user chose from a menu),
    it is used directly and the orchestrator is not called.
    """
    # 1. Select question
    orchestrator_output = selected_question or select_brief_question(state)
    state.asked_question_ids.append(orchestrator_output.question_id)

    # 2. Elicit answer — support sync or async providers
    raw_answer = answer_provider(orchestrator_output.next_question)
    answer: str = await raw_answer if inspect.isawaitable(raw_answer) else raw_answer  # type: ignore[assignment]

    # 3. Record turn
    turn = InterviewTurn(
        turn_number=len(state.turns) + 1,
        question=orchestrator_output.next_question,
        question_rationale=orchestrator_output.rationale,
        answer=answer,
    )
    state.turns.append(turn)

    # 4. Build minimal state slices for each agent (Constraint §26-4)
    known_titles_resp = [r.title for r in state.brief.responsibilities]
    known_people_map = {p.canonical_name: p.role_title for p in state.brief.people}
    known_systems = [s.canonical_name for s in state.brief.systems]
    known_titles_impl = [i.title for i in state.brief.implicit_knowledge]
    known_titles_risk = [r.title for r in state.brief.risks]
    ambiguous_aliases = _build_ambiguous_aliases(state)

    # 5. Parallel fan-out of six agents (Constraint §26-1)
    (
        resp_out,
        people_out,
        systems_out,
        impl_out,
        risk_out,
        clarification_out,
    ) = await asyncio.gather(
        extract_responsibilities(turn, known_titles_resp),
        extract_people(turn, known_people_map),
        extract_systems(turn, known_systems),
        extract_implicit_knowledge(turn, known_titles_impl),
        extract_risks(turn, known_titles_risk),
        detect_clarifications(turn, ambiguous_aliases),
    )

    # 6. Merge all extraction outputs into the brief in place
    update_result = merge_into_brief(
        state.brief,
        source_turn_id=turn.turn_id,
        responsibilities=resp_out.responsibilities,
        people=people_out.people,
        systems=systems_out.systems,
        implicit_knowledge=impl_out.items,
        risks=risk_out.risks,
    )

    # 7. Recompute coverage from brief content
    _recompute_coverage(state)

    # 8. Convert clarifications to open questions
    _append_clarifications(state, clarification_out)

    # 9. Sync brief meta
    state.brief.meta.completeness_score = state.weighted_completeness()
    state.brief.meta.open_questions_count = len(state.open_questions)

    if update_result.has_changes:
        logger.info(
            "Turn %d committed: %s",
            turn.turn_number,
            update_result.summary(),
        )

    return BriefTurnResult(
        orchestrator_output=orchestrator_output,
        turn=turn,
        update_result=update_result,
    )


# ── Multi-turn loop ───────────────────────────────────────────────────────────

async def run_brief_interview(
    state: BriefSessionState,
    answer_provider: AnswerProvider,
    max_turns: int = DEFAULT_MAX_TURNS,
    should_stop: Callable[[BriefSessionState], bool] | None = None,
) -> list[BriefTurnResult]:
    """
    Loop run_brief_turn() until max_turns or should_stop(state) returns True.

    Default stopping condition: mandatory coverage met (all mandatory categories
    above their min_score). Pass a custom should_stop to override.
    """
    _should_stop = should_stop or (lambda s: s.mandatory_coverage_met())
    results: list[BriefTurnResult] = []
    for _ in range(max_turns):
        if _should_stop(state):
            break
        results.append(await run_brief_turn(state, answer_provider))
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _recompute_coverage(state: BriefSessionState) -> None:
    """
    Recompute coverage scores for every category from the brief's current
    item counts. Uses the formula score = n / (n + k) where k = _COVERAGE_K,
    so the score asymptotically approaches 1.0 as item count grows.
    """
    section_counts = state.brief.section_item_count()
    for cat in state.domain_config.coverage_categories:
        target = state.domain_config.extraction_targets.get(cat.name)
        if target is None:
            continue
        n = section_counts.get(target.section_key, 0)
        state.coverage[cat.name] = n / (n + _COVERAGE_K)


def _build_ambiguous_aliases(state: BriefSessionState) -> dict[str, list[str]]:
    """
    Build the surface-form → [canonical_names] map for clarification_detector.
    Seeds from context_briefing (known first names), then adds brief people.
    """
    result: dict[str, list[str]] = {}
    if state.context_briefing:
        for alias, names in state.context_briefing.alias_map().items():
            result.setdefault(alias, []).extend(names)
    for person in state.brief.people:
        first = person.canonical_name.split()[0]
        result.setdefault(first, []).append(person.canonical_name)
        result.setdefault(person.canonical_name, []).append(person.canonical_name)
    # Only keep entries where the alias is actually ambiguous (2+ targets)
    return {k: list(dict.fromkeys(v)) for k, v in result.items() if len(set(v)) > 1}


def _append_clarifications(
    state: BriefSessionState,
    clarification_out: ClarificationOutput,
) -> None:
    for c in clarification_out.clarifications:
        state.open_questions.append(
            OpenQuestion(
                text=c.suggested_question,
                rationale=c.reason,
                target_category="clarification",
                priority=c.priority,
            )
        )
