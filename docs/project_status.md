# Project Status

## Current State
**Phase:** Pre-build (planning complete, setup not started)
**Last updated:** [fill in when you start]

---

## Milestones

### Phase 0: Setup
- [ ] GitHub repo created
- [ ] Linux environment confirmed
- [ ] `.env` file created from `.env.example`
- [ ] Docker Compose running
- [ ] Dependencies installed
- [ ] CLAUDE.md and project_spec.md in repo root

### Phase 1: Core Infrastructure (Day 1)
- [ ] `src/core/config.py` — settings, AGENT_CONFIG, env vars
- [ ] `src/core/logging.py` — structlog setup
- [ ] `src/db/models.py` — SQLAlchemy models
- [ ] `src/db/session.py` — DB session management
- [ ] `src/db/crud.py` — basic CRUD operations
- [ ] `src/llm/client.py` — LLM abstraction layer
- [ ] `src/llm/gemini.py` — Gemini provider
- [ ] `src/llm/groq.py` — Groq provider
- [ ] `src/llm/retry.py` — exponential backoff

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
Start with Phase 0 setup, then Phase 1 core infrastructure.
Use Prompt #1 (Initial Session Prompt) from `docs/claude_code_prompts.md`.
