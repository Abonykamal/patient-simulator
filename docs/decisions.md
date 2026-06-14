# Architecture Decision Records (ADRs)

All significant architectural and design decisions made during this project are logged here.
Format: context → options considered → decision → reasoning → consequences.

This document exists to show the human decision-making process behind the system design.
Code was generated with AI assistance. Every decision in this file was made by the engineer.

---

## ADR-001: File Structure Philosophy
**Date:** June 2026
**Status:** Accepted

**Context:**
Needed to decide how to organize the project's folders — by feature (everything for one feature together) or by layer (everything of the same type together).

**Options considered:**
- A) Feature-based: `patient/` contains agent, schema, routes, tests for the patient feature
- B) Layer-based: `agents/`, `schemas/`, `api/` each contain their respective files across all features
- C) Hybrid: AI system components grouped as layers, but each layer is a cohesive AI concern

**Decision:** Hybrid layer-based (Option C) — layers map to AI system components, not traditional web app layers.

**Reasoning:**
For an AI engineering project, the natural grouping is by what kind of AI work each component does — not by web app convention. When debugging why an agent isn't reading memory correctly, the relevant files are in `agents/` and `memory/` — two folders, not scattered across five feature folders. This mirrors how production AI repos (LangChain, most serious LLM pipelines) are structured. Pure feature-based structure is better for large teams where different engineers own different features — not applicable here.

**Consequences:**
Layers are: `agents/`, `memory/`, `rag/`, `evaluation/`, `state/`, `llm/`, `db/`, `api/`, `core/`. Adding a new scenario type means adding data files, not new folders. Adding a new agent means adding one file to `agents/`.

---

## ADR-002: Frontend Architecture
**Date:** June 2026
**Status:** Accepted

**Context:**
Needed a frontend that allows medical students to interact with the simulation. Decision was whether to build a single-service app or a separated backend/frontend.

**Options considered:**
- A) Streamlit only — single Python service, state managed by Streamlit
- B) FastAPI backend + Streamlit frontend — two services, Streamlit calls FastAPI over HTTP
- C) FastAPI backend + React frontend — production-grade separation, more complex

**Decision:** FastAPI backend + Streamlit frontend (Option B)

**Reasoning:**
FastAPI is the industry standard for serving LLM-backed APIs — it's async-native, auto-generates OpenAPI docs, and is what interviewers expect to see. Streamlit is not a production frontend but it's fast to build and keeps focus on the AI engineering, not CSS. The key constraint: Streamlit only calls FastAPI over HTTP — no direct imports from `src/`. This means replacing Streamlit with React later requires zero changes to the backend. The seam is clean by design.

**Consequences:**
All business logic lives in FastAPI. Streamlit is a thin UI layer. The FastAPI backend is independently testable and demonstrable without any frontend.

---

## ADR-003: Patient State Representation
**Date:** June 2026
**Status:** Accepted

**Context:**
The patient's medical state — symptoms, history, hidden information, emotional arc — needed to be represented in memory during a session. The key question was how to encode relationships between pieces of information, not just the information itself.

**Options considered:**
- A) Flat dictionary — `{"symptoms": [...], "history": [...], "hidden": [...]}`
- B) NetworkX graph — nodes for each piece of information, edges for relationships between them
- C) Relational tables in SQLite — structured but requires DB reads on every turn

**Decision:** NetworkX graph, in-memory during session (Option B)

**Reasoning:**
A flat dictionary can store values but cannot encode relationships. Chest pain *connects to* shortness of breath. Smoking *increases risk of* cardiac events. The father's death *triggers* emotional avoidance. These relationships determine what gets revealed when — and that behavior should emerge from graph traversal, not hardcoded if/else logic. With a graph, adding a new scenario means defining new nodes and edges in a JSON file, not writing new conditional logic. NetworkX is a Python library (not a database), runs in-memory, and requires no infrastructure.

**Consequences:**
The graph lives in memory during a session and is lost on backend restart — acceptable for MVP. A snapshot is serialized to SQLite at session end. The `state/builder.py` module constructs the graph from LLM-generated patient JSON. The `state/serializer.py` handles graph ↔ JSON conversion for storage.

---

## ADR-004: Database Strategy
**Date:** June 2026
**Status:** Accepted

**Context:**
Two types of data need storage: structured relational data (sessions, conversation turns, evaluations) and vector embeddings (clinical cases for RAG retrieval). These have fundamentally different access patterns.

**Options considered for relational:**
- A) In-memory only — no persistence, sessions lost on restart
- B) SQLite + SQLAlchemy — file-based, no server, full SQL, ORM abstraction
- C) PostgreSQL — full production database, requires Docker service
- D) Redis — in-memory store, fast, used in production AI session management

**Options considered for vectors:**
- A) SQLite with serialized vectors — possible but not optimized for similarity search
- B) ChromaDB — vector database, library mode (no server), built for embedding storage and retrieval
- C) Pinecone — managed cloud vector DB, not free at scale

**Decision:** SQLite + SQLAlchemy for relational data; ChromaDB for vector data

**Reasoning:**
SQLite gives full persistence with zero infrastructure overhead — one file on disk. SQLAlchemy ORM means migrating to PostgreSQL later is a one-line config change. The distinction between the two databases maps to access pattern: SQLite answers "give me this specific thing by ID or filter"; ChromaDB answers "give me things semantically similar to this query." Regular SQL cannot do semantic similarity search. ChromaDB runs as a library (no server to manage), which keeps infrastructure minimal for an MVP. Redis deferred to future projects (job portal, production RAG system) where session caching at scale is genuinely needed.

**Consequences:**
Sessions, turns, and evaluations are queryable by ID and filterable by field. Clinical case retrieval is semantic — embedding-based, not keyword-based. ChromaDB is only queried at session start for scenario generation, not during conversation turns.

---

## ADR-005: LLM Provider Strategy
**Date:** June 2026
**Status:** Accepted

**Context:**
The project needs LLM calls for five distinct purposes: patient agent, nurse agent, family agent, scenario generation, and evaluation/judging. Free tier rate limits are a real constraint. Provider reliability varies.

**Options considered:**
- A) Single provider (Gemini) for everything — simplest, one API key, one client
- B) Per-agent provider config with abstraction layer — each agent independently configurable
- C) OpenAI — not free tier, excluded on cost grounds

**Decision:** Per-agent configuration with provider abstraction layer (Option B)

**Reasoning:**
Different agents have different requirements. The judge LLM needs strong analytical reasoning — Groq/Llama 3.3 70B is better suited and has separate rate limits from the conversation agents. The scenario generator benefits from a slightly more capable model (Gemini 2.5 Flash vs Flash-Lite) since it runs once per session, not per turn. The abstraction layer means agent code never knows which provider it's using — it calls `llm_client.complete(agent_name, prompt)` and the client handles routing. Swapping any agent's model is a one-line change in `AGENT_CONFIG`. This pattern mirrors how production AI systems handle multi-model orchestration.

**Current config:**
- Patient, nurse, family → Gemini 2.5 Flash-Lite (15 RPM, 1000 RPD free tier)
- Scenario generator → Gemini 2.5 Flash (higher capability, runs once per session)
- Judge → Groq / Llama 3.3 70B (separate rate limits, strong structured reasoning)

**Consequences:**
`src/llm/client.py` is the only file that knows about providers. All agents import `llm_client`, never `gemini` or `groq` directly. Exponential backoff (1s, 2s, 4s, 8s) on 429 errors implemented in `src/llm/retry.py`.

---

## ADR-006: LLM Config Typing
**Date:** June 2026
**Status:** Accepted

**Context:**
AGENT_CONFIG maps agent names to provider/model pairs. The question was whether to use plain Python dicts or typed Pydantic models for each agent's config entry.

**Options considered:**
- A) Plain dict — `{"provider": "gemini", "model": "gemini-2.5-flash-lite"}`
- B) Typed Pydantic model — `AgentLLMConfig(provider="gemini", model="gemini-2.5-flash-lite")`

**Decision:** Typed Pydantic model (Option B)

**Reasoning:**
With a plain dict, a typo in a provider name (`"gemmini"`) is stored silently and only surfaces as a confusing runtime error mid-session. With a typed Pydantic model, validation happens at startup — the application fails immediately with a clear error message before any user interaction. This is consistent with the project-wide standard of "Pydantic for all internal data." The typed model also makes adding an optional fallback field clean: `fallback: Optional[AgentLLMConfig] = None`.

**Consequences:**
All agent code receives validated config objects. Provider name typos crash at startup, not mid-session. The fallback field is part of the config schema from day one.

---

## ADR-007: Environment Variable Loading
**Date:** June 2026
**Status:** Accepted

**Context:**
API keys and configuration values need to be loaded from environment variables / `.env` file. The question was whether to use Python's standard `os.getenv` manually or use the `pydantic-settings` library.

**Options considered:**
- A) Manual `os.getenv` with custom validation — full control, no extra dependency
- B) `pydantic-settings` — automatic `.env` loading, type coercion, required-field validation

**Decision:** pydantic-settings (Option B)

**Reasoning:**
`pydantic-settings` handles `.env` file loading, type validation, and required-field enforcement automatically. A missing `GEMINI_API_KEY` crashes at startup with a clear error rather than surfacing as a 401 twenty minutes into a session. It's the FastAPI standard pattern — seen in virtually every production FastAPI codebase. The manual approach provides no meaningful advantage and requires writing validation logic that `pydantic-settings` already provides.

**Consequences:**
`src/core/config.py` defines a `Settings(BaseSettings)` class. Adding a new required environment variable means adding one typed field to the class. The `.env.example` template documents all required variables for setup.

---

## ADR-008: Settings Singleton Pattern
**Date:** June 2026
**Status:** Accepted

**Context:**
Multiple modules need access to settings (API keys, config values). The question was whether each module instantiates its own `Settings()` or whether a single shared instance is used.

**Options considered:**
- A) Direct instantiation — each module calls `Settings()` at import time
- B) `lru_cache`-wrapped `get_settings()` function — single instance, overridable in tests

**Decision:** `lru_cache` pattern (Option B)

**Reasoning:**
Direct instantiation re-reads the `.env` file on every import and makes testing difficult — you can't override settings for tests without monkeypatching. The `lru_cache` pattern is FastAPI convention: `get_settings()` is called as a dependency, and tests override it via `app.dependency_overrides[get_settings]`. This is critical because tests must never hit real LLM APIs (which would burn free tier quota). The mock-the-LLM-layer requirement only works cleanly if settings are injectable.

**Consequences:**
One `Settings` instance for the entire application lifetime. Tests can inject fake API keys without touching real providers. Every module that needs settings calls `get_settings()`, never instantiates `Settings()` directly.

---

## ADR-009: Agent Router Design
**Date:** June 2026
**Status:** Accepted

**Context:**
When a student sends a message, the system must decide which agent responds — patient, nurse, or family member. Two approaches were considered with meaningfully different cost implications given free tier rate limits.

**Options considered:**
- A) LLM-based routing — send each message to an LLM classifier to decide which agent responds
- B) Explicit UI addressing with LLM fallback — student selects or addresses an agent directly; LLM only used for genuinely ambiguous messages

**Decision:** Explicit UI addressing with LLM fallback (Option B)

**Reasoning:**
On a 15 RPM free tier, Option A costs an extra LLM call per turn — roughly halving conversation throughput. Most medical interview messages are naturally directed anyway ("Nurse, what are his vitals?", "Can you tell me more about the pain?"). Explicit addressing costs nothing computationally and is pedagogically reasonable — medical students do direct their questions in real clinical encounters. LLM fallback handles edge cases without penalizing every turn.

**Consequences:**
The UI provides a way for students to address agents explicitly (dropdown or prefix convention). `src/agents/router.py` first checks for explicit addressing, then falls back to LLM classification only when the target is ambiguous. Router logic is lightweight for the common case.

---

## ADR-010: Node Revelation Mechanism
**Date:** June 2026
**Status:** Accepted

**Context:**
When an agent responds, the system needs to know which patient state graph nodes were revealed in that response — to mark them as revealed and update the graph. The question was how to detect what was revealed.

**Options considered:**
- A) Post-hoc text matching — scan the response text for keywords after the fact
- B) Structured agent output — agents return JSON with `response_text`, `revealed_nodes[]`, and `emotional_state`

**Decision:** Structured agent output (Option B)

**Reasoning:**
Text matching is fragile — "I used to have a cigarette habit" won't match a `smoking` keyword. The agent itself knows what it revealed because it was instructed to reveal it. Having the agent declare its own output in structured JSON is reliable, explicit, and gives `emotional_state` tracking for free. The tradeoff is that all agent prompts must request JSON output — but this is an architecture-level constraint that's better decided now than retrofitted later.

**Consequences:**
Every agent returns a structured response: `{"response_text": "...", "revealed_nodes": [...], "emotional_state": "..."}`. All agent prompts in `src/agents/` are written to produce this format. The memory manager reads `revealed_nodes` to update the state graph after each turn. Emotional state is available for the conversation arc and final evaluation.

---

## ADR-011: Rubric Design Philosophy
**Date:** June 2026
**Status:** Accepted

**Context:**
The evaluation rubric (checklist of what a good student should cover) is defined in static scenario JSON files. But the patient is generated dynamically per session by an LLM. A conflict arises: what if the generated patient's history doesn't match a rubric item (e.g., rubric says "ask about smoking" but the patient is a non-smoker)?

**Options considered:**
- A) Content-based rubric — rubric items only apply if the patient's generated profile satisfies the precondition
- B) Process-based rubric — rubric rewards asking the question regardless of the patient's actual answer

**Decision:** Process-based rubric (Option B)

**Reasoning:**
Option A requires the scenario generator to guarantee every rubric precondition is satisfied in the generated patient — hard to enforce reliably with an LLM. Option B is simpler and more pedagogically defensible: a good clinician asks about smoking history with every cardiac patient, regardless of whether they suspect it. The rubric teaches *what questions to ask*, not *what answers to find*. This separates the evaluation concern from the generation concern cleanly.

**Consequences:**
Scenario JSON files define process-based rubric items ("asked about smoking history", "asked about family cardiac history"). The judge LLM evaluates whether the student asked — not whether the patient confirmed. The scenario generator has no obligation to satisfy rubric preconditions in the generated patient profile.

---

## ADR-012: Fallback Trigger Conditions
**Date:** June 2026
**Status:** Accepted

**Context:**
Groq/Llama is the fallback provider when Gemini fails. The spec named Groq as fallback but didn't define when fallback triggers. This needed to be decided before writing `client.py`.

**Options considered:**
- A) Fallback only after all retries exhausted — always attempt full backoff before switching
- B) Immediate fallback on 5xx, backoff-then-fallback on 429 — distinguish error types
- C) No automatic fallback — log the error and surface it to the user

**Decision:** Hybrid (Option B) — immediate fallback on 5xx server errors, fallback after backoff exhausts on 429 rate limit errors

**Reasoning:**
A 5xx error means the provider is down — retrying the same provider is pointless, switch immediately. A 429 rate limit error is transient — brief backoff may resolve it without needing the fallback. Exhausting backoff (1s, 2s, 4s, 8s = ~15 seconds) before switching is acceptable UX for a learning tool. Option C degrades the user experience unnecessarily when a working fallback exists.

**Consequences:**
`src/llm/retry.py` implements exponential backoff for 429s. `src/llm/client.py` checks error type: 5xx triggers immediate fallback, 429 triggers retry → fallback. The fallback provider/model is defined per-agent in `AGENT_CONFIG` as an optional field. If no fallback is configured for an agent and all retries fail, the error is raised and handled by the API layer.

---

## ADR-013: RAG Corpus Strategy
**Date:** June 2026
**Status:** Accepted

**Context:**
The RAG pipeline needs a corpus of clinical cases to embed and retrieve from. The question was where this corpus comes from initially.

**Options considered:**
- A) Synthetic corpus only — generate cases with Claude, use throughout the project
- B) Real clinical cases only — source from USMLE banks, Open Clinical, MedQA dataset
- C) Hybrid — start synthetic, add real cases after the pipeline is validated

**Decision:** Start synthetic, add real cases post-MVP (Option C, phased)

**Reasoning:**
Building the RAG pipeline (embedder, retriever, ChromaDB ingestion) should happen before data sourcing work. Validating that retrieval works correctly is easier with synthetic cases you control. Adding real cases later doesn't require changing the pipeline — just adding documents to the corpus. Real data work is time-consuming and shouldn't block learning the AI engineering patterns. The synthetic corpus is honest about its nature in the codebase (clearly labeled as synthetic).

**Consequences:**
`src/rag/corpus/` initially contains synthetic clinical case text files generated for this project. The pipeline is designed to ingest any text file in that directory. Adding real cases post-MVP means dropping files into that folder and re-running the ingestion script — no code changes required.

---

## ADR-014: Database Session Lifecycle & Injection
**Date:** June 2026
**Status:** Accepted

**Context:**
When a request arrives, something must create a SQLAlchemy session (the unit-of-work that batches reads/writes into one transaction), decide how long it lives, and hand it to `crud.py`. The choice shapes every CRUD function signature, every route, and the test strategy.

**Options considered:**
- A) Each CRUD function opens, commits, and closes its own session internally
- B) Session-per-request: created at the start of a request via a FastAPI dependency, passed into CRUD functions as a parameter, committed once at the end
- C) One global, long-lived session shared across the whole app

**Decision:** Session-per-request, injected as a dependency (Option B)

**Reasoning:**
Option A reads cleanly at the call site but makes every CRUD call its own transaction — so multi-step operations ("add a turn AND mark nodes revealed") can't be made atomic. Option C is a known anti-pattern: sessions are not task-safe and accumulate state, causing cross-request data bleed under concurrency. Option B is the FastAPI-standard unit-of-work: `get_db` yields a session and guarantees cleanup, routes declare `Depends(get_db)`, and CRUD functions take `db` as their first argument. It is the only option that gives atomic multi-step operations, and it makes the layer testable — tests override the dependency to point at an in-memory SQLite database (a real-but-disposable DB, no mocks). This pairs with the `lru_cache`/`dependency_overrides` pattern from ADR-008.

**Consequences:**
`src/db/session.py` exposes an async-generator `get_db` dependency that yields a session, commits on success, and rolls back on exception. Every `crud.py` function takes an `AsyncSession` as its first parameter and `flush`es (to assign primary keys) rather than committing — the transaction boundary is owned by the request. Tests use an in-memory engine with `StaticPool` (one shared connection so the schema survives across operations). SQLite's single-writer limitation is irrelevant here because one student drives one session at a time.

---

## ADR-015: JSON Column Storage Strategy
**Date:** June 2026
**Status:** Accepted

**Context:**
Several columns hold structured data as JSON: `patient_profile_json`, `state_snapshot_json` (the serialized NetworkX graph), `revealed_nodes_json`, and the evaluation's `rubric_items_json` / `covered_items_json` / `missed_items_json`. The question is how the ORM models type these columns.

**Options considered:**
- A) Raw `TEXT` columns; callers do `json.dumps()` on write and `json.loads()` on read
- B) SQLAlchemy's `JSON` column type; assign a Python dict/list, read one back, serialization handled by the column

**Decision:** SQLAlchemy `JSON` columns (Option B)

**Reasoning:**
Option A scatters `json.dumps`/`json.loads` across the codebase — every one a place to forget a conversion, store a Python `repr` instead of valid JSON, or double-encode a string. Option B centralizes serialization in the column definition: assign a dict, get a dict. Fewer bugs, cleaner reads, and consistent with the project-wide "typed structured data, not stringly-typed" instinct (same reasoning as choosing typed `AgentLLMConfig` over dicts in ADR-006). Under SQLite the data is stored as text either way, so this honors the spec's `TEXT` intent at the storage level while giving a better Python interface.

**Consequences:**
Models declare these columns as `JSON`. CRUD functions accept and return Python dicts/lists. The boundary stays crisp: serializing the NetworkX graph to a dict is the state layer's job (`state/serializer.py`); the db layer just persists whatever dict it is handed — it never knows about graphs.

---

## ADR-016: Schema Management — create_all now, Alembic deferred
**Date:** June 2026
**Status:** Accepted (temporary — see trigger below)

**Context:**
Tables must exist before any write. There are two ways to make that happen, and they differ in how they handle *changes* to the schema over time.

**Options considered:**
- A) `Base.metadata.create_all` — on startup, create any missing tables from the models
- B) Alembic migrations — versioned, reversible schema-change scripts from day one

**Decision:** `create_all` now; Alembic deferred to post-MVP (Option A, temporarily)

**Reasoning:**
`create_all` is one line and perfect while the schema is still moving and there is no precious data — but it only *creates missing tables*; it will not alter an existing one, so adding a column later silently does nothing. Alembic handles exactly that, but it is real overhead (a migrations directory, an autogenerate-and-review workflow per change) aimed at a problem we do not yet have: evolving a live database with data we cannot drop. Deferring is correct, but this is the one deferral with a sharp edge, so the trigger to switch is named explicitly.

**Consequences:**
`src/db/session.py` provides `init_db()` calling `create_all`. During development, a schema change means deleting the dev `.db` file and letting `create_all` rebuild it. **Trigger to adopt Alembic:** the first time we must change a table that already holds data we care about. Pairs with ADR-004 (database strategy).

---

## ADR-017: Scenario Node Schema — Strict Core + Open Metadata Bag
**Date:** June 2026
**Status:** Accepted

**Context:**
Each patient fact is a node. The schema (`scenarios/schema.py`) validates every scenario — hand-authored now, LLM-generated in Phase 3 — before it becomes a graph. The question was *which* fields are fixed and validated, and whether a node may carry situation-specific fields that the schema doesn't know about (a cardiac case's troponin, a neuro case's GCS).

**Options considered:**
- A) Fully fixed schema (`extra="forbid"`) — every node has exactly the known fields; a neuro case's `gcs_score` is rejected
- B) Fully open schema (`extra="allow"`) — accept any field; a typo like `importnce` is silently kept
- C) Hybrid — a strict, validated core set plus a single free-form `metadata` dict for per-scenario extras

**Decision:** Hybrid (Option C). Core fields = `id`, `label`, `category`, `revealed` (default `False`), `importance` (default `relevant`); optional `detail` and `disclosure_difficulty`; plus an open `metadata: dict`. Core is `extra="forbid"`.

**Reasoning:**
Option A forces a schema change for every new specialty — directly fighting the goal of LLM-generated multi-specialty scenarios. Option B loses all guarantees: a typo in a core field name surfaces as a silent missing value mid-session. The hybrid keeps the fields the *system* depends on (router, graph summary, rubric) strict so typos fail at load, while the `metadata` bag lets each scenario carry domain-specific data with no schema change. The discipline that keeps this safe: **core logic only reads core fields; `metadata` is for display, LLM context, and agent flavour — never for control flow.** `importance` is carried now (its consumer, the process-based rubric, lands in Phase 7) because it is cheap authored data with a certain future reader. `disclosure_difficulty` lets a scenario mark sensitive facts (substance use, non-adherence) as hard to extract — the realism lever the patient agent will honour in Phase 4.

**Consequences:**
`ScenarioNode` forbids unknown top-level fields; per-scenario richness goes inside `metadata`. `Scenario` enforces structural integrity once — unique node ids and no dangling edges (an edge naming a node that doesn't exist) — so the builder and every later traversal can assume a sound graph. Adding a new specialty scenario in Phase 8 is a JSON file, not a schema edit. Pairs with ADR-003 (state representation) and ADR-006 (typed-over-stringly-typed instinct).

---

## ADR-018: State Graph Edges — Undirected Associations, Not Reveal Gates
**Date:** June 2026
**Status:** Accepted

**Context:**
Nodes are clearly "one clinical fact each." The load-bearing question was what an *edge* means, and which NetworkX graph class backs it. Edges shape whether graph structure drives behaviour or is mere decoration.

**Options considered (edge meaning):**
- A) Clinical associations — an edge means "these facts are related" (chest pain ↔ radiates-to-arm; smoking ↔ cardiac risk)
- B) Reveal gates — an edge means "B cannot be revealed until A is" (prerequisite ordering)
- C) Grouping only — edges just connect a category to its detail nodes

**Options considered (graph class):**
- `Graph` (undirected, one edge per pair) vs `MultiGraph` (undirected, parallel edges allowed) vs the directed variants

**Decision:** Edges are clinical associations (Option A) on an undirected `networkx.Graph`. Relationship *type* is an edge attribute `relation`, which may be a string or a list of strings when a pair is related in more than one way.

**Reasoning:**
The spec's bet (ADR-003) is that behaviour emerges from graph structure, which argues for *meaningful* edges between facts — not Option C's near-dict. Option B (gating) was rejected because reveal control already lives with the agent via structured output (ADR-010); a second gating mechanism here would be a conflicting source of truth. Associations are mutual, so an undirected `Graph` is the honest choice. `MultiGraph` was rejected: genuinely parallel relationships between the same pair are rare at our granularity, and a single `relation` attribute (a list when needed) captures multiplicity without making every traversal loop over edge-keys. If a real need for parallel edges ever appears, `Graph → MultiGraph` is a one-line builder change.

**Consequences:**
`src/state/graph.py` exposes `neighbors(node_id)` so the memory layer can surface "related but still hidden" facts as follow-up hints without imposing an order. Edges carry `relation`; nothing in the system gates reveals on graph structure. The payoff: uncovering `chest_pain` can hint at its still-hidden neighbours (`radiation`, `dyspnea`) for context, while the agent stays in charge of what is actually revealed.

---

## ADR-019: State Graph Serialization — NetworkX Node-Link Format
**Date:** June 2026
**Status:** Accepted

**Context:**
At session end the final graph is snapshotted into the `state_snapshot_json` SQLite column. Something must flatten the live NetworkX graph to a JSON-safe dict and rebuild it losslessly. The round-trip — revealed flags, metadata, and edge relations all preserved — is the whole contract.

**Options considered:**
- A) NetworkX's built-in `node_link_data` / `node_link_graph` helpers
- B) A hand-rolled serializer with our own dict shape

**Decision:** NetworkX node-link format (Option A), behind the `serializer.py` seam.

**Reasoning:**
The built-in helpers are battle-tested and round-trip node/edge attributes for free; the snapshot is an internal artifact, so a pretty custom shape buys nothing. Keeping it behind `serialize` / `deserialize` means callers never see which format we chose — we can change the internals later without touching the db or state layers. The one sharp edge: the `edges=` keyword's default changed across NetworkX versions and the unpinned call emits a `FutureWarning`, so both directions pin `edges="edges"` to keep runtime and test output pristine. A round-trip test (`deserialize(serialize(g))` equals the original) is the executable spec.

**Consequences:**
`src/state/serializer.py` exposes `serialize(graph) -> dict` and `deserialize(dict) -> PatientStateGraph`. The db layer just persists the dict it is handed and never knows about graphs (ADR-015). Pairs with ADR-003.

---

## ADR-020: RAG Embeddings — Local ONNX MiniLM Behind an Embedder Seam
**Date:** June 2026
**Status:** Accepted

**Context:**
Retrieval needs text turned into vectors (embeddings). Two questions: *where* do embeddings come from, and *who owns* the call. The corpus is small and the project must stay free and offline-friendly (no quota burned in tests).

**Options considered (source):**
- A) Local `sentence-transformers` (`all-MiniLM-L6-v2`, PyTorch runtime)
- B) A hosted embedding API (Gemini/OpenAI)
- C) The same `all-MiniLM-L6-v2` model in its ONNX-quantized form, which ChromaDB bundles

**Options considered (ownership):**
- Explicit `src/rag/embedder.py` seam that produces vectors, vs letting ChromaDB embed internally via its default embedding function

**Decision:** Local MiniLM via ChromaDB's ONNX runtime (Option C), wrapped behind an explicit `Embedder` (`src/rag/embedder.py`). Vectors are passed to Chroma explicitly at add and query time.

**Reasoning:**
A local model is free, offline, and deterministic, so embeddings cost no quota and tests can assert on *real* vectors (similar meaning → closer vectors) instead of mocks. Choosing the ONNX build over `sentence-transformers` keeps the same model family while avoiding a ~1 GB PyTorch install — and `pyproject.toml`'s stated goal is fast installs. The explicit seam mirrors how `llm/client.py` owns provider calls and `core/config.py` owns model choice: model selection lives in exactly one module, so swapping to `sentence-transformers` (or an API) later is a one-file change. Letting Chroma embed internally would hide the model in DB config and make "does similar text embed near similar text" hard to unit-test.

**Consequences:**
`Embedder.embed(text)` / `embed_batch(texts)` return plain `list[float]` (numpy types never leak past the seam). The model file (~80 MB) downloads once to `~/.cache/chroma` and is offline thereafter. The retriever depends on the embedder, not on any provider. Pairs with ADR-005 (provider-agnostic seam instinct).

---

## ADR-021: RAG Retrieval — Whole-Case Documents, Semantic Search + Metadata Filter
**Date:** June 2026
**Status:** Accepted

**Context:**
The retriever stores the synthetic corpus and, at generation time, returns the few cases most relevant to a request. Two design axes had to be settled: how to *chunk* each case, and what *retrieval strategy* to use.

**Options considered (chunking):**
- A) Whole case = one document = one embedding
- B) Fixed-size chunks (split each case into smaller pieces)
- C) Hierarchical (parent/child) chunking

**Options considered (retrieval):**
- Dense semantic (vector) search; sparse lexical (BM25); hybrid (score-fused dense + sparse)

**Decision:** One case = one document, no chunking. Dense semantic retrieval with a **category metadata pre-filter**, top-`k`=3. The filename prefix (`chest_pain_01` → `chest_pain`) is the source of truth for category; the `# SYNTHETIC CASE` provenance header is stripped before embedding.

**Reasoning:**
The generator needs *whole, coherent* cases as inspiration — a fragment (just the risk-factors paragraph) is useless to it, and our cases are short enough that there is no token-limit pressure forcing a split. Hierarchical chunking solves a precision-vs-context problem we don't have (the case is already both the precise unit and the full context). On retrieval: the corpus is tiny and the task is meaning-driven ("a case like this presentation"), which is dense search's home turf; lexical recall only starts mattering at much larger scale. ChromaDB also has no native score-fused hybrid, so hybrid would mean hand-rolling BM25 + fusion for no benefit. The high-value lever is the metadata filter: storing the category as metadata lets a `where` clause *hard-guarantee* a cardiac request never returns a respiratory case — something neither plain semantic nor hybrid ranking guarantees. Stripping the shared header avoids adding identical noise to every vector.

**Consequences:**
`Retriever.ingest_corpus(dir)` (idempotent via `upsert`) and `query(text, category, k)` returning typed `RetrievedCase` objects. The Chroma collection is injected, so tests use an in-memory (ephemeral) collection and the app uses a persistent on-disk one (`chroma_data/`, gitignored) — embed-once, survive restarts. The filename naming scheme is now load-bearing, not cosmetic. Pairs with ADR-013 (synthetic corpus) and ADR-020.

---

## ADR-022: Scenario Generation — Synthesize From Top-k, Validate-and-Repair Against the Schema
**Date:** June 2026
**Status:** Accepted

**Context:**
The generator is the top of the RAG layer and the one piece that calls an LLM. An LLM returns free text, but the system needs a schema-valid `Scenario`. Two questions: how should retrieved cases be *used*, and how do we *guarantee* valid output given that models sometimes emit malformed or schema-violating JSON.

**Options considered (grounding):**
- A) Retrieve one case and reformat it into the schema (a converter)
- B) Retrieve top-k (≈3) cases as *inspiration* and synthesize a new patient blending them

**Options considered (validity):**
- C) Generate once; if it fails validation, fail the request
- D) Validate against `scenarios/schema.py`; on failure, feed the exact error back and re-prompt, up to a small retry cap

**Decision:** Synthesize a new patient from the top-3 retrieved cases (Option B) and use a validate-and-repair loop (Option D, `max_repairs`=2 by default). Parsing tolerates markdown fences / surrounding prose (first `{` … last `}`). The LLM call is injected (`complete_fn`, defaulting to `llm.client.complete`). On exhausting repairs, raise `ScenarioGenerationError`.

**Reasoning:**
Reformatting one case (Option A) would make every cardiac session essentially the same patient — defeating the reason RAG exists over simply authoring more JSON files; synthesis from several cases yields variety (varied age, severity, emotional context). Single-shot failure (Option C) is fragile UX: one bad field aborts session start. The repair loop turns the Phase 2 schema into a *self-correction signal* — its error messages already name the offending field or dangling id (`edge references nonexistent node id: 'foo'`), which is precisely the instruction the model needs to fix it. The cost (a couple of extra LLM calls) is paid only when something is wrong. Injecting `complete_fn` keeps the whole loop testable with canned responses and no real provider call — the same no-quota rule the rest of the suite follows.

**Consequences:**
`ScenarioGenerator(retriever, complete_fn, k, max_repairs)` with `generate(ScenarioRequest)` returning a schema-valid `Scenario` that is guaranteed to build via `src/state/builder.py`. `scenario_generator` routes through `AGENT_CONFIG` (Gemini `gemini-3.1-flash-lite`), so the first *real* provider call in the system happens here when run outside tests. `ScenarioRequest.category` must match a corpus specialty since it drives the retrieval filter. Pairs with ADR-010 (structured output instinct), ADR-012 (fallback), and ADR-017 (the schema being repaired against).

---

## ADR-023: Agent Base — Template-Method Pipeline, Prompt-Enforced Disclosure, Injected Context
**Date:** June 2026
**Status:** Accepted

**Context:**
The patient, nurse, and family agents all do the same four things: assemble a prompt, call the LLM, parse the reply into the structured `AgentResponse` (ADR-010), and return it. They differ only in persona and which slice of the patient's truth they see. We had to decide how much machinery to share, how the patient honours `disclosure_difficulty` (ADR-017), and where conversation context comes from while the memory layer (Phase 5) does not yet exist.

**Options considered:**
- A) Three standalone agents, each with its own call/parse logic
- B) A thin base with shared helpers, personas mostly independent
- C) A template-method `BaseAgent` owning the whole pipeline, with persona as the only required hook
- Disclosure: prompt-only vs a code "trust counter" gate
- Context: injected as a parameter vs agents reading history/DB themselves

**Decision:** Template-method `BaseAgent` (Option C); disclosure is **prompt-only**; context is an **injected parameter**.

**Reasoning:**
The agents share their entire control flow, so a template method puts the fragile JSON parse/validate/repair loop (reused from the Phase 3 generator) in exactly one place; each persona becomes a short declaration. Disclosure stays prompt-only because reveal control already lives with the agent via structured output (ADR-010/ADR-018); a second code gate would be a conflicting source of truth and make the patient feel robotic. Context is injected so agents stay pure functions and the memory layer (Phase 5) drops in later with zero agent changes — mirroring how `complete_fn` is injected into the generator. The LLM call is injected too, so every agent test runs with a fake and no real provider call.

**Consequences:**
`src/agents/base.py` exposes `BaseAgent.respond(message, context) -> AgentResponse` and an `AgentResponse` model (`response_text`, `revealed_nodes`, `emotional_state`). Agents never write to the graph — they *report* `revealed_nodes` and the caller applies `mark_revealed` (whose guard drops hallucinated ids). Each persona prompt also forbids accepting false premises in a leading question, a clinical-skills *validity* fix applied to all three agents. Pairs with ADR-010, ADR-017, ADR-018.

---

## ADR-024: Per-Agent Knowledge Slicing
**Date:** June 2026
**Status:** Accepted

**Context:**
All three agents read the same `PatientStateGraph`, but a realistic encounter requires each to know different things. If every agent sees everything, the nurse could recite the patient's secret shame and the family could read off lab values — destroying both realism and the reason multiple agents exist.

**Options considered:**
- A) All agents see the full graph; persona prompt alone keeps them in lane
- B) Each agent gets a filtered slice of the graph matching what that character would know

**Decision:** Per-agent knowledge slice (Option B).

**Reasoning:**
A filter enforces the boundary structurally, not just by hope. The patient sees everything (including its own secrets, so it can guard them). The nurse sees only *documented* facts — vitals/exam in `metadata`, current medications, documented history and observations — and explicitly **not** hidden or undisclosed personal facts. The family sees the social/emotional/family-history layer plus observed behaviour, and explicitly **excludes `hidden` nodes**, so a relative never leaks the patient's secrets. The three lanes (patient guards & is vague; nurse is precise & defers personal to the patient; family volunteers the lived layer & defers clinical to staff) push the student to the right source for each kind of question.

**Consequences:**
The context the caller assembles per agent (Phase 5) is the enforcement point; the personas describe the boundary in words as a second layer. The "collateral history exposes what the patient conceals" dynamic (a relative revealing a guarded fact) is deliberately deferred — it needs a schema flag (e.g. `metadata.known_to_family`) and is a Phase 8 item with its own ADR. Pairs with ADR-023.

---

## ADR-025: Router — Explicit Addressing, Default-to-Patient, Resolve-Only, Injected Classifier
**Date:** June 2026
**Status:** Accepted (refines ADR-009)

**Context:**
ADR-009 settled the routing *strategy* (explicit addressing, LLM only for ambiguous messages). Implementing it raised concrete questions: when exactly does the LLM classifier fire, does the router dispatch or just decide, and how is a classifier reply parsed safely.

**Options considered:**
- When to classify: every unaddressed message vs only when explicitly asked
- Router shape: a `BaseAgent` subclass vs a plain resolve-only class vs a dispatching class
- Classifier output: free text vs a strict single word

**Decision:** Explicit target wins; an unaddressed message **defaults to the patient**; the classifier fires **only on an explicit `AUTO` request**. The router is a **resolve-only** plain class. The classifier returns **one word**, parsed defensively.

**Reasoning:**
Classifying every unaddressed turn would reintroduce the per-turn LLM cost ADR-009 exists to avoid; since the UI dropdown defaults to the patient, "unaddressed" almost always means "still talking to the patient," so defaulting there keeps the common path at zero LLM calls. The router can't be a `BaseAgent` subclass — the classifier yields a *label*, not an `AgentResponse` — and resolve-only keeps it single-responsibility and testable without constructing real agents. The classifier prompt names the about-vs-to trap ("Did the nurse check his BP?" is asked *of the patient*) and defaults ambiguity to the patient; the reply is lowercased, stripped to words, matched against the three targets (non-default first), and falls back to the patient on anything unrecognised, so a chatty model can't break routing.

**Consequences:**
`src/agents/router.py` exposes `Router(patient, nurse, family, complete_fn).resolve(message, addressed_to) -> BaseAgent` and an `AUTO` sentinel. A `router` entry was added to `AGENT_CONFIG` (Gemini `gemini-2.5-flash-lite`, the cheapest fast model, rarely called). Prefix-keyword parsing ("Nurse, …") is intentionally omitted for now — a substring match is too fragile — leaving the explicit UI signal as the source of truth. Pairs with ADR-009.

---

*New decisions will be added here as the project is built.*
*Each entry should take ~5 minutes to write. Date it, describe the context, log the options you considered, and record why you chose what you chose.*
