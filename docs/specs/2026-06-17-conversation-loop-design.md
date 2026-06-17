# Phase 6 — Full Conversation Loop (Design)

**Date:** 2026-06-17
**Status:** Approved — ready to build (TDD)
**Scope:** Wire the isolated, unit-tested components (router, memory, agents, state, db,
RAG generator) into a working per-turn loop, exposed over a thin FastAPI layer and
driven by a Streamlit UI. This is where the **first real agent→LLM call** happens.

This phase is almost purely *additive*: new code in `src/conversation/`, `src/api/`,
`frontend/`, plus one smoke script. **No reviewed module is edited** — agents, memory,
state, llm, db, and rag are consumed exactly as they are.

---

## Decisions (drawn out in design dialogue)

| # | Decision | Rationale | ADR |
|---|----------|-----------|-----|
| D1 | Orchestration lives in a dedicated `src/conversation/` module (`start_session`, `run_turn`), collaborators injected; routes stay thin. | Honors CLAUDE.md "routes are thin, business logic in core modules"; matches every other layer (pure + injected + unit-testable without HTTP). | ADR-029 |
| D2 | State graph is **rebuilt from the turns** each turn (event sourcing), not cached or snapshotted mid-session. | The DB is the single source of truth; the persisted turns are the event log and the graph is a projection. Zero new storage, no derived-state drift, restart-safe, naturally stateless. | ADR-030 |
| D3 | Addressing is an **explicit** UI choice (Patient / Nurse / Family, default Patient). The UI never sends `AUTO`; the classifier stays built + unit-tested but unused by the UI. | Product clarity over feature-showcasing: the student only cares that the right person answers. Honors ADR-025 (common path free). | ADR-031 |
| D4 | FastAPI `lifespan` builds the expensive singletons once (Retriever+corpus, agents, Router, generator) onto `app.state`; `Depends` providers hand them to routes; tests use `dependency_overrides` to inject fakes. Corpus is ingested into **persistent** ChromaDB at startup (idempotent). | One construction, no per-request cost; the override seam keeps the suite network-free. | ADR-029 |
| D5 | The risky LLM call happens **before any write**. On failure (provider down post-fallback, or `AgentResponseError`) the route returns `503` + a friendly `detail` and **persists nothing** → the student retries with their text intact. | "Never let a provider error crash a session" (CLAUDE.md). Writes-after-success means a failed turn leaves zero partial state to pollute the thread / Phase-7 transcript. | ADR-029 |
| D6 | Phase 6 = **create a session + have a full conversation**. The end-session affordance is **deferred to Phase 7**, where `POST /evaluate` ends the session and runs the judge in one action. | Avoids shipping an end-without-eval stub we would immediately rework. | — |

---

## Components

| Module | Responsibility |
|--------|----------------|
| `src/conversation/orchestrator.py` | `start_session(...)`, `run_turn(...)` — the pure injected loop; the only place that knows the order of operations. |
| `src/api/main.py` | FastAPI app + `lifespan` building the singletons onto `app.state`. |
| `src/api/deps.py` | `Depends` providers for the singletons + `get_db` — the single override seam for tests. |
| `src/api/routes/sessions.py` | `POST /sessions`, `GET /sessions/{id}` (thin). |
| `src/api/routes/conversation.py` | `POST /sessions/{id}/turns` (thin). |
| `src/api/schemas.py` | Request/response Pydantic models. |
| `frontend/app.py` | Streamlit: scenario picker → create → intro → addressing dropdown + message box → client-side transcript. HTTP only, never imports `src/`. |
| `scripts/smoke_conversation.py` | Hand-run live test (NOT in the pytest suite): real `start_session` + a couple of real `run_turn`s against a throwaway SQLite. First live agent→Gemini call. |

## Orchestrator signatures

```python
async def start_session(db, generator, scenario_type: str) -> tuple[SimulationSession, Scenario]:
    # generator.generate(ScenarioRequest(category=scenario_type))
    # → create_session(db, scenario_id, scenario_name, patient_profile=scenario.model_dump())
    # → return (session, scenario)   # the FULL scenario is stored so the graph can be rebuilt

async def run_turn(db, build_router, session_id, content, addressed_to) -> TurnResult:
    # 1 load session + turns; parse scenario; rebuild graph: build_graph(scenario),
    #   then replay graph.mark_revealed over every turn's revealed_nodes_json;
    #   read current trust = last patient turn's trust_level, else TRUST_BASELINE
    # 2 router = build_router(scenario.patient_name)  # patient agent needs the name
    #   agent = await router.resolve(content, addressed_to); name = agent.agent_name
    # 3 history = [HistoryTurn(speaker, content, addressed_to) for each turn]
    #   context = manager.build_context(name, graph, history, trust if name=="patient" else None)
    # 4 resp = await agent.respond(content, context)         # risky LLM call, FIRST
    # 5 graph.mark_revealed(resp.revealed_nodes)
    #   if name == "patient": trust = apply_rapport_delta(trust, resp.rapport_delta)
    # 6 add_turn(student, content, addressed_to=name)        # store RESOLVED name (ADR-026)
    #   add_turn(name, resp.response_text, revealed_nodes=resp.revealed_nodes,
    #            trust_level=trust if name=="patient" else None)
    # 7 return TurnResult(speaker=name, content=resp.response_text,
    #                     emotional_state=resp.emotional_state)
```

`TurnResult` is a small internal value type; the route maps it to `TurnResponse`.

## API contract (matches spec §API Design)

```
POST /sessions            {scenario_type}            → {session_id, scenario_intro, patient_name}
GET  /sessions/{id}                                  → {session_id, scenario_intro, patient_name, status}
POST /sessions/{id}/turns {content, addressed_to?}   → {speaker, content, emotional_state}
```

`revealed_nodes` is **never** in the turn response — the student must not see what they did
or did not surface. It is internal state only.

## Error handling

Provider failure (after backoff+fallback) and `AgentResponseError` both raise out of step 4,
before any write. The route catches and returns `503` with a friendly `detail`; `get_db` rolls
back (nothing to roll back). Streamlit shows an inline "… didn't respond — please try again"
and keeps the typed message. Generation failure at `POST /sessions` is handled the same way.

## Testing

- **Orchestrator** (thorough, no network, in-memory SQLite like the crud tests): reveals replay
  across turns; trust read-back + clamp; `addressed_to` stores the resolved name; patient vs
  non-patient trust handling; no-partial-write on agent failure.
- **Routes** (thin, `TestClient` + `dependency_overrides`): one happy path per endpoint + one
  `503` shape.
- **Zero real LLM calls** in the suite. The live path is proven only by the hand-run
  `scripts/smoke_conversation.py`.

## Cross-layer touchpoints (consumed, not edited)

`build_graph` + `Scenario.model_validate` (rebuild) · `graph.mark_revealed` · `manager.build_context`
+ `HistoryTurn` + `apply_rapport_delta` · `Router.resolve` · `agent.respond` · `crud.create_session`
/ `add_turn` / `get_session` / `get_turns`. The `serializer` is **not** needed mid-session
(rebuild-from-turns supersedes it); it remains for the Phase-7 end-of-session snapshot.

## What earlier decisions constrain here

- Agents are resolve-only + report-don't-write (ADR-009/023) → the orchestrator calls
  `mark_revealed` and `apply_rapport_delta`, not the agent.
- Memory takes typed injected inputs (ADR-026) → orchestrator maps `ConversationTurn` → `HistoryTurn`.
- Router defaults unaddressed→patient free, classifies only on `AUTO` (ADR-025) → with explicit
  UI addressing, `AUTO` is never sent in the app.
- Trust persisted per patient turn (ADR-027) → "current trust" is read back from the last
  patient turn each turn.
```
