"""
Risk extraction agent (brief engine).

Surfaces single points of failure, fragile dependencies, and known-but-unmitigated
risks from interview answers. Slice contract (Constraint §26-4): receives only the
current turn text and risk titles already captured.
"""
from __future__ import annotations

from pathlib import Path

from app.agents.llm_client import MAX_TOKENS, MODEL, get_client
from app.brief.extraction_models import RiskExtractionOutput
from app.core.models import InterviewTurn

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "risk_extractor.md").read_text()


def _format_known(known_titles: list[str]) -> str:
    if not known_titles:
        return "(none)"
    return "\n".join(f"  - {t}" for t in known_titles)


async def extract_risks(
    turn: InterviewTurn,
    known_titles: list[str],
) -> RiskExtractionOutput:
    """
    Extract risks and single points of failure from a single interview turn.

    known_titles: titles of risks already captured in the brief,
    to avoid duplicate entries.
    """
    user_msg = (
        f"Interview question: {turn.question}\n\n"
        f"Interviewee's answer: {turn.answer}\n\n"
        f"Risks already captured in the brief:\n"
        f"{_format_known(known_titles)}"
    )
    client = get_client()
    return await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        response_model=RiskExtractionOutput,
    )
