# Patient Journey Simulator

Multi-agent clinical simulation system. Medical students interview AI-played patients.
Full spec: `docs/project_spec.md`. Architecture details: `docs/architecture.md`.

---

## Critical Commands

```bash
# Setup
docker-compose up -d
uv sync

# Run
uvicorn src.api.main:app --reload --port 8000   # backend
streamlit run frontend/app.py                   # frontend

# Test
pytest tests/ -v
pytest tests/unit/ -v                           # unit only
pytest tests/integration/ -v                    # integration only

# Lint / format
ruff check src/
ruff format src/
```

---

## Architecture (read before writing code)

**Layers:**
- `src/llm/` — LLM abstraction layer. All LLM calls go through `client.py`. Never call Gemini/Groq directly from agents.
- `src/agents/` — Patient, nurse, family agents + router. Agents call `llm_client`, never raw APIs.
- `src/state/` — NetworkX patient state graph. In-memory during session.
- `src/memory/` — Episodic memory manager. Builds context window for each LLM call.
- `src/rag/` — Embedding, retrieval, scenario generation. ChromaDB lives here.
- `src/evaluation/` — LLM-as-judge system. Runs at session end.
- `src/db/` — SQLAlchemy models, CRUD, session management. SQLite only.
- `src/api/` — FastAPI routes. Thin layer — business logic lives in core modules, not routes.
- `frontend/` — Streamlit UI. Calls FastAPI only, no direct imports from `src/`.

**Non-negotiable constraints:**
- LLM provider config lives in `src/core/config.py` AGENT_CONFIG dict — nowhere else.
- Database access only through `src/db/crud.py` — no raw SQL outside db layer.
- All logging via structlog — no print statements.
- Streamlit never imports from `src/` directly — HTTP only.

---

## LLM Configuration

```python
AGENT_CONFIG = {
    "patient":            {"provider": "gemini", "model": "gemini-2.5-flash-lite"},
    "nurse":              {"provider": "gemini", "model": "gemini-2.5-flash-lite"},
    "family":             {"provider": "gemini", "model": "gemini-2.5-flash-lite"},
    "judge":              {"provider": "groq",   "model": "llama-3.3-70b-versatile"},
    "scenario_generator": {"provider": "gemini", "model": "gemini-2.5-flash"},
}
```

To swap a model: change one line in AGENT_CONFIG. Do not touch agent code.
Implement exponential backoff (1s, 2s, 4s, 8s) on 429 errors in `src/llm/retry.py`.

---

## Code Standards

- Python 3.11+
- Type hints on all function signatures
- Pydantic models for all data validation (request/response + internal)
- Async functions for all I/O (LLM calls, DB operations)
- `try/except` on all LLM calls — never let a provider error crash a session
- Docstrings on all public functions: what it does, params, returns

---

## Working Style

I am a student learning AI engineering. For every non-trivial implementation:
1. Explain what you are about to build and why before writing code
2. Note any tradeoffs in the approach chosen
3. Add inline comments explaining *why*, not just *what*
4. After completing a component, summarize: what it does, what calls it, what it calls

Do not fill in sections of `docs/architecture.md` — I will do that after we discuss.
Do not refactor code I haven't reviewed yet.
Ask before making structural changes to the file layout.

---

## Documentation

Update `docs/project_status.md` after each completed component.
Update `docs/changelog.md` after each working milestone.
Do not modify `docs/project_spec.md` — that is the source of truth.

---

## Current Status

See `docs/project_status.md` for what is built and what is next.
