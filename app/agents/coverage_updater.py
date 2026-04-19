"""
Coverage-update agent (Phase 5).
"""
from __future__ import annotations

from pathlib import Path

from app.agents.llm_client import MAX_TOKENS, MODEL, get_client
from app.core.models import CoverageOutput, CoverageScores, InterviewTurn

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "coverage_updater.md").read_text()


async def update_coverage(
    turn: InterviewTurn,
    current_coverage: CoverageScores,
) -> CoverageOutput:
    """
    Slice contract: receives only the current turn and the existing coverage
    scores — never the full state or graph.
    """
    scores_block = "\n".join(
        f"  {field}: {getattr(current_coverage, field):.2f}"
        for field in CoverageScores.model_fields
    )
    user_msg = (
        f"Interview question: {turn.question}\n\n"
        f"Interviewee's answer: {turn.answer}\n\n"
        f"Current coverage scores:\n{scores_block}"
    )

    client = get_client()
    return await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        response_model=CoverageOutput,
    )
