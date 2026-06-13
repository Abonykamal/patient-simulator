# Project Status

## Current State
**Phase:** Phase 3 (RAG Pipeline) complete — 90 unit tests passing
**Last updated:** 14-June-2026

---

## Milestones

### Phase 0: Setup
- [x] GitHub repo created
- [x] Linux environment confirmed
- [x] `.env` file created from `.env.example`
- [ ] Docker Compose running
- [x] Dependencies installed (uv 0.11.20; Phase 1 deps only, heavier deps added per phase)
- [x] CLAUDE.md and project_spec.md in repo root

### Phase 1: Core Infrastructure (Day 1)
- [x] `src/core/config.py` — settings, AGENT_CONFIG, env vars (typed AgentLLMConfig + fallback field, pydantic-settings, cached get_settings; 11 unit tests)
- [x] `src/core/logging.py` — structlog setup (env-switched JSON/console rendering, contextvars propagation for session_id, get_logger(component); 5 unit tests). stdlib bridge deferred to Phase 6.
- [x] `src/db/models.py` — SQLAlchemy models (SimulationSession/ConversationTurn/Evaluation, JSON columns per ADR-015; 4 unit tests)
- [x] `src/db/session.py` — DB session management (lazy async engine, get_db request-scoped dependency commits/rolls back per ADR-014, init_db via create_all per ADR-016; 2 unit tests)
- [x] `src/db/crud.py` — basic CRUD operations (create/get session, add/get turns, end session, save/get evaluation; 7 unit tests)
- [x] `src/core/exceptions.py` — normalized LLM error hierarchy (LLMError + RateLimit/Server/Response; 2 unit tests)
- [x] `src/llm/retry.py` — exponential backoff on 429 only, injectable sleep (1/2/4/8s; 4 unit tests)
- [x] `src/llm/client.py` — LLM abstraction layer (provider-agnostic complete(); ADR-012 fallback: 429→backoff→fallback, 5xx→immediate fallback, no-fallback→raise; 5 unit tests)
- [x] `src/llm/gemini.py` — Gemini provider (google-genai async adapter, _map_error normalization; 3 unit tests on mapping)
- [x] `src/llm/groq.py` — Groq provider (AsyncGroq adapter, SDK retries disabled, _map_error normalization; 3 unit tests on mapping)

### Phase 2: Patient State Graph (Day 1-2)
- [x] `scenarios/schema.py` — Pydantic scenario schema (strict core + open `metadata` bag, unique-id & dangling-edge validation, `load_scenario`; ADR-017; 8 unit tests)
- [x] `scenarios/chest_pain.json` — first scenario file (16 nodes across all categories, hidden cocaine-use precipitant, vitals in metadata; 3 unit tests)
- [x] `src/state/graph.py` — `PatientStateGraph` over undirected NetworkX graph (`mark_revealed`/`is_revealed`/`neighbors`/`summary`; edges = associations not gates, ADR-018; 8 unit tests)
- [x] `src/state/builder.py` — `build_graph(scenario)` copies core + metadata onto nodes (4 unit tests)
- [x] `src/state/serializer.py` — node-link `serialize`/`deserialize`, round-trip-lossless, warning-free (ADR-019; 4 unit tests)

### Phase 3: RAG Pipeline (Day 2)
- [x] `src/rag/corpus/` — 15 synthetic clinical cases across 5 presentations (chest pain ×4, dyspnea ×3, abdominal pain ×3, headache ×3, leg swelling ×2), varied cause/age/severity/emotion; whole-case docs, filename = category (ADR-013/021)
- [x] `src/rag/embedder.py` — `Embedder` over local ONNX `all-MiniLM-L6-v2` (free/offline/deterministic, 384-dim); single text→vector seam (ADR-020; 4 unit tests)
- [x] `src/rag/retriever.py` — `Retriever` over ChromaDB: `ingest_corpus` (idempotent, strips header, parses category) + `query` (dense semantic + category metadata pre-filter); collection injected (ephemeral tests / persistent app) (ADR-021; 5 unit tests)
- [x] `src/rag/generator.py` — `ScenarioGenerator`: retrieve top-3 → synthesise → validate-and-repair against `scenarios/schema.py` (≤`max_repairs`); LLM injected, no real calls in tests; output builds via `state/builder.py` (ADR-022; 7 unit tests)

### Phase 4: Agents (Day 3)
- [ ] `src/agents/base.py` — base agent class
- [ ] `src/agents/patient.py` — patient agent
- [ ] `src/agents/nurse.py` — nurse agent
- [ ] `src/agents/family.py` — family member agent
- [ ] `src/agents/router.py` — agent router

### Phase 5: Memory & Context (Day 3-4)
- [ ] `src/memory/manager.py` — episodic memory manager
- [ ] `src/memory/context_builder.py` — context window construction
- [ ] `src/memory/summarizer.py` — conversation summarization

### Phase 6: Full Conversation Loop (Day 4)
- [ ] `src/api/routes/sessions.py`
- [ ] `src/api/routes/conversation.py`
- [ ] `src/api/main.py`
- [ ] `frontend/app.py` — Streamlit UI
- [ ] End-to-end conversation working

### Phase 7: Evaluation (Day 5-6)
- [ ] `src/evaluation/rubric.py`
- [ ] `src/evaluation/judge.py`
- [ ] `src/evaluation/report.py`
- [ ] `src/api/routes/evaluation.py`

### Phase 8: Polish (Day 7-8)
- [ ] Second scenario file
- [ ] RAG tested with multiple scenario types
- [ ] Edge cases handled
- [ ] README with setup instructions
- [ ] Demo recording

---

## What's Next
Phase 3 done. Begin Phase 4: Agents — `src/agents/base.py`, `src/agents/patient.py`, `src/agents/nurse.py`, `src/agents/family.py`, `src/agents/router.py`. Agents call `llm.client.complete` (never raw SDKs), return structured JSON `{response_text, revealed_nodes, emotional_state}` (ADR-010), and read the `PatientStateGraph` (summary for context, `mark_revealed` after each turn). The patient agent honours each node's `disclosure_difficulty` (ADR-017). The router uses explicit UI addressing with LLM classification only for ambiguous messages (ADR-009).

Note: the LLM providers' live network path is **still not exercised** (no credentials/integration test). Phase 3's generator is unit-tested with an injected fake LLM, so no real Gemini/Groq call has yet happened. The first real provider call occurs when the generator or an agent runs against live credentials — worth a single smoke test early in Phase 4.

Embedding model note: the ONNX `all-MiniLM-L6-v2` (~80 MB) downloads once on first embed to `~/.cache/chroma`, then runs offline. ChromaDB's persistent store lives at `chroma_data/` (gitignored).

Decisions locked in (reflected in project_spec.md / decisions.md):
- RAG embeddings: local ONNX MiniLM behind the `Embedder` seam — free/offline/deterministic, no torch (ADR-020)
- RAG retrieval: whole-case documents (no chunking), dense semantic + category metadata pre-filter, top-3, no hybrid/BM25 (ADR-021)
- Scenario generation: synthesise from top-3, validate-and-repair against the schema, LLM injected (ADR-022)
- State graph: undirected NetworkX, edges = clinical associations not reveal gates; relation as edge attribute (str or list), no MultiGraph (ADR-018)
- Scenario nodes: strict core fields + open `metadata` bag; core logic never branches on metadata (ADR-017)
- Graph serialization: NetworkX node-link format behind the serializer seam (ADR-019)
- Router: explicit UI addressing; LLM classification only for ambiguous messages
- Agents always return structured JSON: response_text, revealed_nodes, emotional_state
- Rubric is process-based (asking counts regardless of patient's actual history)
- Per-agent optional fallback in AGENT_CONFIG; 429 → fallback after backoff, 5xx → immediately; judge has no fallback (fail loudly)

