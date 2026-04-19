"""
Conftest for golden evaluation tests.

These tests make real Anthropic API calls to evaluate LLM extraction quality.
They are skipped automatically when ANTHROPIC_API_KEY is not set so CI passes
without credentials.  Run them locally with a valid key to validate the
research question.

Usage:
    pytest tests/golden/ -v -s          # show live LLM output
    pytest tests/golden/ -m eval        # same, by marker
"""
from __future__ import annotations

import os
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "eval: live LLM evaluation — requires ANTHROPIC_API_KEY",
    )


# Applied to every test in this directory automatically.
requires_api_key = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live LLM evaluation",
)


@pytest.fixture(autouse=True)
def mark_eval(request):
    """Tag every golden test with @pytest.mark.eval and skip if no key."""
    request.applymarker(pytest.mark.eval)
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
