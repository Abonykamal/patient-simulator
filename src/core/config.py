"""Application settings and per-agent LLM configuration.

This module is the single source of truth for two things:
- which provider/model each agent uses (AGENT_CONFIG)
- environment-driven settings such as API keys (Settings)

No other module may know about providers or read environment variables.
Agents call the LLM client with their agent name; the client resolves
provider, model, and fallback from AGENT_CONFIG.
"""

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentLLMConfig(BaseModel):
    """LLM routing for one agent: primary provider/model plus optional fallback.

    The fallback chain is consumed by src/llm/client.py:
    - HTTP 429: exponential backoff on the primary first (1s, 2s, 4s, 8s),
      switch to ``fallback`` only after backoff exhausts
    - HTTP 5xx: switch to ``fallback`` immediately
    - ``fallback is None``: re-raise so the caller decides how to degrade
    """

    # frozen: config entries are shared module-level objects — nothing may
    # mutate routing at runtime; model swaps happen here, in source, only.
    model_config = ConfigDict(frozen=True)

    provider: Literal["gemini", "groq"]
    model: str
    fallback: "AgentLLMConfig | None" = None


GROQ_LLAMA = AgentLLMConfig(provider="groq", model="llama-3.3-70b-versatile")

AGENT_CONFIG: dict[str, AgentLLMConfig] = {
    "patient": AgentLLMConfig(
        provider="gemini", model="gemini-2.5-flash-lite", fallback=GROQ_LLAMA
    ),
    "nurse": AgentLLMConfig(provider="gemini", model="gemini-2.5-flash-lite", fallback=GROQ_LLAMA),
    "family": AgentLLMConfig(provider="gemini", model="gemini-2.5-flash-lite", fallback=GROQ_LLAMA),
    # No fallback for the judge: a silently degraded judge produces
    # misleading evaluation scores — better to fail loudly and re-run.
    "judge": GROQ_LLAMA,
    "scenario_generator": AgentLLMConfig(
        provider="gemini", model="gemini-3.1-flash-lite", fallback=GROQ_LLAMA
    ),
}


class Settings(BaseSettings):
    """Environment-driven application settings.

    Required fields without defaults (the API keys) make a missing key a
    startup crash with a clear validation error, not a 401 mid-session.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str
    groq_api_key: str
    database_url: str = "sqlite+aiosqlite:///./patient_simulator.db"
    chroma_persist_dir: str = "./chroma_data"
    log_level: str = "INFO"
    # JSON is the source-of-truth log format. Flip to False (LOG_JSON=false)
    # for human-readable console output while developing locally.
    log_json: bool = True


@lru_cache
def get_settings() -> Settings:
    """Return the application-wide ``Settings`` singleton.

    Cached so every caller shares one instance. FastAPI routes should
    depend on this function (``Depends(get_settings)``) so tests can
    swap settings via ``app.dependency_overrides``.

    Returns:
        The validated ``Settings`` instance.
    """
    return Settings()
