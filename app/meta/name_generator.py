"""
Config name generator — derives a human-friendly slug, display name,
description, and tags from a finalized DomainConfig.

Called just before saving so the user sees a clean identity for the config
in the instance picker.
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

from app.agents.llm_client import get_client
from app.config.domain_config import DomainConfig

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "name_generator.md").read_text()
_MAX_TOKENS = 512


class ConfigNamingOutput(BaseModel):
    slug: str
    display_name: str
    description: str
    tags: list[str]


async def generate_config_name(config: DomainConfig) -> ConfigNamingOutput:
    """Generate a memorable identity for the config from its contents."""
    user_msg = (
        f"domain_name: {config.domain_name}\n"
        f"display_name: {config.display_name}\n"
        f"description: {config.description}\n"
        f"categories: {', '.join(config.category_names())}\n"
        f"mandatory: {', '.join(c.name for c in config.mandatory_categories())}"
    )
    client = get_client()
    return await client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        response_model=ConfigNamingOutput,
    )
