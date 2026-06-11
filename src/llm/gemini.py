"""Gemini provider adapter.

Wraps the google-genai async client and translates its ``APIError`` into our
normalized exceptions so ``client.py`` can route retries/fallback without
knowing it is talking to Gemini. The translation lives in ``_map_error``, which
is unit-tested; the live network call is integration-tested with credentials.
"""

from __future__ import annotations

from google import genai
from google.genai import errors as genai_errors

from src.core.config import get_settings
from src.core.exceptions import (
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMServerError,
)


def _map_error(exc: Exception) -> LLMError:
    """Translate a google-genai APIError into a normalized LLM error.

    Reads the HTTP ``code`` the SDK attaches and routes 429 -> rate limit,
    5xx -> server error, anything else -> generic LLM error.
    """
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", str(exc))
    if code == 429:
        return LLMRateLimitError(message, status_code=code, provider="gemini")
    if code is not None and 500 <= code < 600:
        return LLMServerError(message, status_code=code, provider="gemini")
    return LLMError(message, status_code=code, provider="gemini")


class GeminiProvider:
    """Async adapter over the Gemini Developer API."""

    def __init__(self, api_key: str | None = None) -> None:
        self._client = genai.Client(api_key=api_key or get_settings().gemini_api_key)

    async def complete(self, model: str, prompt: str) -> str:
        """Generate a completion for ``prompt`` using ``model``.

        Raises:
            LLMRateLimitError / LLMServerError / LLMError: normalized from the
                SDK's APIError.
            LLMResponseError: if the response carries no text.
        """
        try:
            response = await self._client.aio.models.generate_content(model=model, contents=prompt)
        except genai_errors.APIError as exc:
            raise _map_error(exc) from exc

        text = response.text
        if not text:
            raise LLMResponseError("empty response from gemini", provider="gemini")
        return text
