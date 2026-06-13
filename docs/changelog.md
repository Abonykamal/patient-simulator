# Changelog

All notable changes to the Patient Journey Simulator are documented here.
Format: Date → What was built → Decisions made

---

## [Unreleased]

### 2026-06-13 — Phase 2: Patient State Graph complete (74 unit tests total, +27)
- `scenarios/schema.py` — scenario validation contract: strict core node fields + open `metadata` bag, `relation` as str-or-list, unique-id and dangling-edge checks, `load_scenario`
- `scenarios/chest_pain.json` — first authored patient: 16 nodes across all categories, hidden cocaine-use precipitant, objective vitals carried in metadata
- `src/state/graph.py` — `PatientStateGraph` over an undirected NetworkX graph: `mark_revealed` (idempotent, hallucination-safe), `is_revealed`, `neighbors`, category-grouped `summary`
- `src/state/builder.py` — validated `Scenario` → live graph, copying core fields + metadata onto nodes
- `src/state/serializer.py` — node-link `serialize`/`deserialize`: round-trip-lossless and warning-free for the `state_snapshot_json` snapshot
- Tooling: added `networkx>=3.0`
- ADRs 017–019 added (node schema hybrid, edges-as-associations, node-link serialization)
- `docs/architecture.md` created (system overview, component/data-flow architecture; unbuilt layers stubbed)

### 2026-06-12 — Phase 1: Core Infrastructure complete (47 unit tests)
- `src/core/config.py` — typed `AgentLLMConfig` (provider/model/fallback), pydantic-settings, cached `get_settings()`
- `src/core/logging.py` — structlog: env-switched JSON/console rendering, contextvars propagation, `get_logger(component)`
- `src/core/exceptions.py` — normalized LLM error hierarchy (rate-limit / server / response)
- `src/db/` — async SQLAlchemy models (sessions/turns/evaluations), `get_db` request-scoped dependency, CRUD
- `src/llm/` — provider-agnostic `complete()`, exponential backoff, Gemini + Groq adapters with error normalization
- Tooling: `uv` project, `pytest`/`pytest-asyncio`, `ruff`; tests run against in-memory SQLite and mocked providers (no real API calls)
- ADRs 014–016 added (DB session lifecycle, JSON columns, create_all-vs-Alembic)
- Spec updated for the four locked decisions (explicit routing, structured agent output, process-based rubric, fallback contract)

### Planning complete (pre-build)
- Architecture finalized: FastAPI backend + Streamlit frontend
- Tech stack decided: SQLite + SQLAlchemy, ChromaDB, NetworkX, structlog
- LLM strategy: Gemini 2.5 Flash-Lite (primary), Groq Llama 3.3 70B (fallback + judge)
- Per-agent LLM config pattern decided
- Provider abstraction layer pattern decided
- Layer-based file structure decided (AI system components as layers)
- RAG strategy: synthetic corpus first, real cases added post-MVP
- project_spec.md, CLAUDE.md, prompts, and status tracker created

---
*Entries will be added here as the project is built.*
