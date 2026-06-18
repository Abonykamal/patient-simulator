# Changelog

All notable changes to the Patient Journey Simulator are documented here.
Format: Date → What was built → Decisions made

---

## [Unreleased]

### 2026-06-18 — Phase 8: evaluation quality fixes from live runs (161 unit tests total, +2)
- Driving the app surfaced rubric-quality issues the fake-injected tests couldn't (see ADR-032 Refinements):
- `src/evaluation/rubric.py` — grade only `critical`/`relevant` nodes; `minor` incidental colour ("hairdresser", "lives alone") stays in the graph but is no longer graded (category filtering rejected — `social` holds both "smoker" and "hairdresser")
- `src/evaluation/judge.py` / `report.py` — judge verdict is now `asked`/`not_asked`/**`not_applicable`**; `not_applicable` (objective findings, vitals, observed behaviour like "downplaying symptoms") is dropped from the score's denominator. Askability is decided by the judge, not a generator field (a prototyped `probe` node-field was reverted as generator-biasing/over-engineered)
- `src/rag/generator.py` — `scenario_intro` instruction now requires a name/age/presenting-complaint **door-stem** (schematic form, no concrete example) so the intro stops leaking history the student should elicit
- Generation variety **tabled** (corpus has only 2–4 cases/category) — not needed for the portfolio/MVP goal; structured input parameterisation recorded as the future lever

### 2026-06-17 — Phase 7: Evaluation complete (159 unit tests total, +20)
- `src/evaluation/rubric.py` — `build_rubric(scenario)`: derives the grading rubric from the scenario's nodes (topic + `importance`), consuming the field ADR-017 carried for exactly this; no schema change
- `src/evaluation/judge.py` — the LLM-as-judge (`agent_name="judge"` → Groq/Llama, no fallback): the approved **process-based** prompt (grade asking not answers; "asked" needs an explicit student utterance incl. clinical paraphrase; never infer from the patient's reply), classifies each item asked/not-asked + a reasoning narrative, validate-and-repair, LLM injected
- `src/evaluation/report.py` — pure: `score` = weighted coverage (`critical=3, relevant=2, minor=1`) + `format_report`; judgement is the LLM's, arithmetic is code's (reproducible, testable)
- `src/evaluation/evaluator.py` — `evaluate_session`: idempotent (returns existing, no re-judge) → build rubric → judge → score+format → mark session completed (no graph snapshot — redundant under ADR-030) → save; judge injected
- `src/api/` — `POST /sessions/{id}/evaluate` (ends + judges + saves; **fail-loud 503**, 404 unknown) + `GET /sessions/{id}/report`; `EvaluationResponse`, `get_judge` dep, judge singleton in lifespan
- `frontend/app.py` — "End interview & get feedback" button → score + covered/missed + examiner's notes + full report
- `scripts/smoke_evaluation.py` — hand-run live judge over a seeded transcript (one Groq call)
- ADR-032 added (rubric-from-nodes, judge-classifies/code-scores, dedicated evaluator, idempotent fail-loud); supersedes ADR-030's end-of-session snapshot note (D6)

### 2026-06-17 — Phase 6: Full Conversation Loop complete (139 unit tests total, +15)
- `src/conversation/orchestrator.py` — the per-turn loop, pure and injected: `start_session` (RAG generate → persist full scenario) and `run_turn` (router → memory context → agent LLM → `mark_revealed` → trust nudge → persist). **Rebuild-from-turns** lifecycle (the turns are the event log, the graph a projection — ADR-030); trust read back from the last patient turn and clamped; writes ordered **after** the LLM call so a failed turn is retry-safe (ADR-029)
- `src/api/` — thin FastAPI layer (CLAUDE.md): `schemas.py` (request/response; `TurnResponse` omits `revealed_nodes` — internal-only), `deps.py` (the `dependency_overrides` seam), `routes/sessions.py` (`POST /sessions`, `GET /sessions/{id}`), `routes/conversation.py` (`POST /sessions/{id}/turns`), `main.py` (app + lifespan building the singletons onto `app.state`). Errors map to 503 (provider/agent failure) / 404 (unknown session)
- `frontend/app.py` — Streamlit UI: scenario picker → intro → explicit `Talking to` dropdown (three people, no Auto-detect — ADR-031) → client-side transcript; HTTP only, never imports `src/`
- `scripts/smoke_conversation.py` — hand-run live test of the full loop (first real agent→Gemini call); excluded from the suite, like `smoke_generator.py`
- No reviewed module edited — agents, memory, state, llm, db, rag all consumed as-is
- Tooling: added `fastapi`, `uvicorn`, `streamlit`, `requests`; one narrow pytest `filterwarnings` for Starlette's TestClient httpx deprecation
- ADRs 029–031 added (orchestrator/DI/error boundary, rebuild-from-turns lifecycle, explicit UI addressing)

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
