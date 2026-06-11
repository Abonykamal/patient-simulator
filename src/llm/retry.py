"""Exponential backoff for rate-limit errors.

This handles *only* ``LLMRateLimitError`` (HTTP 429): a 429 is transient, so a
brief wait may clear it. Server errors (5xx) deliberately pass straight
through — switching providers is the right response to those, and that
decision lives in ``client.py`` (ADR-012), not here.

``sleep`` is injectable so tests can assert the backoff schedule without
actually waiting.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from src.core.exceptions import LLMRateLimitError

T = TypeVar("T")


async def with_backoff(
    func: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 4,
    base_delay: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> T:
    """Call ``func``, retrying on rate-limit errors with exponential backoff.

    On ``LLMRateLimitError`` the delays double each time — with the defaults,
    1s, 2s, 4s, 8s — for up to ``max_retries`` retries. If the last retry still
    rate-limits, the error is re-raised for the caller (client.py) to handle.

    Args:
        func: A zero-arg async callable performing the request.
        max_retries: Number of retries after the initial attempt.
        base_delay: First backoff delay in seconds; doubles each retry.
        sleep: Async sleep function (injected in tests).

    Returns:
        Whatever ``func`` returns on its first successful call.

    Raises:
        LLMRateLimitError: If every attempt is rate-limited.
    """
    # Resolve at call time (not as a default arg) so that patching
    # asyncio.sleep in tests is actually observed here.
    sleep = sleep if sleep is not None else asyncio.sleep
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except LLMRateLimitError:
            if attempt == max_retries:
                raise
            await sleep(base_delay * (2**attempt))
    raise AssertionError("unreachable")  # loop either returns or raises
