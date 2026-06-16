# Changelog

All notable changes to the Patient Journey Simulator are documented here.
Format: Date → What was built → Decisions made

---

## [Unreleased]

### 2026-06-16 — Phase 5: Memory & Context complete (124 unit tests total, +20)
- `src/memory/context_builder.py` — pure per-agent context renderer: slice *policy* (agent→categories, ADR-024/028) over the new `graph.facts()` *mechanism*, labelled blocks (state slice → patient-only rapport line → recent turns), `you`/`student` labelling, nurse `metadata` (vitals) surfaced; `HistoryTurn` value type so the layer never imports `db.models`
- `src/memory/manager.py` — public API: per-agent thread-filtering (D2), windowing to the last `RECENT_EXCHANGES_N` exchanges (D6), and the `apply_rapport_delta` trust clamp (ADR-027); pure/I-O-free (typed injected inputs, no DB, no LLM)
- `src/memory/summarizer.py` — deferred stub (design D5): structured stores (graph `[revealed]` + persisted `trust_level`) cover the MVP
- `src/state/graph.py` — generic `facts()` accessor + `Fact` type (slice mechanism; `summary()` untouched)
- `src/agents/base.py` — `AgentResponse.rapport_delta` + `_json_fields` hook; `src/agents/patient.py` — persona honours the injected rapport level and emits `rapport_delta` (C2 trust)
- `src/db/` — `ConversationTurn.trust_level` + `addressed_to` columns and `add_turn` params; `src/core/config.py` — `RECENT_EXCHANGES_N`, trust bounds
- ADRs 026–028 added (memory layer/injected context, C2 trust model, slice policy-in-memory)

### 2026-06-14 — Phase 4: Agents complete (104 unit tests total, +14)
- `src/agents/base.py` — `BaseAgent` template-method pipeline (assemble → `complete` → parse/validate/repair) + `AgentResponse` model (`response_text`, `revealed_nodes`, `emotional_state`); LLM injected, validate-and-repair reused from the generator
- `src/agents/patient.py` — `PatientAgent`: approved persona with prompt-enforced disclosure hierarchy + trust rubric, plain language, no diagnosis leakage, defers vitals to staff, memory vagueness, pacing
- `src/agents/nurse.py` — `NurseAgent`: documented-facts-only, no clinical reasoning/diagnosis, precise values, defers personal history to the patient
- `src/agents/family.py` — `FamilyAgent`: first-person collateral history, observation-not-inference, no invented family history, slice excludes hidden nodes
- All personas refuse false premises in leading questions (clinical-skills validity guard)
- `src/agents/router.py` — `Router`: resolve-only, explicit addressing wins, unaddressed defaults to patient, one-word LLM classifier only on `AUTO` (zero LLM cost on the common path), defensive parse
- `src/core/config.py` — added `router` to `AGENT_CONFIG` (Gemini `gemini-2.5-flash-lite`)
- ADRs 023–025 added (agent base/template-method + injected context, per-agent knowledge slicing, router implementation)
- `docs/architecture.md` §7 Agents filled in; testing-strategy count updated

### 2026-06-14 — Phase 3: RAG Pipeline complete (90 unit tests total, +16)
- `src/rag/corpus/` — 15 synthetic clinical cases across 5 presentations (chest pain ×4, dyspnea ×3, abdominal pain ×3, headache ×3, leg swelling ×2); varied underlying cause, age, severity, emotional context; whole-case documents, filename encodes category
- `src/rag/embedder.py` — `Embedder`, the text→vector seam over local ONNX `all-MiniLM-L6-v2` (free, offline, deterministic, 384-dim); model choice owned in one place
- `src/rag/retriever.py` — `Retriever` over ChromaDB: `ingest_corpus` (idempotent, strips provenance header, parses category from filename) and `query` (dense semantic search + category metadata pre-filter); collection injected for ephemeral/persistent split
- `src/rag/generator.py` — `ScenarioGenerator`: retrieve top-3 → synthesise a new patient → validate-and-repair against `scenarios/schema.py`; LLM injected (no real calls in tests); output guaranteed to build via `state/builder.py`
- Tooling: added `chromadb` (brings the ONNX MiniLM; no PyTorch)
- ADRs 020–022 added (local ONNX embedder seam, whole-case semantic+metadata retrieval, synthesise + validate-and-repair generation)
- `docs/architecture.md` §6 RAG filled in; persistence + testing-strategy sections updated

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
