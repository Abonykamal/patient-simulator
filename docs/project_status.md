# Project Status

## Current State
**Phase:** Phase 7 (Evaluation) complete; Phase 8 (Polish) underway — 166 unit tests passing
**Last updated:** 19-June-2026

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
- [x] `src/agents/base.py` — `BaseAgent` template-method pipeline + `AgentResponse` (LLM injected, validate-and-repair; prompt-enforced disclosure, ADR-023; 4 unit tests)
- [x] `src/agents/patient.py` — `PatientAgent`: approved persona, disclosure hierarchy + trust rubric, no diagnosis leakage, defers vitals (ADR-024; 2 unit tests)
- [x] `src/agents/nurse.py` — `NurseAgent`: documented-facts-only, no clinical reasoning, defers personal history to patient (ADR-024; 2 unit tests)
- [x] `src/agents/family.py` — `FamilyAgent`: first-person collateral, observation-not-inference, slice excludes hidden nodes (ADR-024; 2 unit tests)
- [x] `src/agents/router.py` — `Router`: resolve-only, explicit addressing → default-to-patient → `AUTO` classifier; defensive parse; `router` added to AGENT_CONFIG (ADR-009/ADR-025; 4 unit tests)
- All personas refuse false premises in leading questions (clinical-skills validity guard)

### Phase 5: Memory & Context (Day 3-4)
- [x] `src/memory/context_builder.py` — pure per-agent context renderer: slice policy over `graph.facts()`, labelled blocks (slice → patient-only rapport line → recent turns), `HistoryTurn` type (ADR-024/026/028; 6 unit tests)
- [x] `src/memory/manager.py` — public API: per-agent thread-filter + windowing + `apply_rapport_delta` clamp; pure/injected (ADR-026/027; 3 unit tests)
- [x] `src/memory/summarizer.py` — deferred stub: structured stores cover the MVP (design D5; 1 guard test)
- [x] Prereqs: `graph.facts()` accessor, `AgentResponse.rapport_delta` + `_json_fields`, patient persona rapport additions, `trust_level`/`addressed_to` columns, config tunables (+10 unit tests)

### Phase 6: Full Conversation Loop (Day 4)
- [x] `src/conversation/orchestrator.py` — `start_session` + `run_turn`: the pure injected loop (router → memory → agent → state → db); rebuild-from-turns lifecycle, trust read-back/clamp, writes-after-LLM-call (ADR-029/030; 8 unit tests)
- [x] `src/api/schemas.py` — request/response models; `TurnResponse` omits `revealed_nodes` (internal-only)
- [x] `src/api/deps.py` — `Depends` providers (the single `dependency_overrides` seam for tests)
- [x] `src/api/routes/sessions.py` — `POST /sessions`, `GET /sessions/{id}` (thin; 503/404 mapping)
- [x] `src/api/routes/conversation.py` — `POST /sessions/{id}/turns` (thin; 503/404 mapping)
- [x] `src/api/main.py` — FastAPI app + lifespan building the singletons (Retriever+corpus, agents, Router, generator) onto `app.state`
- [x] Thin route tests via `TestClient` + `dependency_overrides` (7 unit tests)
- [x] `frontend/app.py` — Streamlit UI: scenario picker → intro → `Talking to` dropdown (explicit, three people) → client-side transcript; HTTP only, never imports `src/`
- [x] `scripts/smoke_conversation.py` — hand-run live test of the full loop (first real agent→Gemini call); excluded from the suite
- [x] Tooling: added `fastapi`, `uvicorn`, `streamlit`, `requests`; one narrow pytest `filterwarnings` for Starlette's TestClient

### Phase 7: Evaluation (Day 5-6)
- [x] `src/evaluation/rubric.py` — `build_rubric(scenario)`: `critical`/`relevant` nodes → `RubricItem`s (`minor` excluded); derives the rubric, no schema field (ADR-032; 3 unit tests)
- [x] `src/evaluation/judge.py` — the LLM-as-judge (Groq, no fallback): approved process-based prompt, classifies each item `asked`/`not_asked`/`not_applicable` + reasoning narrative, validate-and-repair, LLM injected (ADR-032; 4 unit tests)
- [x] `src/evaluation/report.py` — pure: `score` (weighted coverage 3/2/1, `not_applicable` dropped from denominator) + `format_report`; judgement is the LLM's, arithmetic is code's (ADR-032; 7 unit tests)
- [x] `src/evaluation/evaluator.py` — `evaluate_session`: idempotent → build rubric → judge → score+format → end session (no snapshot, D6) → save; judge injected (ADR-032; 3 unit tests)
- [x] `src/api/routes/evaluation.py` — `POST /sessions/{id}/evaluate` (ends+judges+saves; 404/503 fail-loud) + `GET /sessions/{id}/report`; `EvaluationResponse`, `get_judge` dep, judge singleton in lifespan (5 route tests)
- [x] `frontend/app.py` — "End interview & get feedback" button → score + covered/missed + notes + full report
- [x] `scripts/smoke_evaluation.py` — hand-run live judge over a seeded transcript (one Groq call)

### Phase 8: Polish (Day 7-8)
- [x] Rubric/judge quality fixes from live runs: `minor`-importance filter; judge `not_applicable` for findings/observations; generator door-stem intro (no leaked history) — see ADR-032 Refinements
- [ ] Second scenario file
- [ ] RAG tested with multiple scenario types
- [x] Edge cases handled (ADR-033): completed-session turn → `SessionClosedError`/**409** (+ UI hides input); blank `content` and non-`{patient,nurse,family}` `addressed_to` → **422** at the schema; empty interview → 0% report with **no judge call** (+5 unit tests)
- [x] `README.md` — portfolio-facing: what it is + what it demonstrates, layered architecture + data-flow, tech stack, setup (`uv sync` + keys), run, use, test, structure, design notes/limitations
- [ ] Demo recording

---

## What's Next
Phase 7 done; Phase 8 (Polish) underway — the system is functionally complete end to end (create → converse → evaluate), has had a first round of live-run quality fixes (ADR-032 Refinements), and is now edge-case hardened (ADR-033) with a portfolio README. Remaining Phase 8: RAG exercised across multiple specialties, and an optional demo recording. The "second authored scenario file" is **dropped** as low-value: the app always generates dynamically and already supports all five presentation types, and authored scenario JSONs are never served (only `chest_pain.json` exists, as a test fixture) — a second one would only matter if we added a deterministic offline "demo mode", which we decided against. Known, deliberately-deferred items: generation variety is **tabled** (only matters for a real product, not the portfolio MVP — structured input parameterisation is the recorded future lever); no list/resume of past sessions. Completed sessions now **do** block further turns (ADR-033). The "generally healthy"-style answer-phrased labels are handled by the judge's `not_applicable`/topic interpretation rather than a generator field.

Note (run before demoing): confirm the live judge with `scripts/smoke_evaluation.py` (one Groq call) and the full app with `uv run uvicorn src.api.main:app --port 8000` + `uv run streamlit run frontend/app.py`. Run servers via `uv run` (or activate `.venv`) — a bare `uvicorn`/`streamlit` resolves to the system install, which lacks our deps.

Note: the live agent path is **confirmed working** — `scripts/smoke_conversation.py` was run on 17-June-2026 and passed: live scenario generation (one validate-and-repair cycle) → 4 live agent turns (patient ×2, nurse, family) → 8 turns persisted, reveals tracked, trust read back/clamped. It makes real Gemini calls (generation + agent replies), so it costs free-tier quota and is excluded from the suite, like `scripts/smoke_generator.py`. The smoke test also surfaced one integration gap the fake-injected unit tests could not: the patient agent is parameterised by the patient's name, so the router is injected as a per-session `build_router(patient_name)` factory (ADR-029).

Note: the live network path is exercised only by the two hand-run smoke scripts — `scripts/smoke_generator.py` (corpus → embed → retrieve → `scenario_generator` LLM → schema-validate → graph) and `scripts/smoke_conversation.py` (full loop: `start_session` → `run_turn` × N with live agents). Automated tests still make **no** real provider calls — every LLM collaborator is injected/faked; the smoke scripts are the deliberate, hand-run exceptions.

Embedding model note: the ONNX `all-MiniLM-L6-v2` (~80 MB) downloads once on first embed to `~/.cache/chroma`, then runs offline. ChromaDB's persistent store lives at `chroma_data/` (gitignored).

Decisions locked in (reflected in project_spec.md / decisions.md):
- RAG embeddings: local ONNX MiniLM behind the `Embedder` seam — free/offline/deterministic, no torch (ADR-020)
- RAG retrieval: whole-case documents (no chunking), dense semantic + category metadata pre-filter, top-3, no hybrid/BM25 (ADR-021)
- Scenario generation: synthesise from top-3, validate-and-repair against the schema, LLM injected (ADR-022)
- State graph: undirected NetworkX, edges = clinical associations not reveal gates; relation as edge attribute (str or list), no MultiGraph (ADR-018)
- Scenario nodes: strict core fields + open `metadata` bag; core logic never branches on metadata (ADR-017)
- Graph serialization: NetworkX node-link format behind the serializer seam (ADR-019)
- Agent base: template-method `BaseAgent`, prompt-enforced disclosure (no code gate), context injected as a parameter; LLM injected for tests (ADR-023)
- Per-agent knowledge slicing: patient sees all, nurse documented-only, family social/emotional/family-history excluding hidden nodes (ADR-024)
- Router: resolve-only, explicit addressing → default-to-patient → `AUTO` one-word classifier (zero LLM cost on the common path), defensive parse (ADR-009/ADR-025)
- Agents always return structured JSON: response_text, revealed_nodes, emotional_state (ADR-010); all personas refuse leading-question false premises
- Rubric is process-based (asking counts regardless of patient's actual history)
- Per-agent optional fallback in AGENT_CONFIG; 429 → fallback after backoff, 5xx → immediately; judge has no fallback (fail loudly)
- Memory & context: inputs injected as typed objects (graph, `HistoryTurn`s, `trust_level`) and rendered to a string; per-agent conversation threading; labelled context = slice → patient rapport line → last `RECENT_EXCHANGES_N` exchanges (ADR-026)
- Trust model C2: persisted `trust_level` (0–3) nudged by a patient-emitted `rapport_delta` (−1/0/+1), `only_if_trust_built` unlocks at 3, persisted per patient turn (ADR-027)
- Per-agent slice: policy in memory (`context_builder`), generic mechanism in graph (`facts()`) — graph stays agent-agnostic (ADR-028)
- Conversation summarizer deferred: structured stores (graph reveals + `trust_level`) cover the MVP (design D5)

