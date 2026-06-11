# Patient Journey Simulator — Project Specification

## Project Overview

A multi-agent AI system that simulates clinical patient encounters for medical students. The student plays a medical student conducting a patient interview. The AI plays three distinct roles: a patient, a family member, and a nurse. At session end, an LLM-as-judge evaluation system assesses the student's clinical reasoning and produces a structured report.

**Primary goals:**
- Demonstrate AI engineering skills: multi-agent orchestration, RAG, context engineering, LLM evaluation
- Build something resume-worthy and defensible in a technical interview
- Learn by building — every component must be explainable

**Target users:** Medical students practicing clinical history-taking and diagnostic reasoning.

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Backend API | FastAPI (Python) | Async-native, auto OpenAPI docs, industry standard for LLM APIs |
| Frontend UI | Streamlit | Rapid UI, calls FastAPI endpoints, replaceable later |
| Patient State | NetworkX | In-memory graph during session, serialized to SQLite at end |
| Relational DB | SQLite + SQLAlchemy | Sessions, turns, evaluations. ORM layer makes Postgres migration a one-line config change |
| Vector DB | ChromaDB | Stores clinical case embeddings for RAG-based scenario generation |
| Primary LLM | Gemini 2.5 Flash-Lite | Free tier: 15 RPM, 1000 RPD. Used for patient/nurse/family agents |
| Fallback LLM | Groq / Llama 3.3 70B | Free tier: 30 RPM, 1000 RPD. Used as judge and primary fallback |
| Embeddings | Sentence-Transformers | Local, free, no API calls needed for embedding the corpus |
| Logging | structlog | Structured JSON logging from day one |
| Containerization | Docker + Docker Compose | Linux (Ubuntu) environment |

---

## Architecture Overview

### System Design

```
┌─────────────────────────────────────────────────────────┐
│                    Streamlit Frontend                    │
│         (calls FastAPI endpoints over HTTP)              │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP
┌─────────────────────▼───────────────────────────────────┐
│                    FastAPI Backend                       │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  Session    │  │ Conversation │  │  Evaluation    │  │
│  │  Router     │  │    Router    │  │   Router       │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘  │
└─────────┼────────────────┼──────────────────┼───────────┘
          │                │                  │
┌─────────▼────────────────▼──────────────────▼───────────┐
│                      Core Engine                         │
│                                                          │
│  ┌──────────────┐    ┌─────────────────────────────────┐ │
│  │  RAG Module  │    │       Agent Orchestrator        │ │
│  │              │    │  ┌──────────┐ ┌───────────────┐ │ │
│  │ ChromaDB     │    │  │ Patient  │ │ Family Member │ │ │
│  │ Embeddings   │    │  │  Agent   │ │    Agent      │ │ │
│  │ Retrieval    │    │  └──────────┘ └───────────────┘ │ │
│  └──────┬───────┘    │  ┌──────────┐                   │ │
│         │            │  │  Nurse   │                   │ │
│         │            │  │  Agent   │                   │ │
│         │            │  └──────────┘                   │ │
│         │            └────────────┬────────────────────┘ │
│         │                         │                      │
│  ┌──────▼─────────────────────────▼────────────────────┐ │
│  │                 Memory Manager                       │ │
│  │    (episodic memory, context construction,          │ │
│  │     patient state graph read/write)                 │ │
│  └──────────────────────────┬───────────────────────────┘ │
│                              │                            │
│  ┌──────────────────────────▼───────────────────────────┐ │
│  │                  State Manager                       │ │
│  │    NetworkX graph: symptoms, history, hidden info,  │ │
│  │    emotional arc, relationships between nodes       │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌──────────────────────────────────────────────────────┐ │
│  │              LLM Abstraction Layer                   │ │
│  │   Per-agent config → routes to Gemini or Groq       │ │
│  │   Handles retry with exponential backoff on 429s    │ │
│  └──────────────────────────────────────────────────────┘ │
└─────────────────────────────┬────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
     ┌────────▼────────┐           ┌──────────▼──────────┐
     │   SQLite DB     │           │     ChromaDB        │
     │ (sessions,      │           │ (clinical case      │
     │  turns,         │           │  embeddings for     │
     │  evaluations,   │           │  RAG retrieval)     │
     │  state snapshots│           │                     │
     └─────────────────┘           └─────────────────────┘
```

### Data Flow: Session Start
```
1. Student selects scenario type (e.g. "chest pain")
2. RAG module embeds query → retrieves similar cases from ChromaDB
3. Retrieved cases + scenario template → LLM generates dynamic patient JSON
4. State manager builds NetworkX graph from patient JSON
5. New session row created in SQLite
6. Streamlit renders the scenario intro
```

### Data Flow: Conversation Turn
```
1. Student submits message, optionally addressed to a specific agent
   (UI dropdown or "Nurse: ..." prefix)
2. Agent router resolves the speaker: an explicit address always wins;
   LLM-based classification is used only when the target is ambiguous
3. Memory manager constructs context:
   - Last N turns from SQLite
   - Current state graph summary
   - Agent persona and constraints
   - What has/hasn't been revealed
4. LLM call via abstraction layer
5. Agent returns structured JSON (all agents, always):
   { "response_text": "...", "revealed_nodes": [...], "emotional_state": "..." }
6. response_text returned to student
7. State graph updated: every node in revealed_nodes marked revealed
8. Turn saved to SQLite
```

### Data Flow: Session End
```
1. Student triggers end-of-session
2. Full transcript retrieved from SQLite
3. Scenario rubric retrieved from scenario file
4. Judge LLM (Groq/Llama 70B) receives transcript + rubric
5. Judge produces structured evaluation JSON
6. Evaluation saved to SQLite
7. Streamlit renders assessment report
```

---

## Database Schema

### SQLite Tables

```sql
-- One row per simulation session
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,               -- UUID
    scenario_id TEXT NOT NULL,
    scenario_name TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    status TEXT DEFAULT 'active',      -- active | completed | abandoned
    patient_profile_json TEXT,         -- full generated patient as JSON
    state_snapshot_json TEXT           -- final state graph snapshot
);

-- One row per message exchanged
CREATE TABLE conversation_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    turn_number INTEGER NOT NULL,
    speaker TEXT NOT NULL,             -- student | patient | nurse | family
    content TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    revealed_nodes_json TEXT           -- nodes revealed by this turn (if any)
);

-- One row per completed session evaluation
CREATE TABLE evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    created_at TIMESTAMP NOT NULL,
    rubric_items_json TEXT NOT NULL,   -- full rubric with covered/missed flags
    covered_items_json TEXT NOT NULL,
    missed_items_json TEXT NOT NULL,
    clinical_reasoning_notes TEXT,
    overall_score REAL,
    full_report_text TEXT
);
```

### ChromaDB Collections

```
collection: clinical_cases
  - documents: raw clinical case text
  - embeddings: sentence-transformer vectors
  - metadata: { case_id, presentation_type, specialty, source }
```

---

## Project File Structure

```
patient-simulator/
│
├── CLAUDE.md                    # Claude Code instructions (lean, <150 lines)
├── README.md                    # Project overview and setup guide
├── docker-compose.yml           # Services: backend, frontend
├── .env.example                 # Environment variable template
├── pyproject.toml               # Dependencies (use uv or poetry)
│
├── docs/
│   ├── project_spec.md          # This file
│   ├── architecture.md          # Detailed system design (populated as built)
│   ├── changelog.md             # Version history
│   └── project_status.md        # Milestones and current progress
│
├── scenarios/
│   ├── schema.py                # Pydantic schema for scenario files
│   ├── chest_pain.json          # Scenario 1
│   └── dyspnea.json             # Scenario 2 (stretch goal)
│
├── src/
│   ├── core/
│   │   ├── config.py            # Settings, env vars, agent config
│   │   ├── logging.py           # structlog setup
│   │   └── exceptions.py        # Custom exception classes
│   │
│   ├── llm/
│   │   ├── client.py            # LLM abstraction layer
│   │   ├── gemini.py            # Gemini provider
│   │   ├── groq.py              # Groq provider
│   │   └── retry.py             # Exponential backoff on 429s
│   │
│   ├── rag/
│   │   ├── embedder.py          # Sentence-transformer embedding
│   │   ├── retriever.py         # ChromaDB retrieval
│   │   ├── generator.py         # Scenario generation from retrieved cases
│   │   └── corpus/              # Synthetic clinical case text files
│   │
│   ├── state/
│   │   ├── graph.py             # NetworkX patient state graph
│   │   ├── builder.py           # Builds graph from LLM-generated patient JSON
│   │   └── serializer.py        # Graph ↔ JSON for SQLite storage
│   │
│   ├── agents/
│   │   ├── base.py              # Base agent class
│   │   ├── patient.py           # Patient agent
│   │   ├── nurse.py             # Nurse agent
│   │   ├── family.py            # Family member agent
│   │   └── router.py            # Decides which agent responds
│   │
│   ├── memory/
│   │   ├── manager.py           # Episodic memory manager
│   │   ├── context_builder.py   # Constructs context window for each LLM call
│   │   └── summarizer.py        # Summarizes older turns to save context space
│   │
│   ├── evaluation/
│   │   ├── judge.py             # LLM-as-judge system
│   │   ├── rubric.py            # Rubric loading and management
│   │   └── report.py            # Formats evaluation output
│   │
│   ├── db/
│   │   ├── models.py            # SQLAlchemy models
│   │   ├── session.py           # DB session management
│   │   └── crud.py              # Create/read/update operations
│   │
│   └── api/
│       ├── main.py              # FastAPI app entry point
│       ├── routes/
│       │   ├── sessions.py      # POST /sessions, GET /sessions/{id}
│       │   ├── conversation.py  # POST /sessions/{id}/turns
│       │   └── evaluation.py    # POST /sessions/{id}/evaluate
│       └── schemas.py           # Pydantic request/response models
│
├── tests/
│   ├── unit/                    # No-network tests; LLM layer always mocked
│   └── integration/             # Cross-component tests
│
└── frontend/
    └── app.py                   # Streamlit app (calls FastAPI)
```

---

## API Design

### Endpoints

```
POST   /sessions                        Create new session, triggers RAG scenario generation
GET    /sessions/{session_id}           Get session state and metadata
POST   /sessions/{session_id}/turns     Submit student message, get agent response
POST   /sessions/{session_id}/evaluate  End session, trigger judge evaluation
GET    /sessions/{session_id}/report    Get evaluation report
```

### Key Request/Response Shapes

```python
# POST /sessions
Request:  { "scenario_type": "chest_pain" }
Response: { "session_id": "uuid", "scenario_intro": "...", "patient_name": "..." }

# POST /sessions/{id}/turns
# addressed_to is optional; if omitted or ambiguous, the router classifies
Request:  { "content": "Do you have any chest pain?", "addressed_to": "patient" }
Response: { "speaker": "patient", "content": "...", "emotional_state": "anxious" }

# GET /sessions/{id}/report
Response: {
    "covered": ["chest pain onset", "radiation", "associated symptoms"],
    "missed": ["smoking history", "family cardiac history"],
    "score": 0.72,
    "clinical_reasoning_notes": "...",
    "full_report": "..."
}
```

---

## LLM Configuration

```python
# src/core/config.py
class AgentLLMConfig(BaseModel):
    provider: Literal["gemini", "groq"]       # typo in provider = crash at startup
    model: str
    fallback: "AgentLLMConfig | None" = None  # consumed by src/llm/client.py

GROQ_LLAMA = AgentLLMConfig(provider="groq", model="llama-3.3-70b-versatile")

AGENT_CONFIG: dict[str, AgentLLMConfig] = {
    "patient":            AgentLLMConfig(provider="gemini", model="gemini-2.5-flash-lite", fallback=GROQ_LLAMA),
    "nurse":              AgentLLMConfig(provider="gemini", model="gemini-2.5-flash-lite", fallback=GROQ_LLAMA),
    "family":             AgentLLMConfig(provider="gemini", model="gemini-2.5-flash-lite", fallback=GROQ_LLAMA),
    "judge":              GROQ_LLAMA,  # no fallback: a degraded judge silently misleads — fail loudly instead
    "scenario_generator": AgentLLMConfig(provider="gemini", model="gemini-3.1-flash-lite", fallback=GROQ_LLAMA),
}
```

Changing one agent's model = changing one line in this dict. All agent code calls `llm_client.complete(agent_name, prompt)` and never knows which provider it's using.

**Fallback contract (implemented in `src/llm/client.py`):**
- On HTTP 429: retry the primary with exponential backoff (1s, 2s, 4s, 8s); switch to `fallback` only after backoff exhausts
- On HTTP 5xx: switch to `fallback` immediately
- `fallback is None`: re-raise after backoff — the caller decides how to degrade

---

## Logging

Structured JSON logging via `structlog`. Every log entry includes:
- `timestamp`
- `level`
- `component` (which module)
- `session_id` (when applicable)
- `event` (what happened)
- Additional context fields per event

Example:
```json
{"timestamp": "2026-01-01T10:00:00Z", "level": "info", "component": "agents.patient", "session_id": "abc123", "event": "agent_response", "tokens_used": 342, "revealed_nodes": ["sweating"]}
```

---

## Key Engineering Decisions (with rationale)

| Decision | Choice | Why |
|---|---|---|
| File structure | Layer-based (AI components as layers) | AI system components are the natural grouping for this codebase |
| State representation | NetworkX graph | Encodes relationships between symptoms/history; behavior emerges from traversal, not hardcoded logic |
| RAG corpus | Synthetic first, real cases added later | Build and validate the pipeline before doing data work |
| LLM abstraction | Per-agent config, provider-agnostic client | Swap any agent's model with one config change |
| Frontend | Streamlit calling FastAPI | Learn FastAPI (the real skill); Streamlit for speed |
| Database | SQLite + SQLAlchemy | Full persistence, ORM abstracts DB, trivial Postgres migration later |
| Vectors | ChromaDB | Library-mode (no server), sufficient for this scale |
| Logging | structlog (JSON) | Queryable logs from day one; good engineering habit |
| Agent routing | Explicit UI addressing; LLM classification only for ambiguous messages | Saves one LLM call per turn on a 15 RPM budget; deterministic where possible |
| Revealed-node tracking | Structured agent output: `{response_text, revealed_nodes, emotional_state}` | Agent declares reveals in-band; far more reliable than post-hoc text matching |
| Rubric semantics | Process-based: asking counts, regardless of the patient's actual history | Decouples static rubrics from dynamically generated patients |
| Provider fallback | Optional `fallback` field per agent in AGENT_CONFIG | 429 → after backoff exhausts; 5xx → immediately; provider outage doesn't kill a session |

---

## Future Extensions (Post-MVP)

- Conversation turn embeddings in ChromaDB for semantic search across sessions ("find sessions where students missed cardiac history")
- Real clinical cases added to RAG corpus (USMLE case banks, Open Clinical, MedQA dataset)
- Redis session caching (revisit for production RAG project)
- Replace Streamlit with React frontend
- Multi-speciality scenarios (neurology, pediatrics)
- Student performance analytics dashboard

---

## What This Project Demonstrates (for interviews)

1. **Multi-agent orchestration** — three agents with distinct personas, memory access levels, and an explicit router
2. **RAG pipeline** — embedding, retrieval, prompt construction from retrieved context
3. **Context engineering** — episodic memory, structured context window construction, state-aware prompting
4. **LLM evaluation** — LLM-as-judge with rubric, structured output, measurable clinical reasoning assessment
5. **Provider abstraction** — model-agnostic design, per-agent configuration
6. **Production patterns** — structured logging, SQLAlchemy ORM, Docker, async FastAPI
