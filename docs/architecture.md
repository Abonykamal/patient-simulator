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
| Agents | `src/agents/` | Patient / nurse / family agents + router | ✅ Phase 4 |
| Memory | `src/memory/` | Per-agent context assembly: slice + rapport + recent turns; trust clamp | ✅ Phase 5 |
| Conversation | `src/conversation/` | The per-turn orchestrator (`start_session`, `run_turn`): router → memory → agent → state → db | ✅ Phase 6 |
| API | `src/api/` | FastAPI routes (thin) + lifespan-built singletons | ✅ Phase 6 |
| Frontend | `frontend/` | Streamlit UI (HTTP only) | ✅ Phase 6 |
| Evaluation | `src/evaluation/` | LLM-as-judge: rubric (from nodes), judge, score+report, coordinator | ✅ Phase 7 |

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

## 7. Agents Layer (✅ Phase 4)

Turns the patient's state (data) into characters that talk. Three personas plus a
router; the personas share one pipeline and differ only in voice and what they
know.

- **`base.py`** — `BaseAgent`, a template-method pipeline every persona reuses:
  assemble prompt → `llm.client.complete` → parse/validate/**repair** into an
  `AgentResponse` (`response_text`, `revealed_nodes`, `emotional_state`; ADR-010).
  Subclasses override only `_persona()`. The repair loop and injected `complete_fn`
  are reused from the Phase 3 generator, so the codebase coaxes JSON from LLMs one
  consistent way. Agents never write to the graph — they *report* `revealed_nodes`
  and the caller applies `mark_revealed` (ADR-023).
- **`patient.py`** — `PatientAgent`. Plays the specific patient; constructed with
  `patient_name`, the mutable truth injected per turn as context. Disclosure is
  prompt-enforced via the `volunteered → if_asked → only_if_asked_directly →
  only_if_trust_built` hierarchy plus a trust rubric (no code gate, ADR-023). Its
  guardrails keep it believable: plain language, answer only what's asked, memory
  vagueness, no diagnosis leakage, defers vitals/exam to staff, 1–3 sentences.
- **`nurse.py`** — `NurseAgent`. The patient's mirror: *precise* (reads numbers
  off the chart) and *defers personal history to the patient*. Reports only
  documented facts; never diagnoses, interprets, or reasons clinically.
- **`family.py`** — `FamilyAgent`. A worried relative giving collateral history;
  first-person, reports observation not inference, no invented family history,
  defers clinical detail to staff. Its slice excludes `hidden` nodes so it never
  leaks secrets (ADR-024).
- **`router.py`** — `Router`. Resolve-only: explicit addressing wins, an
  unaddressed message defaults to the patient, and a one-word LLM classifier fires
  only on an explicit `AUTO` request — keeping the common path at zero LLM calls
  (ADR-009/ADR-025). Classifier replies are parsed defensively (fall back to
  patient).

Per-agent knowledge slicing (who sees what) is enforced by the context the caller
assembles (Phase 5) and described again in each persona (ADR-024). All persona
prompts also refuse false premises in leading questions — a clinical-skills
validity guard.

## 8. Memory Layer (✅ Phase 5)

Pure, I/O-free assembly of each agent's per-turn `context` string. It is handed
typed objects (the `PatientStateGraph`, a list of `HistoryTurn`s, the current
`trust_level`) and returns a string — it never opens a DB session or calls an LLM
(ADR-026). The Phase 6 orchestrator owns those boundaries.

- `context_builder.py` — the pure renderer. Owns the per-agent **slice policy**
  (`agent → visible categories`, the literal encoding of ADR-024/ADR-028) applied
  over the graph's generic `facts()` **mechanism**, and the labelled layout
  (design D6): state slice → patient-only rapport line → recent turns, with the
  agent's own turns labelled "you". Nurse/family never see `hidden`; the nurse's
  objective `metadata` (vitals) is surfaced. Defines `HistoryTurn`, a
  framework-free turn type so the layer never imports `db.models`.
- `manager.py` — the public API the orchestrator calls. Filters all turns to the
  agent's **own thread** (per-agent threading, D2 — so one agent's spoken
  disclosures never leak into another's context), windows it to the last
  `RECENT_EXCHANGES_N` exchanges (D6), and delegates rendering. Hosts
  `apply_rapport_delta`, the persisted-trust clamp (ADR-027).
- `summarizer.py` — deferred stub (design D5): the graph's `[revealed]` flags and
  the persisted `trust_level` already capture what a prose recap would, so none is
  injected for the MVP.

Trust (C2, ADR-027): a persisted `trust_level` (0–3, baseline 1) is nudged by a
bounded `rapport_delta` the patient emits in its own JSON; `only_if_trust_built`
facts unlock at level 3. Persisted per patient turn for the Phase 7 trajectory.

## 9. Conversation, API & Frontend (✅ Phase 6)

**Orchestrator** (`src/conversation/orchestrator.py`) — the per-turn glue, pure and
injected so it unit-tests with fakes and no network. `start_session` generates a
patient (RAG) and stores the *full* scenario in `patient_profile_json`. `run_turn`
rebuilds the state graph from the stored scenario + the per-turn reveal log
(rebuild-from-turns / event sourcing, ADR-030), reads current trust from the last
patient turn, builds this session's router via the injected `build_router(patient_name)`
factory (the patient agent is parameterised by the patient's name, so the router cannot
be a global singleton), resolves the agent, builds *its* context (memory), calls it
(the live LLM), applies `mark_revealed` + the rapport nudge, then persists the
student + agent turns. The LLM call runs **before** any write, so a failed turn
leaves zero partial state and is retry-safe (ADR-029).

**API** (`src/api/`) — a thin FastAPI layer (CLAUDE.md). `main.py`'s lifespan builds
the expensive singletons once (Retriever+corpus, agents, Router, generator) onto
`app.state`; `deps.py` hands them to routes and is the single seam tests override
with `dependency_overrides`. Routes (`sessions.py`, `conversation.py`) unpack the
request, call the orchestrator, and shape the response; an agent/provider failure
becomes a `503` and an unknown session a `404`. `schemas.py` holds the
request/response models — `TurnResponse` omits `revealed_nodes` (the student must
not see what they surfaced).

**Frontend** (`frontend/app.py`) — Streamlit, HTTP only, never imports `src/`. A
scenario picker starts a session; the transcript is kept client-side; a `Talking
to` dropdown selects the recipient explicitly (three people, no Auto-detect —
ADR-031). Endpoints used: `POST /sessions`, `GET /sessions/{id}`, `POST
/sessions/{id}/turns`.

The evaluate/report endpoints and the end-session affordance are deferred to
Phase 7 (ADR-029). The live agent path is exercised by the hand-run
`scripts/smoke_conversation.py`.

## 10. Evaluation Layer (✅ Phase 7)

The end-of-session LLM-as-judge (ADR-032). Four small modules + a coordinator:

- **`rubric.py`** — `build_rubric(scenario)` turns each node into a `RubricItem`
  (topic = label, weight = `importance`). The rubric is *derived*, not authored —
  consuming the `importance` field ADR-017 carried for exactly this.
- **`judge.py`** — the LLM-as-judge (`agent_name="judge"` → Groq/Llama, **no
  fallback**). The approved **process-based** prompt grades *asking* not answers:
  an item is "asked" only with an explicit student utterance (incl. clinical
  paraphrase), never inferred from the patient's reply. Returns per-item
  asked/not-asked + a reasoning narrative; validate-and-repair; LLM injected.
- **`report.py`** — pure: `score` = weighted coverage (`critical=3, relevant=2,
  minor=1`), `format_report` wraps the narrative with the score + covered/missed.
  The judge does judgement; code does the arithmetic (reproducible, testable).
- **`evaluator.py`** — `evaluate_session(db, judge, id)`: idempotent (returns an
  existing evaluation, no re-judge) → build rubric → render transcript → judge →
  score+format → mark session `completed` → save. The judge call runs before any
  write; on failure the route returns **503 (fail loud)** — a degraded evaluation
  must not look like a pass.

Exposed via `POST /sessions/{id}/evaluate` (ends + judges + saves) and
`GET /sessions/{id}/report`. No end-of-session graph snapshot — rebuild-from-turns
(ADR-030) makes it redundant. Live judge proven by `scripts/smoke_evaluation.py`.

---

## 11. Data Flows

### Session start
```
scenario type → orchestrator.start_session → RAG retrieve + generate patient JSON
            → schema validate → full scenario stored in patient_profile_json
            → SQLite session row → Streamlit renders intro
```

### Conversation turn
```
student message (+ explicit recipient) → orchestrator.run_turn
   → rebuild graph from stored scenario + reveal log (ADR-030); read current trust
   → router resolves agent → memory builds its context (slice + rapport + last N turns)
   → agent.respond → live LLM → {response_text, revealed_nodes, emotional_state, rapport_delta}
   → graph.mark_revealed + trust nudge → student + agent turns saved to SQLite → reply shown
```

### Session end
```
POST /evaluate → evaluator.evaluate_session (idempotent)
          → build_rubric(scenario) + transcript from SQLite
          → judge LLM (Groq, no fallback) → per-item asked/not-asked + notes
          → report.score (weighted coverage) + format_report
          → mark session completed (no snapshot, ADR-030) → save_evaluation → report rendered
```

---

## 12. Persistence

- **SQLite** (`src/db/`) — `sessions`, `conversation_turns`, `evaluations`.
  Session-per-request unit-of-work (ADR-014); structured columns stored as
  `JSON` (ADR-015); schema via `create_all`, Alembic deferred (ADR-016).
- **ChromaDB** (`src/rag/`) — clinical-case embeddings, queried at session start
  for scenario generation. On-disk collection at `chroma_data/` (gitignored),
  embedded once from `src/rag/corpus/`; in-memory in tests (ADR-021).
- **No mid-session in-memory state** — the live `PatientStateGraph` is rebuilt each
  turn from the stored scenario + the per-turn reveal log (rebuild-from-turns,
  ADR-030, superseding the in-session-only approach of ADR-003), so the DB is the
  single source of truth and the loop is stateless / restart-safe. No graph
  snapshot is taken even at session end — it would be redundant under
  rebuild-from-turns (ADR-032, D6) — so the `serializer` and `state_snapshot_json`
  remain available but unused.

---

## 13. Testing Strategy

Test-first (TDD). No real LLM calls in tests (they burn free-tier quota) and no
real network: provider adapters are tested at their error-normalization seam,
and the DB uses in-memory SQLite with `StaticPool`. The state layer is pure, so
its tests construct graphs directly. The RAG layer tests against the *real*
local embedder and an in-memory ChromaDB (both free and offline), and injects a
fake LLM into the generator so the validate-and-repair loop is exercised with no
provider call. The agents layer injects a fake `complete_fn` into each agent and
the router, so personas, the repair loop, and routing are all tested without a
real call. The conversation orchestrator is tested directly against in-memory
SQLite with fake agents/router/generator (reveals replay, trust read-back/clamp,
resolved-name threading, retry-safety on failure); the FastAPI routes get thin
`TestClient` tests with `dependency_overrides` (happy path + 503/404 shapes), so
the HTTP seam is covered without building the real singletons. The evaluation layer
follows the same pattern: rubric/report are pure (direct tests), the judge and the
`evaluate_session` coordinator use a fake judge over in-memory SQLite (scoring,
idempotency, fail paths). As of Phase 7: **159 unit tests**.

The three live paths are covered only by hand-run smoke scripts excluded from the
suite — `scripts/smoke_generator.py` (RAG → generator),
`scripts/smoke_conversation.py` (the full loop with live agents), and
`scripts/smoke_evaluation.py` (the live judge). A dedicated
automated integration suite remains deferred; the smoke scripts are the
deliberate, manual exception.
