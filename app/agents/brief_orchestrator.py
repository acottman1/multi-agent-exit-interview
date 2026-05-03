"""
Brief orchestrator — selects the next question for the brief engine.

Reads question banks from DomainConfig instead of hardcoded _FALLBACK_VARIANTS.
Preserves the same priority ladder as the graph-engine orchestrator but
replaces Priority 3 (probe low-confidence nodes) with Priority 3 (mandatory
category below min_score), which is more direct for the brief engine.

Priority ladder (highest first):
  1. Unresolved ambiguity with highest priority
  2. Seeded open question not yet asked, highest priority first
  3. Mandatory category furthest below its min_score threshold
  4. Lowest-coverage category overall (fallback)
"""
from __future__ import annotations

import hashlib

from app.brief.session import BriefSessionState
from app.core.models import ClarificationPriority, OrchestratorOutput

_PRIORITY_RANK: dict[ClarificationPriority, int] = {"high": 0, "medium": 1, "low": 2}


# ── Public entry points ───────────────────────────────────────────────────────

def select_brief_questions(
    state: BriefSessionState, n: int = 5
) -> list[OrchestratorOutput]:
    """
    Return up to *n* candidate questions ranked by priority ladder.

    Pure function — does NOT mutate state. The default (index 0) is the same
    question that select_brief_question() would have returned.
    """
    candidates: list[OrchestratorOutput] = []
    candidates.extend(_ambiguity_questions(state))
    candidates.extend(_open_questions(state))
    candidates.extend(_mandatory_gap_questions(state))
    candidates.extend(_coverage_gap_questions(state))

    seen: set[str] = set()
    unique: list[OrchestratorOutput] = []
    for c in candidates:
        if c.question_id not in seen:
            seen.add(c.question_id)
            unique.append(c)

    return unique[:n]


def select_brief_question(state: BriefSessionState) -> OrchestratorOutput:
    """Pick the single highest-priority next question. Pure function."""
    return select_brief_questions(state, n=1)[0]


# ── Priority 1: unresolved ambiguities ────────────────────────────────────────

def _ambiguity_questions(state: BriefSessionState) -> list[OrchestratorOutput]:
    pending = [
        a for a in state.ambiguities
        if not a.resolved
        and _amb_qid(a.ambiguity_id) not in state.asked_question_ids
    ]
    pending.sort(key=lambda a: _PRIORITY_RANK[a.priority])
    return [
        OrchestratorOutput(
            next_question=a.suggested_question,
            rationale=f"Resolving ambiguity: {a.reason}",
            target_category="ambiguity_resolution",
            question_id=_amb_qid(a.ambiguity_id),
        )
        for a in pending
    ]


def _amb_qid(ambiguity_id: str) -> str:
    return f"q_amb_{ambiguity_id}"


# ── Priority 2: pending open questions ────────────────────────────────────────

def _open_questions(state: BriefSessionState) -> list[OrchestratorOutput]:
    pending = [
        q for q in state.open_questions
        if q.question_id not in state.asked_question_ids
    ]
    pending.sort(key=lambda q: _PRIORITY_RANK[q.priority])
    return [
        OrchestratorOutput(
            next_question=q.text,
            rationale=q.rationale,
            target_category=q.target_category,
            question_id=q.question_id,
        )
        for q in pending
    ]


# ── Priority 3: mandatory category furthest below min_score ───────────────────

def _mandatory_gap_questions(state: BriefSessionState) -> list[OrchestratorOutput]:
    gaps = [
        cat for cat in state.domain_config.mandatory_categories()
        if state.coverage.get(cat.name, 0.0) < cat.min_score
        and _gap_qid(cat.name, state) not in state.asked_question_ids
    ]
    # Widest gap first (actual score - min_score, most negative first)
    gaps.sort(key=lambda c: state.coverage.get(c.name, 0.0) - c.min_score)
    return [
        OrchestratorOutput(
            next_question=_pick_variant(state, cat.name),
            rationale=(
                f"Mandatory category {cat.name!r} at "
                f"{state.coverage.get(cat.name, 0.0):.2f} "
                f"(target {cat.min_score:.2f})."
            ),
            target_category=cat.name,
            question_id=_gap_qid(cat.name, state),
        )
        for cat in gaps
    ]


# ── Priority 4: lowest-coverage category overall ─────────────────────────────

def _coverage_gap_questions(state: BriefSessionState) -> list[OrchestratorOutput]:
    cats = sorted(
        state.domain_config.coverage_categories,
        key=lambda c: state.coverage.get(c.name, 0.0),
    )
    return [
        OrchestratorOutput(
            next_question=_pick_variant(state, cat.name),
            rationale=(
                f"Coverage for {cat.name!r} is "
                f"{state.coverage.get(cat.name, 0.0):.2f}; broadening the discussion."
            ),
            target_category=cat.name,
            question_id=_gap_qid(cat.name, state),
        )
        for cat in cats
        if state.domain_config.question_banks.get(cat.name)
    ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _gap_qid(category: str, state: BriefSessionState) -> str:
    return f"q_gap_{category}_{len(state.turns)}"


def _pick_variant(state: BriefSessionState, category: str) -> str:
    """
    Pick an unasked question variant for the category.

    Starts from a session-seeded index then advances past any text that was
    already asked this session, so consecutive turns get different questions.
    """
    variants = state.domain_config.question_banks.get(category, [])
    if not variants:
        return f"Can you tell me more about {category.replace('_', ' ')}?"
    asked_texts = {t.question for t in state.turns}
    base = int(hashlib.md5(f"{state.session_id}:{category}".encode()).hexdigest(), 16)
    for i in range(len(variants)):
        candidate = variants[(base + i) % len(variants)]
        if candidate not in asked_texts:
            return candidate
    # All variants exhausted — cycle back to base
    return variants[base % len(variants)]
