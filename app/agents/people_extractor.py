"""
People extraction agent (brief engine).

Slice contract (Constraint §26-4): receives only the current turn text and
a map of canonical names already known (for disambiguation and dedup).
"""
from __future__ import annotations

from pathlib import Path

from app.agents.llm_client import MAX_TOKENS, MODEL, get_client
from app.brief.extraction_models import PeopleExtractionOutput
from app.core.models import InterviewTurn

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "people_extractor.md").read_text()


def _format_known(known_people: dict[str, str]) -> str:
    if not known_people:
        return "(none)"
    return "\n".join(f"  - {name} ({role})" for name, role in known_people.items())


async def extract_people(
    turn: InterviewTurn,
    known_people: dict[str, str],
) -> PeopleExtractionOutput:
    """
    Extract key people and relationships from a single interview turn.

    known_people: canonical_name → role/title for people already in the brief.
    Used to resolve first-name references and avoid duplicate entries.
    """
    user_msg = (
        f"Interview question: {turn.question}\n\n"
        f"Interviewee's answer: {turn.answer}\n\n"
        f"People already captured in the brief (canonical name → role):\n"
        f"{_format_known(known_people)}"
    )
    client = get_client()
    return await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        response_model=PeopleExtractionOutput,
    )
