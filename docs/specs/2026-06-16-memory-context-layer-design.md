# Memory & Context Layer — Design Spec

**Date:** 2026-06-16
**Phase:** 5 (Memory & Context)
**Status:** Approved design, pre-implementation
**Related ADRs:** ADR-010 (structured agent output), ADR-014 (DB session lifecycle),
ADR-018 (graph = associations), ADR-023 (agent base / injected context),
ADR-024 (per-agent knowledge slicing), ADR-025 (router). New ADRs to be written
for the decisions below.

---

## 1. Purpose & scope

LLMs are stateless: each agent call is an independent request to a model that
remembers nothing. The memory layer's job is to **reconstruct, before every
call, the right slice of "what this character knows" + "what has been said to
it," render it into the `context` string the agent already accepts
([base.py](../../src/agents/base.py) `respond(message, context)`), and carry the
trust signal forward between turns.**

The layer is **pure and I/O-free**: it receives typed objects as arguments and
returns a string. It never opens a DB session and never calls an LLM. The
orchestrator (Phase 6) owns those boundaries.

**In scope (Phase 5):** `context_builder.py`, `manager.py`, a deferred
`summarizer.py` stub, plus the cross-layer prerequisites the layer depends on.
**Out of scope:** the conversation loop / orchestrator that wires this to the
router, the DB, and the frontend — that is Phase 6.

## 2. Constraints inherited from prior layers

- **ADR-023** fixed the agent's input contract: `context` is a **string**
  inserted between the persona (emitted by the agent) and the student message
  (emitted by the agent). The memory layer therefore owns only the *middle* of
  the prompt and must **not** re-emit the persona.
- **ADR-024** makes this layer the enforcement point for per-agent knowledge
  slicing (patient sees all; nurse documented-only; family social/emotional/
  family-history minus hidden).
- **ADR-010 / ADR-018**: the graph holds the full truth; agents *report*
  `revealed_nodes` and the caller applies `mark_revealed` (hallucination-safe).
  The memory layer *reads* revealed state; it never decides reveals.
- **ADR-014**: the transaction/session boundary belongs to the request layer, so
  core modules stay I/O-free and unit-testable. The memory layer follows that
  grain.
- The state graph already structurally captures *what has been revealed*, which
  is the single most important thing a conversation summary would otherwise
  recover (see D5).

## 3. Key decisions

### D1 — Inputs injected as typed objects (not fetched); context returned as a string
The context builder **receives** its inputs — the `PatientStateGraph`, the
conversation history, and the current `trust_level` — as plain typed arguments.
It does **not** import `crud` or take a DB session. "Injected" means *handed the
real objects*, not *flattened to strings*: the graph arrives with all its
methods, the history as typed turns, trust as an `int`. Rendering to a string
happens only inside the builder.

*Rationale:* mirrors how agents take an injected `complete_fn` so tests never hit
a provider — here memory takes injected data so tests never hit a DB. Keeps the
layer modular and unit-testable with zero infrastructure. History is injected as
a **lightweight value type** (`HistoryTurn`), not raw `ConversationTurn` ORM
rows, to avoid coupling memory to `db.models` and to dodge detached-session
pitfalls.

### D2 — Per-agent conversation threading
Each agent sees only the turns between **itself and the student**, never turns
directed at other agents.

*Rationale (decisive):* a global transcript would leak the patient's spoken
disclosures (e.g. a hidden substance-use admission) into the nurse's/family's
context, blowing a hole through the ADR-024 slice on the *conversation* axis even
though it is blocked on the *knowledge* axis. Per-agent threading makes the two
axes agree. It is also more realistic (the nurse wasn't in the room), sufficient
for continuity (an agent only needs its own thread), and cheaper. Reconstructing
a thread requires knowing which student turns were addressed to which agent →
see the `addressed_to` change in §6.

### D3 — Per-agent slice: policy in memory, mechanism in the graph
The **slice policy** (the `agent → allowed categories + hidden rule` mapping that
encodes ADR-024) lives in the memory layer. The **mechanism** (filtering nodes by
category and revealed-state, and rendering a given subset) is a generic,
agent-agnostic accessor on `PatientStateGraph`.

*Rationale:* "what the nurse may see" is a *policy* owned by the agent-aware
layer; "what nodes are in category X" is a *data* question owned by the graph.
The graph must never learn the words "nurse"/"family" — that would break its
"depends on nothing of ours" property and force a graph edit for every new agent.
Future rules (e.g. the Phase 8 "collateral reveals a concealed fact") plug in as
a policy tweak in memory, not a data-structure change.

Illustrative policy (exact category mapping finalized at build time):

| agent   | categories visible                                       | hidden nodes |
|---------|----------------------------------------------------------|--------------|
| patient | all                                                      | yes          |
| nurse   | symptom, history, medication, family_history (+ vitals from metadata) | no |
| family  | social, emotional, family_history                        | no           |

### D4 — Trust model: rapport delta in the patient's output, gated against node difficulty, persisted per-turn
- **Two distinct variables.** `emotional_state` (how the patient *feels now*; for
  the arc + evaluation) is **not** the trust signal. Trust is a separate
  variable: the patient's *willingness to disclose sensitive facts*.
- **A persisted `trust_level`** (int, range 0–3, baseline 1) is carried forward
  across turns and only *nudged* each turn — never re-derived from scratch. This
  is ~5 tokens in the prompt (no history bloat) and consistent (it can't lurch).
- **The nudge is the patient's own `rapport_delta`** (−1 / 0 / +1), emitted as a
  field in the patient's existing JSON response (**Option C2** — no extra LLM
  call). Default is **0**: factual questions ("where is the pain?") move trust
  not at all; only emotionally-loaded interactions move it. Applied as
  `new_level = clamp(old_level + delta, 0, 3)`.
- **Disclosure gate.** Of the four `disclosure_difficulty` levels
  ([schema.py](../../scenarios/schema.py)), only `only_if_trust_built` is
  trust-gated: the patient discloses such a node when `trust_level` is high
  (= 3). `volunteered` / `if_asked` / `only_if_asked_directly` are governed by
  *question specificity*, which the persona handles directly. So trust carries
  only the top tier.
- **One-turn lag (accepted, even preferred).** Because the delta is computed in
  the same call that produces the reply, a turn's rapport boost takes effect on
  the *next* turn. This prevents a student front-loading empathy + the sensitive
  question in one breath, and is more realistic.
- **Persistence.** The resulting `trust_level` is written onto each **patient**
  `ConversationTurn` (next to `revealed_nodes_json`), giving the full trajectory
  for Phase 7 (rapport-building is a gradeable skill) and making "current" the
  last patient turn's value (recoverable on resume). Non-patient turns leave it
  null.
- **Reversible.** The persisted level, the gate, and the context line are
  identical whether the delta comes from the patient (C2) or a separate judge
  (C1). If the patient's self-reported delta proves unreliable in the live smoke
  test, the delta source can be lifted into a separate judge later, touching
  nothing else.

### D5 — Prose summarizer deferred
No running prose summary is injected for the MVP. `summarizer.py` is a preserved
stub.

*Rationale:* summarization solves a token-budget problem that does not exist at
this scale (a long 40-turn session is low thousands of tokens — a fraction of a
percent of the model's window). The two durable things a recap would preserve are
*already captured structurally*: **what's disclosed** (graph `[revealed]` flags
in the slice) and **the rapport arc** (`trust_level`). Continuity of disclosure
survives window-dropping because a node scrolled out of the recent window is still
shown as `[revealed]` in the slice. Add a real summarizer only if a live session
overflows or needs early *non-factual, non-rapport* recall (e.g. a reassurance the
student gave).

### D6 — Context shape
The assembled `context` string is composed of **labeled blocks** (not one prose
header — explicit per-section labels let the model distinguish persistent facts
from prior utterances from the current instruction, which is the real form of
that principle), in this order:

1. **State slice** — labeled (e.g. "WHAT YOU KNOW ABOUT YOURSELF",
   `[revealed]`/`[hidden]` marked), per the D3 policy. For nurse/family the label
   changes ("WHAT IS DOCUMENTED" / "WHAT YOU'VE OBSERVED").
2. **Rapport line** — *patient only*: "CURRENT RAPPORT WITH THIS STUDENT: n / 3".
   Only the *level* is injected here; the *rule* that gates disclosure stays in
   the persona's trust rubric.
3. **Recent turns** — the last **6 exchanges** of this agent's thread,
   chronological (oldest → newest), each line `you:`/`student:` (the agent's own
   turns render as "you").

Ordering rationale: stable facts at the high-attention start, the volatile recent
turns + the live question at the high-attention end, nothing important stranded
in the "lost-in-the-middle." `N = 6` exchanges chosen because clinical
history-taking runs in chains (location → radiation → character → severity →
timing → aggravating) up to ~5 questions deep; 6 keeps a whole chain plus its
pivot visible. Cost is not the constraint, so `N` is a tunable config constant.

The current student message is **excluded** from the recent-turns block (the agent
emits it separately) so it is never double-fed.

## 4. Module responsibilities

- **`context_builder.py` — pure rendering (the heart).**
  Input `(agent_name, graph, thread_turns, trust_level | None)` → `context`
  string. Owns the slice policy (D3), the labeled rendering (D6), and the
  `speaker → "you"/"student"` mapping. No DB, no LLM. Unit-tested with a tiny
  graph + a few `HistoryTurn`s + an int.
- **`manager.py` — memory coordinator (the layer's public API).**
  Input `(agent_name, graph, all_turns, trust_level | None)`. Performs the
  per-agent **thread-filtering** (D2) and the **windowing** to the last 6
  exchanges (D6), then delegates rendering to `context_builder`. Hosts the trust
  helper `apply_rapport_delta(old, delta) -> clamp(old + delta, 0, 3)`.
  Centralizing both visibility decisions (graph slice *and* conversation thread)
  here keeps all "what does this agent see" logic in one testable place. This is
  what Phase 6 calls.
- **`summarizer.py` — deferred stub** (D5).

## 5. Data types

`HistoryTurn(speaker: str, content: str, addressed_to: str | None)` — a
lightweight, framework-free value type (Pydantic model or dataclass). `speaker`
drives the rendered label; `addressed_to` lets `manager` filter a turn into the
correct per-agent thread. The orchestrator maps `ConversationTurn` rows →
`HistoryTurn`s; memory never imports `db.models`.

## 6. Cross-layer changes (⚠️ = approval gate before the change is made)

| File | Change |
|------|--------|
| `src/db/models.py` | Two nullable columns on `ConversationTurn`: `trust_level: int`, `addressed_to: str` |
| `src/db/crud.py` | `add_turn` gains optional `trust_level`, `addressed_to` params |
| `src/agents/base.py` | `AgentResponse` gains `rapport_delta: int = 0` (ADR-010 amendment) |
| ⚠️ `src/agents/patient.py` | One persona line instructing the −1/0/+1 rapport assessment |
| ⚠️ `src/state/graph.py` | One generic, additive filtered-query accessor (existing `summary()` untouched) |
| `src/core/config.py` | Constants: `RECENT_EXCHANGES_N = 6`, trust baseline/min/max |
| `docs/*` | New ADRs (memory layer / trust model / slice location); status, changelog, architecture §8 |

Schema note: the project uses `create_all`, not Alembic (ADR-016), so a fresh DB
picks up the new columns automatically; an existing dev `.db` must be recreated.

## 7. New files

- `src/memory/__init__.py`
- `src/memory/context_builder.py`
- `src/memory/manager.py`
- `src/memory/summarizer.py` (stub)
- `tests/unit/test_memory_context_builder.py`
- `tests/unit/test_memory_manager.py`

## 8. Live data flow (Phase 6 wiring — recorded here for context)

Per student turn, the orchestrator:
1. Receives the student message addressed to agent **X** (router-resolved or
   explicit).
2. Fetches prior turns via `crud`, maps → `HistoryTurn`s; reads current
   `trust_level` (last patient turn's value, or baseline).
3. Calls `manager.build_context(X, graph, turns, trust_level)` → context string
   (current message excluded).
4. Calls `agent.respond(message, context)` → `AgentResponse`
   (`revealed_nodes`, `emotional_state`, and `rapport_delta` for the patient).
5. `graph.mark_revealed(response.revealed_nodes)`.
6. If X is patient: `new_trust = manager.apply_rapport_delta(trust_level,
   response.rapport_delta)`.
7. Persists the student turn (`addressed_to=X`) and the agent turn
   (`revealed_nodes`, `trust_level=new_trust` if patient).

## 9. Build order (TDD throughout)

1. Prerequisites: db columns, config constants, `AgentResponse.rapport_delta`.
2. ⚠️ Patient persona line + ⚠️ graph filtered-query accessor — both shown for
   approval before any code is written.
3. `context_builder` (RED → GREEN): slice rendering per policy, labeled blocks,
   speaker mapping, rapport line, recent-turns formatting.
4. `manager` (RED → GREEN): thread-filtering, windowing, `apply_rapport_delta`.
5. `summarizer` stub.
6. Docs + ADRs.

## 10. Testing strategy

All unit tests, no real LLM and no DB. `context_builder` is tested by handing it a
small in-memory `PatientStateGraph`, a handful of `HistoryTurn`s, and a
`trust_level`, then asserting the rendered string: slice correctness per agent
(nurse excludes hidden; family excludes hidden; patient shows all), the rapport
line appears only for the patient, the recent-turns window and ordering, and the
`you`/`student` labelling. `manager` is tested for correct thread-filtering by
`addressed_to`, windowing to 6 exchanges, and the `apply_rapport_delta` clamp.

## 11. Out of scope / future

- The Phase 6 orchestrator/loop, the live router wiring, and the first live agent
  smoke test (the first real agent→provider call).
- A prose summarizer (D5) — revisit on evidence.
- "Collateral reveals a concealed fact" (Phase 8) — a future slice-policy tweak,
  likely needing a `metadata.known_to_family` flag.
