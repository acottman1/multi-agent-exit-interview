"""
Attribute-extraction agent (Phase 5).
"""
from __future__ import annotations

from pathlib import Path

from app.agents.llm_client import MAX_TOKENS, MODEL, get_client
from app.core.models import AttributeExtractionOutput, InterviewTurn

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "attribute_extractor.md").read_text()


async def extract_attributes(
    turn: InterviewTurn,
    known_node_ids: list[str],
) -> AttributeExtractionOutput:
    """
    Slice contract: receives the current turn and existing node IDs so the LLM
    can anchor attributes to known entities without seeing full node data.
    """
    ids_block = "\n".join(f"  - {nid}" for nid in known_node_ids) or "  (none)"
    user_msg = (
        f"Interview question: {turn.question}\n\n"
        f"Interviewee's answer: {turn.answer}\n\n"
        f"Known node IDs already in the graph:\n{ids_block}"
    )

    client = get_client()
    return await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        response_model=AttributeExtractionOutput,
    )
