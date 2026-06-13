# Architecture

Living architecture reference for the Patient Journey Simulator. The source of
truth for *requirements* is `project_spec.md`; the source of truth for *why*
each choice was made is `decisions.md` (ADRs). This document explains *how the
pieces fit together*.

> **Status convention.** Sections describing layers that are built are written
> in full. Layers not yet built are marked **🚧 To be filled in** and will be
> completed as each phase lands — the engineer fills these in after we discuss,
> per the working agreement.

---

## 1. System Overview

A medical student interviews an AI-played patient (plus a nurse and a family
member) to practise clinical history-taking. A session runs roughly:

```
select scenario → RAG generates a patient → interview over many turns → end → evaluation report
```

The system is split into two processes connected only over HTTP, so the UI can
be swapped without touching the backend (ADR-002):

```
┌────────────────────┐         HTTP/JSON          ┌────────────────────────────┐
│  Streamlit frontend │ ───────────────────────▶  │  FastAPI backend           │
│  (thin UI only)     │ ◀───────────────────────  │  (all business logic)      │
└────────────────────┘                            └────────────────────────────┘
                                                          │
                          ┌───────────────────────────────┼───────────────────────────────┐
                          ▼                               ▼                                ▼
                   SQLite (sessions,              ChromaDB (clinical              LLM providers
                   turns, evaluations)            case embeddings)                (Gemini, Groq)
```

**Layering rule (CLAUDE.md):** business logic lives in core modules under
`src/`, never in the API routes or the frontend. The frontend talks HTTP only.

---

## 2. Component Architecture

Layers map to AI-system concerns, not web-app tiers (ADR-001). Each `src/`
subpackage is one layer:

| Layer | Package | Responsibility | Status |
|-------|---------|----------------|--------|
| Core | `src/core/` | Config (`AGENT_CONFIG`, settings), logging, exception hierarchy | ✅ Phase 1 |
| LLM | `src/llm/` | Provider-agnostic `complete()`, backoff, fallback, Gemini/Groq adapters | ✅ Phase 1 |
| DB | `src/db/` | Async SQLAlchemy models, session lifecycle, CRUD | ✅ Phase 1 |
| State | `src/state/` | In-memory NetworkX patient graph: build, query, serialize | ✅ Phase 2 |
| Scenarios | `scenarios/` | Scenario schema + authored patient JSON files | ✅ Phase 2 |
| RAG | `src/rag/` | Embedding, retrieval, scenario generation; ChromaDB | ✅ Phase 3 |
| Agents | `src/agents/` | Patient / nurse / family agents + router | 🚧 Phase 4 |
| Memory | `src/memory/` | Episodic memory, context-window construction | 🚧 Phase 5 |
| API | `src/api/` | FastAPI routes (thin) | 🚧 Phase 6 |
| Frontend | `frontend/` | Streamlit UI (HTTP only) | 🚧 Phase 6 |
| Evaluation | `src/evaluation/` | LLM-as-judge rubric scoring + report | 🚧 Phase 7 |

**Dependency direction:** agents → LLM layer (never raw provider SDKs); routes →
core modules (never the reverse); state and scenarios depend on nothing of ours
except each other (pure, no I/O), which keeps their tests fast and isolated.

---

## 3. Core Layer (✅ Phase 1)

- **`config.py`** — `Settings` (pydantic-settings, `.env`-loaded, `lru_cache`
  singleton via `get_settings()`) and `AGENT_CONFIG`, a dict of typed
  `AgentLLMConfig(provider, model, fallback)`. Swapping a model is a one-line
  change here and nowhere else (ADR-005, ADR-006, ADR-007, ADR-008).
- **`logging.py`** — structlog, env-switched JSON vs console rendering,
  contextvars propagation (e.g. `session_id`), `get_logger(component)`.
- **`exceptions.py`** — normalized `LLMError` hierarchy: `LLMRateLimitError`
  (429), `LLMServerError` (5xx), `LLMResponseError` (empty/malformed).

## 4. LLM Layer (✅ Phase 1)

`client.complete(agent_name, prompt)` looks up the agent's config, calls the
primary provider wrapped in exponential backoff, and routes failures: 429 →
backoff then fallback; 5xx → immediate fallback; no fallback configured → raise
(the judge fails loudly by design). Provider adapters (`gemini.py`, `groq.py`)
translate each SDK's errors into the normalized hierarchy via `_map_error`, so
the client routes without knowing which provider it is talking to (ADR-005,
ADR-012). Backoff (1/2/4/8s) lives in `retry.py` and retries 429s only.

## 5. State Layer (✅ Phase 2)

The patient's "brain" as data: the full clinical truth plus what the student has
uncovered so far.

- **`scenarios/schema.py`** — the validation contract. `ScenarioNode` has a
  strict core (`id`, `label`, `category`, `revealed`, `importance`), optional
  `detail` / `disclosure_difficulty`, and an open `metadata` bag for
  per-scenario extras. `ScenarioEdge` carries a `relation` (string or list).
  `Scenario` enforces unique ids and rejects dangling edges. `load_scenario`
  reads + validates a file (ADR-017).
- **`scenarios/chest_pain.json`** — first authored patient (16 nodes across all
  categories, including a hidden cocaine-use precipitant and objective vitals in
  `metadata`). Doubles as a test fixture and the seed example for Phase 3's
  generator.
- **`src/state/graph.py`** — `PatientStateGraph`, a behaviour wrapper over an
  undirected `networkx.Graph` (edges = clinical associations, not reveal gates;
  ADR-018). Verbs: `mark_revealed` (idempotent, reports only new flips, skips
  hallucinated ids), `is_revealed`, `revealed_ids` / `hidden_ids`, `neighbors`,
  and `summary` (facts grouped by category, each marked revealed/hidden — the
  text the memory layer feeds the LLM).
- **`src/state/builder.py`** — `build_graph(scenario)` turns a validated
  scenario into a live graph, copying every node attribute (core + metadata) so
  the graph is the single source of truth.
- **`src/state/serializer.py`** — `serialize` / `deserialize` via NetworkX
  node-link format (pinned `edges="edges"`); round-trip-lossless, JSON-safe for
  the `state_snapshot_json` column (ADR-015, ADR-019).

## 6. RAG Layer (✅ Phase 3)

Turns a library of synthetic clinical cases into *fresh, varied, schema-valid*
patients on demand. The chain is bottom-up: embed → retrieve → generate.

- **`src/rag/corpus/`** — 15 synthetic clinical case `.txt` files across five
  presentations (chest pain, dyspnea, abdominal pain, headache, leg swelling),
  each varying the underlying cause, demographics, severity, and emotional
  context. Each file is one whole document (no chunking, ADR-021); its category
  comes from the filename prefix and a `# SYNTHETIC CASE` header marks
  provenance (ADR-013).
- **`src/rag/embedder.py`** — `Embedder`, the single text→vector seam. Wraps the
  local ONNX `all-MiniLM-L6-v2` model (free, offline, deterministic — no quota,
  no torch), returning plain 384-dim float vectors. Model choice lives here and
  nowhere else (ADR-020).
- **`src/rag/retriever.py`** — `Retriever` over ChromaDB. `ingest_corpus` embeds
  every case once (idempotent `upsert`), parsing the category from the filename
  and stripping the provenance header before embedding. `query(text, category,
  k)` does dense semantic search with a **category metadata pre-filter** — a
  hard guarantee that a request for one specialty never returns another
  (ADR-021). The collection is injected: in-memory in tests, on-disk
  (`chroma_data/`) in the app.
- **`src/rag/generator.py`** — `ScenarioGenerator`, the only Phase 3 piece that
  calls an LLM. `generate(ScenarioRequest)` retrieves the top-3 cases for the
  requested specialty, prompts the model to *synthesize a new patient* inspired
  by them (not copy one), then parses and validates the output against
  `scenarios/schema.py`. On failure it feeds the exact validation error back and
  re-prompts, up to `max_repairs` times — the schema is both the gate and the
  self-correction signal (ADR-022). The LLM call is injected so tests drive the
  whole loop with no real provider call. Output is guaranteed to build via
  `state/builder.py`.

## 7. Agents Layer — 🚧 To be filled in (Phase 4)

_Patient / nurse / family agents and the router (explicit UI addressing with LLM
fallback, ADR-009). All agents return structured JSON `{response_text,
revealed_nodes, emotional_state}` (ADR-010)._

## 8. Memory Layer — 🚧 To be filled in (Phase 5)

_Episodic memory and context-window construction: last N turns + state-graph
summary + persona/constraints + what has/hasn't been revealed._

## 9. API & Frontend — 🚧 To be filled in (Phase 6)

_FastAPI routes (sessions, conversation, evaluation) and the Streamlit UI._

## 10. Evaluation Layer — 🚧 To be filled in (Phase 7)

_LLM-as-judge over the transcript + process-based rubric (ADR-011); Groq/Llama,
no fallback (fail loudly)._

---

## 11. Data Flows

### Session start
```
scenario type → RAG retrieve + generate patient JSON → schema validate
            → builder.build_graph → in-memory PatientStateGraph
            → SQLite session row → Streamlit renders intro
```

### Conversation turn
```
student message (optionally addressed) → router resolves speaker
   → memory builds context (last N turns + graph.summary() + persona)
   → llm.complete(agent, prompt) → agent returns {response_text, revealed_nodes, emotional_state}
   → graph.mark_revealed(revealed_nodes) → turn saved to SQLite → response shown
```

### Session end
```
end trigger → transcript from SQLite + rubric from scenario file
          → judge LLM → evaluation JSON → SQLite → report rendered
          → final graph serialized to state_snapshot_json
```

---

## 12. Persistence

- **SQLite** (`src/db/`) — `sessions`, `conversation_turns`, `evaluations`.
  Session-per-request unit-of-work (ADR-014); structured columns stored as
  `JSON` (ADR-015); schema via `create_all`, Alembic deferred (ADR-016).
- **ChromaDB** (`src/rag/`) — clinical-case embeddings, queried at session start
  for scenario generation. On-disk collection at `chroma_data/` (gitignored),
  embedded once from `src/rag/corpus/`; in-memory in tests (ADR-021).
- **In-memory** — the live `PatientStateGraph` exists only during a session and
  is snapshotted to SQLite at the end (lost on restart, acceptable for MVP;
  ADR-003).

---

## 13. Testing Strategy

Test-first (TDD). No real LLM calls in tests (they burn free-tier quota) and no
real network: provider adapters are tested at their error-normalization seam,
and the DB uses in-memory SQLite with `StaticPool`. The state layer is pure, so
its tests construct graphs directly. The RAG layer tests against the *real*
local embedder and an in-memory ChromaDB (both free and offline), and injects a
fake LLM into the generator so the validate-and-repair loop is exercised with no
provider call. As of Phase 3: **90 unit tests**.

> **🚧 To be filled in:** integration-test strategy once a live provider path
> and the end-to-end conversation loop exist (Phase 6).
