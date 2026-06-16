"""Tests for src.core.config — settings loading and per-agent LLM configuration.

Imports happen inside each test so a missing module reports as a test
failure rather than killing collection for the whole suite.
"""

import pytest
from pydantic import ValidationError


class TestAgentLLMConfig:
    def test_rejects_unknown_provider(self):
        from src.core.config import AgentLLMConfig

        with pytest.raises(ValidationError):
            AgentLLMConfig(provider="openai", model="gpt-4o")

    def test_fallback_defaults_to_none(self):
        from src.core.config import AgentLLMConfig

        cfg = AgentLLMConfig(provider="gemini", model="gemini-2.5-flash-lite")
        assert cfg.fallback is None

    def test_is_immutable(self):
        from src.core.config import AgentLLMConfig

        cfg = AgentLLMConfig(provider="gemini", model="gemini-2.5-flash-lite")
        with pytest.raises(ValidationError):
            cfg.model = "something-else"


class TestAgentConfigRegistry:
    def test_contains_exactly_the_expected_agents(self):
        from src.core.config import AGENT_CONFIG

        assert set(AGENT_CONFIG) == {
            "patient",
            "nurse",
            "family",
            "router",
            "judge",
            "scenario_generator",
        }

    def test_every_entry_is_typed(self):
        from src.core.config import AGENT_CONFIG, AgentLLMConfig

        assert all(isinstance(c, AgentLLMConfig) for c in AGENT_CONFIG.values())

    def test_persona_agents_fall_back_to_groq(self):
        from src.core.config import AGENT_CONFIG

        for name in ("patient", "nurse", "family"):
            fallback = AGENT_CONFIG[name].fallback
            assert fallback is not None, f"{name} must have a fallback"
            assert fallback.provider == "groq"

    def test_judge_has_no_fallback(self):
        # A silently degraded judge produces misleading scores — fail loudly.
        from src.core.config import AGENT_CONFIG

        assert AGENT_CONFIG["judge"].fallback is None


class TestSettings:
    def test_missing_api_keys_fail_at_startup(self, monkeypatch):
        from src.core.config import Settings

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_loads_keys_from_environment(self, monkeypatch):
        from src.core.config import Settings

        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
        monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
        settings = Settings(_env_file=None)
        assert settings.gemini_api_key == "test-gemini-key"
        assert settings.groq_api_key == "test-groq-key"

    def test_sensible_defaults_for_non_secrets(self, monkeypatch):
        from src.core.config import Settings

        monkeypatch.setenv("GEMINI_API_KEY", "k")
        monkeypatch.setenv("GROQ_API_KEY", "k")
        settings = Settings(_env_file=None)
        assert settings.database_url.startswith("sqlite")
        assert settings.log_level == "INFO"

    def test_log_json_defaults_true(self, monkeypatch):
        # JSON is the source-of-truth format; console output is an opt-in.
        from src.core.config import Settings

        monkeypatch.setenv("GEMINI_API_KEY", "k")
        monkeypatch.setenv("GROQ_API_KEY", "k")
        assert Settings(_env_file=None).log_json is True

    def test_get_settings_returns_cached_singleton(self, monkeypatch):
        from src.core.config import get_settings

        monkeypatch.setenv("GEMINI_API_KEY", "k")
        monkeypatch.setenv("GROQ_API_KEY", "k")
        get_settings.cache_clear()
        try:
            assert get_settings() is get_settings()
        finally:
            get_settings.cache_clear()


class TestMemoryTunables:
    def test_memory_constants_have_expected_values(self):
        from src.core.config import (
            RECENT_EXCHANGES_N,
            TRUST_BASELINE,
            TRUST_MAX,
            TRUST_MIN,
        )

        assert RECENT_EXCHANGES_N == 6
        assert TRUST_MIN == 0
        assert TRUST_BASELINE == 1
        assert TRUST_MAX == 3
