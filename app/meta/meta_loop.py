"""
Meta-loop orchestrator — the full pipeline for creating a new DomainConfig.

Stages:
  1. Meta-interview   — 8 hardcoded questions elicit the domain description
  2. Config generation — transcript → DomainConfig (instructor-enforced LLM call)
  3. Validation       — programmatic gap detection (no LLM)
  4. Review + preview — human-readable summary + first-question preview
  5. Clarification    — up to max_clarification_rounds of targeted follow-ups
  6. Name generation  — slug / display_name / tags from finalized config
  7. Save             — persist to config store

Callers supply two answer providers:
  answer_provider   — receives question text, returns free-text answer (meta Q&A
                      and clarification questions)
  confirm_provider  — receives the formatted review, returns "approve" or free text
                      describing requested changes (defaults to answer_provider)
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Union

from app.config.config_store import save_domain_config
from app.config.domain_config import DomainConfig
from app.meta.config_generator import generate_domain_config
from app.meta.config_reviewer import ConfigReview, format_approval_prompt, review_config
from app.meta.config_validator import validate_config
from app.meta.meta_interview import MetaTurn, run_meta_interview
from app.meta.name_generator import ConfigNamingOutput, generate_config_name

logger = logging.getLogger(__name__)

AnswerProvider = Union[
    Callable[[str], Awaitable[str]],
    Callable[[str], str],
]

_APPROVE_KEYWORDS = {"approve", "yes", "ok", "looks good", "save", "done", "go ahead"}
_DEFAULT_MAX_CLARIFICATION_ROUNDS = 2


@dataclass
class MetaLoopResult:
    config: DomainConfig
    naming: ConfigNamingOutput
    config_path: Path
    meta_turns: list[MetaTurn]
    clarification_turns: list[MetaTurn] = field(default_factory=list)
    gaps_resolved: bool = True
    rounds_taken: int = 0


# ── Public entry point ────────────────────────────────────────────────────────

async def run_meta_loop(
    answer_provider: AnswerProvider,
    confirm_provider: AnswerProvider | None = None,
    store_dir: Path | None = None,
    max_clarification_rounds: int = _DEFAULT_MAX_CLARIFICATION_ROUNDS,
) -> MetaLoopResult:
    """
    Run the full meta-loop and return the saved DomainConfig.

    confirm_provider defaults to answer_provider if not supplied.
    store_dir defaults to the config store default directory.
    """
    _confirm = confirm_provider or answer_provider

    # Stage 1: Meta-interview
    logger.info("Stage 1: running meta-interview (%d questions)", 8)
    meta_turns = await run_meta_interview(answer_provider)

    # Stage 2: Generate initial config from transcript
    logger.info("Stage 2: generating DomainConfig from transcript")
    all_turns = list(meta_turns)
    config = await generate_domain_config(all_turns)
    logger.info("Generated config: %r (%d categories)", config.domain_name, len(config.coverage_categories))

    # Stages 3–5: Validate → review → optional clarification rounds
    clarification_turns: list[MetaTurn] = []
    rounds_taken = 0
    gaps_resolved = True

    for round_num in range(max_clarification_rounds + 1):
        gaps = validate_config(config)
        preview_q = _get_preview_question(config)
        review = review_config(config, gaps, preview_question=preview_q)

        approval_text = format_approval_prompt(review)

        if review.is_valid and round_num > 0:
            logger.info("Stage 3–5: gaps resolved after %d clarification round(s)", round_num)
            break

        # Ask for user approval (or clarification if errors remain)
        raw = _confirm(approval_text)
        user_response: str = await raw if inspect.isawaitable(raw) else raw  # type: ignore[assignment]

        if _is_approval(user_response):
            if not review.is_valid:
                gaps_resolved = False
                logger.warning("User approved config with outstanding errors.")
            break

        # Not approved — ask clarification questions, then regenerate
        if not review.clarification_questions:
            logger.info("No clarification questions available; saving as-is.")
            break

        logger.info(
            "Stage 5: clarification round %d/%d",
            round_num + 1, max_clarification_rounds,
        )
        round_turns = await _run_clarification_round(
            answer_provider, review.clarification_questions
        )
        clarification_turns.extend(round_turns)
        all_turns = list(meta_turns) + clarification_turns
        config = await generate_domain_config(all_turns)
        rounds_taken = round_num + 1

    # Stage 6: Name generation
    logger.info("Stage 6: generating config name")
    naming = await generate_config_name(config)
    config.domain_name = naming.slug
    config.display_name = naming.display_name
    config.description = naming.description

    # Stage 7: Save
    logger.info("Stage 7: saving config as %r", naming.slug)
    save_kwargs: dict = {"config": config, "slug": naming.slug}
    if store_dir is not None:
        save_kwargs["store_dir"] = store_dir
    config_path = save_domain_config(**save_kwargs)
    logger.info("Config saved to %s", config_path)

    return MetaLoopResult(
        config=config,
        naming=naming,
        config_path=config_path,
        meta_turns=meta_turns,
        clarification_turns=clarification_turns,
        gaps_resolved=gaps_resolved,
        rounds_taken=rounds_taken,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _run_clarification_round(
    answer_provider: AnswerProvider,
    questions: list[str],
) -> list[MetaTurn]:
    turns: list[MetaTurn] = []
    for i, q in enumerate(questions, start=1):
        raw = answer_provider(q)
        answer: str = await raw if inspect.isawaitable(raw) else raw  # type: ignore[assignment]
        turns.append(MetaTurn(question_number=100 + i, question=q, rationale="clarification", answer=answer))
    return turns


def _is_approval(response: str) -> bool:
    return response.strip().lower() in _APPROVE_KEYWORDS


def _get_preview_question(config: DomainConfig) -> str | None:
    """Return the first question the engine would ask with this config."""
    try:
        from app.brief.schema import BriefMeta, RoleBrief
        from app.brief.session import BriefSessionState
        from app.agents.brief_orchestrator import select_brief_question

        meta = BriefMeta(
            session_id="preview",
            domain_name=config.domain_name,
            interviewee_name="(preview)",
            role_title="(preview)",
        )
        state = BriefSessionState(domain_config=config, brief=RoleBrief(meta=meta))
        return select_brief_question(state).next_question
    except Exception:
        return None
