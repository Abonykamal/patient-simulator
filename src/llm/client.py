"""Provider-agnostic LLM client — the single entry point for all LLM calls.

Agent code calls ``complete(agent_name, prompt)`` and never knows which
provider answered. This module resolves the agent's config from AGENT_CONFIG,
calls the right provider, and applies the ADR-012 fallback contract:

- 429 (rate limit): retry the primary with exponential backoff; if it never
  clears, switch to the configured fallback.
- 5xx (server error): switch to the fallback immediately (no retry — the
  primary is down, retrying it is pointless). This falls out naturally because
  ``with_backoff`` only retries 429s, so a 5xx propagates straight to the
  fallback branch.
- No fallback configured: re-raise, so the caller decides how to degrade.
"""

from __future__ import annotations

from typing import Protocol

from src.core.config import AGENT_CONFIG, AgentLLMConfig
from src.core.exceptions import LLMRateLimitError, LLMServerError
from src.core.logging import get_logger
from src.llm.retry import with_backoff

log = get_logger("llm.client")


class Provider(Protocol):
    """The contract every provider adapter implements."""

    async def complete(self, model: str, prompt: str) -> str: ...


# Providers are built lazily and cached: importing an SDK and reading API keys
# is deferred until a provider is actually used (and kept out of unit tests,
# which replace get_provider with fakes).
_providers: dict[str, Provider] = {}


def get_provider(name: str) -> Provider:
    """Return the (cached) provider adapter for a provider name."""
    if name not in _providers:
        if name == "gemini":
            from src.llm.gemini import GeminiProvider

            _providers[name] = GeminiProvider()
        elif name == "groq":
            from src.llm.groq import GroqProvider

            _providers[name] = GroqProvider()
        else:
            raise ValueError(f"unknown provider: {name!r}")
    return _providers[name]


async def _call(config: AgentLLMConfig, prompt: str) -> str:
    """Make one provider call for the given config (no retry/fallback here)."""
    provider = get_provider(config.provider)
    return await provider.complete(config.model, prompt)


async def complete(agent_name: str, prompt: str) -> str:
    """Run an LLM completion for an agent, with backoff and fallback.

    Args:
        agent_name: A key in AGENT_CONFIG (e.g. "patient", "judge").
        prompt: The fully-constructed prompt text.

    Returns:
        The model's completion text.

    Raises:
        LLMError: If the primary fails and no fallback is configured, or if the
            fallback also fails.
    """
    config = AGENT_CONFIG[agent_name]
    try:
        # 429s are retried inside with_backoff; 5xx propagates out immediately.
        return await with_backoff(lambda: _call(config, prompt))
    except (LLMRateLimitError, LLMServerError) as exc:
        if config.fallback is None:
            log.error("llm_failed_no_fallback", agent=agent_name, error=str(exc))
            raise
        log.warning(
            "llm_fallback",
            agent=agent_name,
            primary=config.provider,
            fallback=config.fallback.provider,
            reason=type(exc).__name__,
        )
        return await with_backoff(lambda: _call(config.fallback, prompt))
