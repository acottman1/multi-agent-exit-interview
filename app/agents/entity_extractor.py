"""
Entity-extraction agent (Phase 5).

Replaces the stub in stubs.py. Constraint §26-5: the LLM signals is_ambiguous
and populates possible_matches when a surface form matches multiple existing
nodes; Pydantic enforces the output shape via instructor.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.agents.llm_client import MAX_TOKENS, MODEL, get_client
from app.core.models import EntityExtractionOutput, InterviewTurn

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "entity_extractor.md").read_text()


def _format_aliases(existing_aliases: dict[str, list[str]]) -> str:
    if not existing_aliases:
        return "(none)"
    lines = [f"  {alias!r} → {ids}" for alias, ids in existing_aliases.items()]
    return "\n".join(lines)


async def extract_entities(
    turn: InterviewTurn,
    existing_aliases: dict[str, list[str]],
) -> EntityExtractionOutput:
    """
    Slice contract (Constraint §26-4): receives only the current turn text and
    existing_aliases map — never the full SharedInterviewState.
    """
    user_msg = (
        f"Interview question: {turn.question}\n\n"
        f"Interviewee's answer: {turn.answer}\n\n"
        f"Existing nodes (surface-form → node IDs that share that alias):\n"
        f"{_format_aliases(existing_aliases)}"
    )

    client = get_client()
    return await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        response_model=EntityExtractionOutput,
    )
