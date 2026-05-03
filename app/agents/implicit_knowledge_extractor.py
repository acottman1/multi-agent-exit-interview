"""
Implicit knowledge extraction agent (brief engine).

Targets the hardest section to fill: things the interviewee knows but has
never written down. Slice contract (Constraint §26-4): receives only the
current turn text and titles already captured.
"""
from __future__ import annotations

from pathlib import Path

from app.agents.llm_client import MAX_TOKENS, MODEL, get_client
from app.brief.extraction_models import ImplicitKnowledgeExtractionOutput
from app.core.models import InterviewTurn

_SYSTEM_PROMPT = (
    Path(__file__).parent / "prompts" / "implicit_knowledge_extractor.md"
).read_text()


def _format_known(known_titles: list[str]) -> str:
    if not known_titles:
        return "(none)"
    return "\n".join(f"  - {t}" for t in known_titles)


async def extract_implicit_knowledge(
    turn: InterviewTurn,
    known_titles: list[str],
) -> ImplicitKnowledgeExtractionOutput:
    """
    Extract implicit / undocumented knowledge items from a single interview turn.

    known_titles: titles of items already captured in the brief's
    implicit_knowledge section, to avoid duplicate entries.
    """
    user_msg = (
        f"Interview question: {turn.question}\n\n"
        f"Interviewee's answer: {turn.answer}\n\n"
        f"Implicit knowledge items already captured in the brief:\n"
        f"{_format_known(known_titles)}"
    )
    client = get_client()
    return await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        response_model=ImplicitKnowledgeExtractionOutput,
    )
