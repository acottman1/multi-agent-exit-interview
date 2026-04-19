"""
Clarification-detection agent (Phase 5).
"""
from __future__ import annotations

from pathlib import Path

from app.agents.llm_client import MAX_TOKENS, MODEL, get_client
from app.core.models import ClarificationOutput, InterviewTurn

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "clarification_detector.md").read_text()


def _format_ambiguous_aliases(ambiguous_aliases: dict[str, list[str]]) -> str:
    if not ambiguous_aliases:
        return "  (none)"
    return "\n".join(
        f"  {alias!r} → could be: {ids}" for alias, ids in ambiguous_aliases.items()
    )


async def detect_clarifications(
    turn: InterviewTurn,
    ambiguous_aliases: dict[str, list[str]],
) -> ClarificationOutput:
    """
    Slice contract: receives the current turn and the map of already-known
    ambiguous surface forms so the LLM avoids flagging duplicates.
    """
    user_msg = (
        f"Interview question: {turn.question}\n\n"
        f"Interviewee's answer: {turn.answer}\n\n"
        f"Already-known ambiguous aliases (do NOT re-flag these):\n"
        f"{_format_ambiguous_aliases(ambiguous_aliases)}"
    )

    client = get_client()
    return await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        response_model=ClarificationOutput,
    )
