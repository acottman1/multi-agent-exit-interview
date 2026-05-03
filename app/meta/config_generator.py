"""
Config generator — synthesizes a DomainConfig from a meta-interview transcript.

Single LLM call at the end of the meta-interview (or after clarification rounds).
Uses instructor to enforce the DomainConfig Pydantic shape.
"""
from __future__ import annotations

from pathlib import Path

from app.agents.llm_client import get_client
from app.config.domain_config import DomainConfig
from app.meta.meta_interview import MetaTurn, format_transcript

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "config_generator.md").read_text()

# DomainConfig is large (question banks, templates); allow plenty of tokens.
_MAX_TOKENS = 6000


async def generate_domain_config(turns: list[MetaTurn]) -> DomainConfig:
    """
    Synthesize a DomainConfig from the full meta-interview transcript.

    Pass both the original 8 turns and any clarification turns that followed;
    later turns override earlier ones when there's a contradiction.
    """
    transcript = format_transcript(turns)
    user_msg = f"Meta-interview transcript:\n\n{transcript}"

    client = get_client()
    return await client.messages.create(
        model=_model(),
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        response_model=DomainConfig,
    )


def _model() -> str:
    import os
    return os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
