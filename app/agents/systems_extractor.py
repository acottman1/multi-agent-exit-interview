"""
Systems extraction agent (brief engine).

Slice contract (Constraint §26-4): receives only the current turn text and
the list of system canonical names already captured in the brief.
"""
from __future__ import annotations

from pathlib import Path

from app.agents.llm_client import MAX_TOKENS, MODEL, get_client
from app.brief.extraction_models import SystemsExtractionOutput
from app.core.models import InterviewTurn

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "systems_extractor.md").read_text()


def _format_known(known_systems: list[str]) -> str:
    if not known_systems:
        return "(none)"
    return "\n".join(f"  - {s}" for s in known_systems)


async def extract_systems(
    turn: InterviewTurn,
    known_systems: list[str],
) -> SystemsExtractionOutput:
    """
    Extract systems and tools from a single interview turn.

    known_systems: canonical names of systems already captured in the brief,
    used to normalize references and avoid duplicate entries.
    """
    user_msg = (
        f"Interview question: {turn.question}\n\n"
        f"Interviewee's answer: {turn.answer}\n\n"
        f"Systems already captured in the brief:\n"
        f"{_format_known(known_systems)}"
    )
    client = get_client()
    return await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        response_model=SystemsExtractionOutput,
    )
