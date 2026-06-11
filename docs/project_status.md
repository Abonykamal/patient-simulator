# Project Status

## Current State
**Phase:** Phase 1 (Core Infrastructure) complete — 47 unit tests passing
**Last updated:** 12-June-2026

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
- [ ] `scenarios/schema.py` — Pydantic scenario schema
- [ ] `scenarios/chest_pain.json` — first scenario file
- [ ] `src/state/graph.py` — NetworkX graph implementation
- [ ] `src/state/builder.py` — builds graph from patient JSON
- [ ] `src/state/serializer.py` — graph ↔ JSON serialization

### Phase 3: RAG Pipeline (Day 2)
- [ ] `src/rag/corpus/` — synthetic clinical cases written
- [ ] `src/rag/embedder.py` — sentence-transformer embedding
- [ ] `src/rag/retriever.py` — ChromaDB retrieval
- [ ] `src/rag/generator.py` — scenario generation from retrieved cases

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
Phase 1 done. Begin Phase 2: Patient State Graph — `scenarios/schema.py` (Pydantic scenario schema), `scenarios/chest_pain.json`, then `src/state/graph.py` → `builder.py` → `serializer.py`.

Note: the LLM providers' live network path is not yet exercised (no credentials/integration test). Only the normalization seams are unit-tested. First real Gemini/Groq call happens when an agent or scenario generator runs.

Decisions locked in (reflected in project_spec.md):
- Router: explicit UI addressing; LLM classification only for ambiguous messages
- Agents always return structured JSON: response_text, revealed_nodes, emotional_state
- Rubric is process-based (asking counts regardless of patient's actual history)
- Per-agent optional fallback in AGENT_CONFIG; 429 → fallback after backoff, 5xx → immediately; judge has no fallback (fail loudly)

