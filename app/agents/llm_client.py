"""
Shared instructor-wrapped Anthropic async client.

Import `get_client()` in each agent module. The indirection makes it trivial
to monkeypatch in contract tests without touching real API credentials.

On import, we look for a .env file at the project root and load any keys that
are not already set in the environment — so setting ANTHROPIC_API_KEY in the
shell always wins over the file.
"""
from __future__ import annotations

import os
from pathlib import Path

import anthropic
import instructor

MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
MAX_TOKENS: int = 2048

# ── .env loader (no extra dependency required) ────────────────────────────────

def _load_dotenv() -> None:
    """Read PROJECT_ROOT/.env and populate os.environ for any missing keys."""
    env_file = Path(__file__).parent.parent.parent / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")  # tolerate quoted values
        os.environ.setdefault(key, value)


_load_dotenv()


# ── Client factory ────────────────────────────────────────────────────────────

def get_client() -> instructor.AsyncInstructor:
    return instructor.from_anthropic(anthropic.AsyncAnthropic())
