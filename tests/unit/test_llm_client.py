"""Tests for src.llm.client — the provider-agnostic complete() and the
ADR-012 fallback contract: 429 -> backoff then fallback; 5xx -> fallback
immediately; no fallback -> re-raise.

Providers are replaced with fakes, so no real API is ever called. Sleep is
neutered so backoff is instant.
"""

import pytest

from src.core.exceptions import LLMRateLimitError, LLMServerError
from src.llm import client as client_mod


class FakeProvider:
    """A provider whose calls yield scripted outcomes.

    ``outcomes`` is a list of ("ok", value) or ("raise", exception); the last
    entry repeats for any further calls. ``calls`` records how many times the
    provider was invoked (so we can assert retry behavior).
    """

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = 0

    async def complete(self, model, prompt):
        kind, value = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if kind == "raise":
            raise value
        return value


@pytest.fixture
def patch_providers(monkeypatch):
    def _install(gemini, groq):
        registry = {"gemini": gemini, "groq": groq}
        monkeypatch.setattr(client_mod, "get_provider", lambda name: registry[name])

    return _install


@pytest.fixture(autouse=True)
def _instant_backoff(monkeypatch):
    async def fake_sleep(_):
        return None

    monkeypatch.setattr("src.llm.retry.asyncio.sleep", fake_sleep)


async def test_returns_primary_response_and_skips_fallback(patch_providers):
    gemini = FakeProvider([("ok", "patient says hi")])
    groq = FakeProvider([("ok", "fallback")])
    patch_providers(gemini, groq)

    assert await client_mod.complete("patient", "hello") == "patient says hi"
    assert groq.calls == 0


async def test_falls_back_immediately_on_server_error(patch_providers):
    gemini = FakeProvider([("raise", LLMServerError("503"))])
    groq = FakeProvider([("ok", "fallback")])
    patch_providers(gemini, groq)

    assert await client_mod.complete("patient", "hello") == "fallback"
    assert gemini.calls == 1  # 5xx is not retried before falling back


async def test_retries_then_falls_back_on_persistent_rate_limit(patch_providers):
    gemini = FakeProvider([("raise", LLMRateLimitError("429"))])
    groq = FakeProvider([("ok", "fallback")])
    patch_providers(gemini, groq)

    assert await client_mod.complete("patient", "hello") == "fallback"
    assert gemini.calls == 5  # 1 initial attempt + 4 backoff retries


async def test_recovers_during_backoff_without_using_fallback(patch_providers):
    gemini = FakeProvider(
        [
            ("raise", LLMRateLimitError("429")),
            ("raise", LLMRateLimitError("429")),
            ("ok", "recovered"),
        ]
    )
    groq = FakeProvider([("ok", "fallback")])
    patch_providers(gemini, groq)

    assert await client_mod.complete("patient", "hello") == "recovered"
    assert groq.calls == 0


async def test_no_fallback_propagates_the_error(patch_providers):
    # The judge (groq, no fallback) must surface failures, not hide them.
    gemini = FakeProvider([("ok", "unused")])
    groq = FakeProvider([("raise", LLMServerError("500"))])
    patch_providers(gemini, groq)

    with pytest.raises(LLMServerError):
        await client_mod.complete("judge", "evaluate this transcript")
