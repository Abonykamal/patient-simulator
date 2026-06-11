"""Tests for src.llm.retry — exponential backoff on rate-limit errors.

``sleep`` is injected so the backoff schedule is asserted without real waits.
"""

import pytest

from src.core.exceptions import LLMRateLimitError, LLMServerError
from src.llm.retry import with_backoff


async def test_returns_result_without_sleeping_on_success():
    delays: list[float] = []

    async def sleep(d):
        delays.append(d)

    async def func():
        return "ok"

    assert await with_backoff(func, sleep=sleep) == "ok"
    assert delays == []


async def test_retries_rate_limit_on_1_2_4_8_then_raises():
    delays: list[float] = []

    async def sleep(d):
        delays.append(d)

    async def func():
        raise LLMRateLimitError("429")

    with pytest.raises(LLMRateLimitError):
        await with_backoff(func, sleep=sleep)
    assert delays == [1, 2, 4, 8]  # four backoff waits, then give up


async def test_succeeds_after_transient_rate_limits():
    delays: list[float] = []

    async def sleep(d):
        delays.append(d)

    calls = {"n": 0}

    async def func():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise LLMRateLimitError("429")
        return "recovered"

    assert await with_backoff(func, sleep=sleep) == "recovered"
    assert delays == [1, 2]  # only waited for the two failures
    assert calls["n"] == 3


async def test_does_not_retry_server_errors():
    # 5xx is not a rate limit; backoff must not swallow or retry it.
    delays: list[float] = []

    async def sleep(d):
        delays.append(d)

    async def func():
        raise LLMServerError("503")

    with pytest.raises(LLMServerError):
        await with_backoff(func, sleep=sleep)
    assert delays == []
