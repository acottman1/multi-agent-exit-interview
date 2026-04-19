"""
Shared instructor-wrapped Anthropic async client.

Import `get_client()` in each agent module. The indirection makes it trivial
to monkeypatch in contract tests without touching real API credentials.
"""
from __future__ import annotations

import anthropic
import instructor

MODEL: str = "claude-haiku-4-5-20251001"
MAX_TOKENS: int = 2048


def get_client() -> instructor.AsyncInstructor:
    return instructor.from_anthropic(anthropic.AsyncAnthropic())
