"""
Eval-suite conftest.

Evals live outside tests/ so they are not affected by the global
QUILL_MOCK=true set in tests/conftest.py. Running:

    pytest evals/                          # skip if no API key
    ANTHROPIC_API_KEY=sk-... pytest evals/ # execute against real Claude
"""
import os
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "eval: LLM evaluation tests — require ANTHROPIC_API_KEY, not run by default",
    )


@pytest.fixture(autouse=True, scope="session")
def require_real_api_key():
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — skipping evals (run: ANTHROPIC_API_KEY=... pytest evals/)")
