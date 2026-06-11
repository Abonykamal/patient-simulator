"""Tests for src.core.exceptions — the normalized LLM error hierarchy.

The client's fallback logic catches by base class, so the hierarchy is
load-bearing: a bug here would silently break 429/5xx routing.
"""

from src.core.exceptions import (
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMServerError,
)


def test_all_llm_errors_share_a_base():
    assert issubclass(LLMRateLimitError, LLMError)
    assert issubclass(LLMServerError, LLMError)
    assert issubclass(LLMResponseError, LLMError)


def test_carries_status_code_and_provider():
    err = LLMRateLimitError("rate limited", status_code=429, provider="gemini")
    assert err.status_code == 429
    assert err.provider == "gemini"
    assert "rate limited" in str(err)
