# Patient Journey Simulator

A multi-agent clinical simulation where medical students practise **history-taking**
by interviewing an AI-played patient — then receive structured, examiner-style
feedback from an LLM judge.

The student is dropped at the bedside with only a door-stem ("John Doe, 58, presents
with chest pain") and must *elicit* the rest: the history, the risk factors, the
things the patient would rather not mention. At the end they get a score and a
breakdown of what they covered and what they missed.

> Built as a portfolio project to practise production AI-engineering patterns. The
> interesting parts are the **design decisions**, documented as ADRs in
> [`docs/decisions.md`](docs/decisions.md) and explained in
> [`docs/architecture.md`](docs/architecture.md).

---

## What it demonstrates

- **Multi-agent orchestration** — three distinct characters (patient, nurse, family
  member) each with their own knowledge slice and persona, plus a router that decides
  who answers.
- **RAG scenario generation** — a fresh, schema-valid patient is *synthesised* from a
  corpus of clinical cases (retrieve → generate → validate-and-repair), not hand-written.
- **A patient state graph** — clinical facts as nodes, associations as edges; reveals
  are tracked as the student uncovers them.
- **Episodic memory & trust** — each agent sees only a per-character context window;
  the patient guards sensitive facts until the student earns rapport.
- **LLM-as-judge evaluation** — a *separate, larger* model on a different provider
  (Llama-70B) grades the **process** of asking, not the patient's answers — so the
  patient agent never grades itself; code computes the weighted score deterministically.
- **A resilient, provider-agnostic LLM layer** — every agent's provider+model is one
  line of config (swap without touching agent code), with automatic **cross-provider
  failover** (Gemini→Groq) on `429`/`5xx`; conversation turns are **event-sourced**, so
  a failed call persists nothing and is safe to retry.

---

## Architecture

The system is built as **layers** (one responsibility each). The frontend talks to
the backend over HTTP only — it never imports `src/`.

```
frontend/ (Streamlit)
    │  HTTP
    ▼
src/api/ ............ thin FastAPI routes (no business logic)
    ▼
src/conversation/ ... orchestrator — the per-turn loop
    │
    ├── src/agents/ ...... patient · nurse · family · router  (call the LLM layer)
    ├── src/memory/ ...... builds each agent's context window
    ├── src/state/ ....... NetworkX patient graph (facts + reveals)
    ├── src/rag/ ......... corpus → embed → retrieve → generate a scenario
    ├── src/evaluation/ .. rubric → LLM judge → weighted score → report
    ├── src/db/ .......... SQLAlchemy / SQLite (sessions, turns, evaluations)
    └── src/llm/ ......... provider-agnostic complete(); Gemini + Groq adapters
```

### Data flow

**Start a session** — generate the patient:

```
category → retrieve top-k corpus cases → generator LLM → validate against schema
        → (repair on failure) → persist the Scenario
```

**Each turn** — answer the student:

```
student message → rebuild graph from stored turns → router picks the agent
              → memory builds that agent's context → agent LLM → mark reveals
              → nudge trust → persist the turn
```

**End the session** — grade the interview:

```
scenario nodes → rubric (critical/relevant topics) → judge LLM classifies each
            (asked / not_asked / not_applicable) → code computes weighted score
            → render report → persist the evaluation
```

The conversation is **event-sourced**: the stored turns are the source of truth and
the patient graph is rebuilt from them each turn, so a failed turn is retry-safe and
no end-of-session snapshot is needed.

---

## Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| Backend | FastAPI + Uvicorn (async) |
| Frontend | Streamlit |
| LLM providers | Gemini (patient/nurse/family/router/generator), Groq (judge) |
| State graph | NetworkX (in-memory) |
| RAG store | ChromaDB + local ONNX `all-MiniLM-L6-v2` embeddings (free, offline) |
| Persistence | SQLite via async SQLAlchemy |
| Logging | structlog |
| Validation | Pydantic v2 |
| Tooling | `uv`, `pytest`, `ruff` |

No external services to stand up — SQLite is a local file and ChromaDB persists to
`chroma_data/`.

---

## Setup

**Prerequisites:** Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and API keys for
[Google Gemini](https://aistudio.google.com/apikey) and [Groq](https://console.groq.com/keys)
(both have free tiers).

```bash
# 1. Install dependencies (creates .venv from uv.lock)
uv sync

# 2. Provide your API keys
cp .env.example .env
#   then edit .env and set:
#     GEMINI_API_KEY=...
#     GROQ_API_KEY=...
```

`.env` is gitignored — keys never get committed.

> First run only: the embedding model (~80 MB ONNX MiniLM) downloads once to
> `~/.cache/chroma`, then runs offline.

---

## Running

Two processes — backend, then frontend. Run them via `uv run` (a bare `uvicorn` /
`streamlit` resolves to the system Python, which lacks these deps).

```bash
# Terminal 1 — backend (http://localhost:8000, docs at /docs)
uv run uvicorn src.api.main:app --reload --port 8000

# Terminal 2 — frontend (http://localhost:8501)
uv run streamlit run frontend/app.py
```

Then in the browser:

1. Pick a presentation type and start a session — a patient is generated for you.
2. Interview them. Use the **Talking to** dropdown to address the patient, the nurse,
   or the family member.
3. Click **End interview & get feedback** for your score, what you covered, what you
   missed, and the examiner's notes.

---

## Testing

```bash
uv run pytest tests/ -v          # full suite (166 tests)
uv run pytest tests/unit/ -v     # unit only
uv run pytest tests/integration/ -v
```

Tests make **no real LLM calls** — every provider is injected/faked, so the suite is
fast, deterministic, and costs no quota.

The live network paths are exercised only by four hand-run smoke scripts (each makes
real API calls, so they cost free-tier quota and are excluded from the suite):

```bash
PYTHONPATH=. uv run python scripts/smoke_generator.py        # RAG → generate a scenario
PYTHONPATH=. uv run python scripts/smoke_rag_specialties.py  # RAG across all 5 specialties
PYTHONPATH=. uv run python scripts/smoke_conversation.py     # full conversation loop
PYTHONPATH=. uv run python scripts/smoke_evaluation.py       # the live judge
```

---

## Configuration

Every agent's provider and model live in **one place** — the `AGENT_CONFIG` dict in
[`src/core/config.py`](src/core/config.py):

```python
# Primary is Gemini; each agent falls back ACROSS providers to Groq/Llama.
GROQ_LLAMA = AgentLLMConfig(provider="groq", model="llama-3.3-70b-versatile")

AGENT_CONFIG = {
    "patient":            AgentLLMConfig("gemini", "gemini-2.5-flash-lite", fallback=GROQ_LLAMA),
    "nurse":              AgentLLMConfig("gemini", "gemini-2.5-flash-lite", fallback=GROQ_LLAMA),
    "family":             AgentLLMConfig("gemini", "gemini-2.5-flash-lite", fallback=GROQ_LLAMA),
    "router":             AgentLLMConfig("gemini", "gemini-2.5-flash-lite", fallback=GROQ_LLAMA),
    "scenario_generator": AgentLLMConfig("gemini", "gemini-3.1-flash-lite", fallback=GROQ_LLAMA),
    "judge":              GROQ_LLAMA,   # no fallback — a degraded judge must fail loud
}
```

(Constructor args are keyword in the source; shortened here for width — see
[`src/core/config.py`](src/core/config.py).) To swap a model, change one line — agent
code stays untouched. The fallback is **cross-provider**: on `429` the LLM layer backs
off exponentially (1/2/4/8s) and, once that's exhausted (or immediately on a `5xx`),
fails over from Gemini to Groq. The **judge has no fallback** and fails loudly, so a
degraded grade can never silently mislead.

---

## Project structure

```
src/
  core/         config (AGENT_CONFIG), structlog logging, exception hierarchy
  llm/          provider-agnostic complete(), retry/backoff, Gemini + Groq adapters
  state/        PatientStateGraph (NetworkX), builder, serializer
  rag/          corpus, embedder, retriever (ChromaDB), scenario generator
  agents/       patient, nurse, family, router
  memory/       per-agent context builder, manager (threading/window/trust)
  conversation/ orchestrator (start_session, run_turn)
  evaluation/   rubric, judge, report, evaluator
  db/           SQLAlchemy models, CRUD, session management
  api/          FastAPI app, routes, dependency providers, schemas
frontend/       Streamlit UI (HTTP only)
scenarios/      scenario schema + an authored fixture (chest_pain.json)
scripts/        live smoke tests (run by hand)
tests/          unit + integration (no real LLM calls)
docs/           project spec, architecture, decisions (ADRs), status, changelog
```

---

## Scope & roadmap

An intentionally scoped MVP: each cut below was a deliberate decision — recorded as an
ADR in [`docs/decisions.md`](docs/decisions.md) — made to prove the pipeline end to
end, not to ship every edge.

- **Generation variety** — the corpus holds only a few cases per specialty, so
  generated patients within a category resemble one another. Expanding and
  parameterising the corpus is the recorded next lever.
- **Conversation summarisation** — the episodic-memory headline (per-character context
  windows + trust-gated disclosure) is built; what's stubbed is a long-history
  *summariser*, which the structured stores (graph reveals + persisted trust) make
  unnecessary at the MVP's conversation lengths. It's the next memory step if sessions
  grow long.
- **Session history** — ending an interview locks the session (further turns are
  rejected, ADR-033) and produces the evaluation; listing and resuming past sessions
  is the next step.

---

## Documentation

- [`docs/project_spec.md`](docs/project_spec.md) — the source-of-truth spec
- [`docs/architecture.md`](docs/architecture.md) — layer-by-layer architecture
- [`docs/decisions.md`](docs/decisions.md) — every ADR (the *why* behind the design)
- [`docs/project_status.md`](docs/project_status.md) — what's built, what's next
- [`docs/changelog.md`](docs/changelog.md) — milestone history
