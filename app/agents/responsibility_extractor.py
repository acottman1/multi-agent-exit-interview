"""
Responsibility extraction agent (brief engine).

Slice contract (Constraint §26-4): receives only the current turn text and
the list of responsibility titles already captured in the brief.
"""
from __future__ import annotations

from pathlib import Path

from app.agents.llm_client import MAX_TOKENS, MODEL, get_client
from app.brief.extraction_models import ResponsibilityExtractionOutput
from app.core.models import InterviewTurn

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "responsibility_extractor.md").read_text()


def _format_known(known_titles: list[str]) -> str:
    if not known_titles:
        return "(none)"
    return "\n".join(f"  - {t}" for t in known_titles)


async def extract_responsibilities(
    turn: InterviewTurn,
    known_titles: list[str],
) -> ResponsibilityExtractionOutput:
    """
    Extract discrete responsibilities from a single interview turn.

    known_titles: titles of responsibilities already captured in the brief,
    so the LLM can flag whether this is an update to an existing item.
    """
    user_msg = (
        f"Interview question: {turn.question}\n\n"
        f"Interviewee's answer: {turn.answer}\n\n"
        f"Responsibilities already captured in the brief:\n"
        f"{_format_known(known_titles)}"
    )
    client = get_client()
    return await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        response_model=ResponsibilityExtractionOutput,
    )
