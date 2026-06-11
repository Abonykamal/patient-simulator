"""Custom exception classes.

The LLM errors are *normalized*: each provider adapter translates its SDK's
own exception types into these, so the retry and fallback logic in
``src/llm/`` can reason about "rate limited" vs "server error" without knowing
which provider raised it.
"""


class LLMError(Exception):
    """Base class for all LLM-related failures.

    Args:
        message: Human-readable description.
        status_code: Originating HTTP status, if known.
        provider: Provider name that produced the error, if known.
    """

    def __init__(
        self,
        message: str = "",
        *,
        status_code: int | None = None,
        provider: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider


class LLMRateLimitError(LLMError):
    """HTTP 429 — provider rate limit hit. Retryable with backoff."""


class LLMServerError(LLMError):
    """HTTP 5xx — provider-side failure. Not worth retrying the same provider."""


class LLMResponseError(LLMError):
    """The call succeeded but the response was empty or malformed."""
