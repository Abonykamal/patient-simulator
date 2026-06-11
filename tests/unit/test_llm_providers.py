"""Tests for the provider adapters' error normalization.

The live network path (calling Gemini/Groq) needs credentials and is covered
by integration tests later. What we unit-test here is the load-bearing logic:
translating each SDK's own exceptions into our normalized hierarchy, since the
client's fallback routing depends entirely on getting that mapping right.
``_map_error`` is module-private but is the deliberate testable seam.
"""

from src.core.exceptions import LLMError, LLMRateLimitError, LLMServerError
from src.llm.gemini import _map_error as gemini_map
from src.llm.groq import _map_error as groq_map


class FakeGeminiError(Exception):
    """Stands in for google.genai.errors.APIError (which exposes .code)."""

    def __init__(self, code, message="boom"):
        super().__init__(message)
        self.code = code
        self.message = message


class FakeGroqError(Exception):
    """Stands in for groq.APIStatusError (which exposes .status_code)."""

    def __init__(self, status_code):
        super().__init__("boom")
        self.status_code = status_code


def test_gemini_maps_429_to_rate_limit():
    assert isinstance(gemini_map(FakeGeminiError(429)), LLMRateLimitError)


def test_gemini_maps_5xx_to_server_error():
    assert isinstance(gemini_map(FakeGeminiError(503)), LLMServerError)


def test_gemini_maps_other_codes_to_generic_error():
    err = gemini_map(FakeGeminiError(404))
    assert isinstance(err, LLMError)
    assert not isinstance(err, (LLMRateLimitError, LLMServerError))


def test_groq_maps_429_to_rate_limit():
    assert isinstance(groq_map(FakeGroqError(429)), LLMRateLimitError)


def test_groq_maps_5xx_to_server_error():
    assert isinstance(groq_map(FakeGroqError(500)), LLMServerError)


def test_groq_maps_other_codes_to_generic_error():
    err = groq_map(FakeGroqError(400))
    assert isinstance(err, LLMError)
    assert not isinstance(err, (LLMRateLimitError, LLMServerError))
