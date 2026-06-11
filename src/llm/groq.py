"""Groq provider adapter.

Wraps the groq async client (OpenAI-style chat completions) and translates its
``APIError`` subclasses into our normalized exceptions. The SDK's own retries
are disabled (``max_retries=0``) so that backoff and fallback are owned solely
by ``retry.py`` / ``client.py`` (ADR-012), not silently duplicated here.
"""

from __future__ import annotations

import groq
from groq import AsyncGroq

from src.core.config import get_settings
from src.core.exceptions import (
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMServerError,
)


def _map_error(exc: Exception) -> LLMError:
    """Translate a groq APIError into a normalized LLM error.

    Routes by the HTTP ``status_code`` the SDK attaches (RateLimitError carries
    429): 429 -> rate limit, 5xx -> server error, else generic LLM error.
    """
    status = getattr(exc, "status_code", None)
    if status == 429:
        return LLMRateLimitError(str(exc), status_code=status, provider="groq")
    if status is not None and status >= 500:
        return LLMServerError(str(exc), status_code=status, provider="groq")
    return LLMError(str(exc), status_code=status, provider="groq")


class GroqProvider:
    """Async adapter over the Groq chat completions API."""

    def __init__(self, api_key: str | None = None) -> None:
        self._client = AsyncGroq(
            api_key=api_key or get_settings().groq_api_key,
            max_retries=0,
        )

    async def complete(self, model: str, prompt: str) -> str:
        """Generate a completion for ``prompt`` using ``model``.

        Raises:
            LLMRateLimitError / LLMServerError / LLMError: normalized from the
                SDK's APIError.
            LLMResponseError: if the response carries no content.
        """
        try:
            completion = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
        except groq.APIError as exc:
            raise _map_error(exc) from exc

        content = completion.choices[0].message.content
        if not content:
            raise LLMResponseError("empty response from groq", provider="groq")
        return content
