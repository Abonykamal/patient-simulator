# Memory & Context Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 5 memory layer that assembles each agent's `context` string (per-agent state slice + rapport line + recent turns) and carries the trust signal, plus the cross-layer prerequisites it depends on.

**Architecture:** Two pure, I/O-free modules — `context_builder` (renders a string from injected typed objects) and `manager` (filters to the per-agent thread, windows it, delegates rendering, hosts the trust-clamp). The slice *policy* lives in `context_builder`; the slice *mechanism* is a generic `graph.facts()` accessor. Trust uses the C2 model: the patient emits a bounded `rapport_delta` in its own JSON; the level is persisted per turn. No DB and no LLM are touched by the memory modules; the Phase 6 orchestrator wires them.

**Tech Stack:** Python 3.11, Pydantic, NetworkX, SQLAlchemy (async), pytest (asyncio_mode=auto). Run tests with `~/.local/bin/uv run pytest`.

**Reference spec:** `docs/specs/2026-06-16-memory-context-layer-design.md`

**⚠️ Two approval gates — do NOT write the code for these tasks until the user has approved the exact wording/signature shown in the task:**
- **Task 5** — the patient persona's two new lines (rapport gating + `rapport_delta`).
- **Task 4** — the `graph.facts()` accessor added to reviewed code.

---

## Task 1: Config tunables

**Files:**
- Modify: `src/core/config.py` (after the `AGENT_CONFIG` dict, before `class Settings`)
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_config.py`:

```python
class TestMemoryTunables:
    def test_memory_constants_have_expected_values(self):
        from src.core.config import (
            RECENT_EXCHANGES_N,
            TRUST_BASELINE,
            TRUST_MAX,
            TRUST_MIN,
        )

        assert RECENT_EXCHANGES_N == 6
        assert TRUST_MIN == 0
        assert TRUST_BASELINE == 1
        assert TRUST_MAX == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.local/bin/uv run pytest tests/unit/test_config.py::TestMemoryTunables -v`
Expected: FAIL with `ImportError: cannot import name 'RECENT_EXCHANGES_N'`.

- [ ] **Step 3: Add the constants**

In `src/core/config.py`, immediately after the `AGENT_CONFIG = {...}` block:

```python
# --- Memory & Context layer (Phase 5) tunables -----------------------------
# Recent exchanges (student msg + agent reply) kept verbatim per agent thread.
# Cost is not the constraint at this scale; this is tuned for conversational
# coherence, so it lives here for easy adjustment after the live smoke test.
RECENT_EXCHANGES_N = 6
# Trust/rapport level bounds and session-start baseline (see ADR-027).
TRUST_MIN = 0
TRUST_MAX = 3
TRUST_BASELINE = 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.local/bin/uv run pytest tests/unit/test_config.py -v`
Expected: PASS (all config tests).

- [ ] **Step 5: Commit**

```bash
git add src/core/config.py tests/unit/test_config.py
git commit -m "feat: add memory-layer config tunables (recent window, trust bounds)"
```

---

## Task 2: `AgentResponse.rapport_delta` + `_json_fields` hook

**Files:**
- Modify: `src/agents/base.py` (`AgentResponse` model; `BaseAgent._build_prompt`; add `_json_fields`)
- Test: `tests/unit/test_agents_base.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_agents_base.py`:

```python
def test_agent_response_defaults_rapport_delta_to_zero():
    from src.agents.base import AgentResponse

    resp = AgentResponse(response_text="hi", emotional_state="calm")
    assert resp.rapport_delta == 0


def test_agent_response_accepts_rapport_delta():
    from src.agents.base import AgentResponse

    resp = AgentResponse(response_text="hi", emotional_state="calm", rapport_delta=-1)
    assert resp.rapport_delta == -1


def test_base_json_fields_excludes_rapport_delta():
    # The shared default stays the original 3-field shape so nurse/family/router
    # prompts are unchanged; only the patient overrides this.
    from src.agents.base import BaseAgent

    async def _noop(_name, _prompt):
        return ""

    class _Bare(BaseAgent):
        agent_name = "patient"

        def _persona(self):
            return "persona"

    fields = _Bare(complete_fn=_noop)._json_fields()
    assert "response_text" in fields
    assert "rapport_delta" not in fields
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/unit/test_agents_base.py -v -k "rapport or json_fields"`
Expected: FAIL — `rapport_delta` is not a field; `_json_fields` does not exist.

- [ ] **Step 3: Add the field, the hook, and use the hook**

In `src/agents/base.py`, add the field to `AgentResponse` (after `emotional_state`):

```python
    emotional_state: str
    rapport_delta: int = 0  # patient-only rapport nudge (-1/0/+1); others leave 0
```

Add a hook method to `BaseAgent` (next to `_persona`):

```python
    def _json_fields(self) -> str:
        """The JSON shape this agent must return. The patient overrides this to
        request ``rapport_delta``; every other agent uses the 3-field default."""
        return '{"response_text": "...", "revealed_nodes": [...], "emotional_state": "..."}'
```

Change the final line of `_build_prompt` to use the hook (replace the hard-coded JSON template):

```python
Reply ONLY with a JSON object: {self._json_fields()}"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/unit/test_agents_base.py tests/unit/test_agents_nurse.py tests/unit/test_agents_family.py -v`
Expected: PASS — new tests green AND the existing nurse/family/base tests still pass (default prompt unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/agents/base.py tests/unit/test_agents_base.py
git commit -m "feat: AgentResponse.rapport_delta + _json_fields hook (ADR-010 amendment for C2 trust)"
```

---

## Task 3: DB columns + crud params (`trust_level`, `addressed_to`)

**Files:**
- Modify: `src/db/models.py` (`ConversationTurn`)
- Modify: `src/db/crud.py` (`add_turn`)
- Test: `tests/unit/test_db_crud.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_db_crud.py` (follow the existing async session-fixture pattern already used in that file):

```python
@pytest.mark.asyncio
async def test_add_turn_persists_trust_level_and_addressed_to(db_session):
    from src.db import crud

    sim = await crud.create_session(db_session, "sc1", "Chest pain")
    turn = await crud.add_turn(
        db_session,
        sim.id,
        speaker="patient",
        content="It's in my chest.",
        trust_level=2,
        addressed_to="student",
    )
    assert turn.trust_level == 2
    assert turn.addressed_to == "student"
```

> If the existing tests use a fixture under a different name than `db_session`, reuse that exact fixture name — match the file's current pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.local/bin/uv run pytest tests/unit/test_db_crud.py::test_add_turn_persists_trust_level_and_addressed_to -v`
Expected: FAIL — `add_turn() got an unexpected keyword argument 'trust_level'`.

- [ ] **Step 3: Add the columns and the params**

In `src/db/models.py`, add to `ConversationTurn` after `revealed_nodes_json`:

```python
    revealed_nodes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    trust_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    addressed_to: Mapped[str | None] = mapped_column(String, nullable=True)
```

In `src/db/crud.py`, extend `add_turn`'s signature and the row construction:

```python
async def add_turn(
    db: AsyncSession,
    session_id: str,
    speaker: str,
    content: str,
    revealed_nodes: list | None = None,
    trust_level: int | None = None,
    addressed_to: str | None = None,
) -> ConversationTurn:
```

and in the `ConversationTurn(...)` call inside it:

```python
    turn = ConversationTurn(
        session_id=session_id,
        turn_number=(existing or 0) + 1,
        speaker=speaker,
        content=content,
        revealed_nodes_json=revealed_nodes or [],
        trust_level=trust_level,
        addressed_to=addressed_to,
    )
```

Also extend `add_turn`'s docstring Args with `trust_level` (patient rapport after this turn) and `addressed_to` (which agent a student turn was directed at).

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/unit/test_db_crud.py tests/unit/test_db_models.py -v`
Expected: PASS — new test green, existing db tests still pass (columns are nullable; in-memory test DB recreates via `create_all`).

- [ ] **Step 5: Commit**

```bash
git add src/db/models.py src/db/crud.py tests/unit/test_db_crud.py
git commit -m "feat: persist trust_level + addressed_to per ConversationTurn"
```

---

## Task 4: ⚠️ `graph.facts()` accessor (APPROVAL GATE)

**Files:**
- Modify: `src/state/graph.py` (add `Fact` NamedTuple + `facts()` method; existing `summary()` untouched)
- Test: `tests/unit/test_state_graph.py`

- [ ] **Step 0: ⚠️ APPROVAL GATE — present this to the user and wait for explicit approval before any code**

> "This adds a generic, agent-agnostic accessor to the reviewed `graph.py`. It does **not** change `summary()` or any existing logic. Approve this exact addition?"
>
> ```python
> class Fact(NamedTuple):
>     """One fact as the memory layer consumes it (agent-agnostic)."""
>     category: str
>     label: str
>     revealed: bool
>     disclosure_difficulty: str | None
>     metadata: dict
>
> def facts(self, categories: Iterable[str] | None = None) -> list[Fact]:
>     """Return facts (optionally filtered to a category whitelist) as Fact rows.
>     ``categories=None`` returns every node. Generic: the memory layer supplies
>     the whitelist that encodes a per-agent slice. Deterministic node-id order."""
> ```

Only proceed once the user approves.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_state_graph.py`:

```python
import networkx as nx

from src.state.graph import PatientStateGraph


def _graph(*nodes):
    g = nx.Graph()
    for node in nodes:
        attrs = dict(node)
        nid = attrs.pop("id")
        attrs.setdefault("revealed", False)
        attrs.setdefault("disclosure_difficulty", None)
        attrs.setdefault("metadata", {})
        g.add_node(nid, **attrs)
    return PatientStateGraph(g)


def test_facts_returns_all_when_no_filter():
    g = _graph(
        {"id": "a", "label": "chest pain", "category": "symptom"},
        {"id": "b", "label": "smoker", "category": "history"},
    )
    cats = {f.category for f in g.facts()}
    assert cats == {"symptom", "history"}


def test_facts_filters_to_the_category_whitelist():
    g = _graph(
        {"id": "a", "label": "chest pain", "category": "symptom"},
        {"id": "b", "label": "cocaine use", "category": "hidden"},
    )
    labels = [f.label for f in g.facts({"symptom"})]
    assert labels == ["chest pain"]


def test_facts_carries_difficulty_and_metadata():
    g = _graph(
        {
            "id": "a",
            "label": "chest pain",
            "category": "symptom",
            "revealed": True,
            "metadata": {"bp": "162/94"},
        },
        {
            "id": "b",
            "label": "cocaine use",
            "category": "hidden",
            "disclosure_difficulty": "only_if_trust_built",
        },
    )
    by_label = {f.label: f for f in g.facts()}
    assert by_label["chest pain"].revealed is True
    assert by_label["chest pain"].metadata == {"bp": "162/94"}
    assert by_label["cocaine use"].disclosure_difficulty == "only_if_trust_built"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/unit/test_state_graph.py -v -k facts`
Expected: FAIL — `PatientStateGraph` has no attribute `facts`.

- [ ] **Step 3: Implement the accessor**

In `src/state/graph.py`, add `NamedTuple` to the typing import:

```python
from typing import NamedTuple
```

Add the `Fact` type at module level (above the class):

```python
class Fact(NamedTuple):
    """One fact as the memory layer consumes it (agent-agnostic)."""

    category: str
    label: str
    revealed: bool
    disclosure_difficulty: str | None
    metadata: dict
```

Add the method to `PatientStateGraph` (e.g. just after `summary`):

```python
    def facts(self, categories: Iterable[str] | None = None) -> list[Fact]:
        """Return the patient's facts, optionally filtered to ``categories``.

        ``categories=None`` returns every node. This is the generic, agent-
        agnostic slicing *mechanism*: the memory layer supplies the category
        whitelist that encodes each agent's slice *policy* (ADR-024/ADR-028).
        Deterministic node-id order so callers and tests are stable.
        """
        allowed = set(categories) if categories is not None else None
        out: list[Fact] = []
        for node_id, data in sorted(self._g.nodes(data=True), key=lambda nd: nd[0]):
            if allowed is not None and data["category"] not in allowed:
                continue
            out.append(
                Fact(
                    category=data["category"],
                    label=data["label"],
                    revealed=data["revealed"],
                    disclosure_difficulty=data.get("disclosure_difficulty"),
                    metadata=data.get("metadata", {}),
                )
            )
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/unit/test_state_graph.py -v`
Expected: PASS — new tests green, existing graph tests untouched.

- [ ] **Step 5: Commit**

```bash
git add src/state/graph.py tests/unit/test_state_graph.py
git commit -m "feat: graph.facts() generic slice accessor (mechanism for per-agent slicing, ADR-028)"
```

---

## Task 5: ⚠️ Patient persona rapport additions (APPROVAL GATE)

**Files:**
- Modify: `src/agents/patient.py` (`_PERSONA_TEMPLATE`; add `_json_fields` override)
- Test: `tests/unit/test_agents_patient.py`

- [ ] **Step 0: ⚠️ APPROVAL GATE — present this exact wording to the user and wait for explicit approval before any code**

> Two additions to the approved patient persona (per the standing "consult on every prompt" rule):
>
> **(A) Honour the injected rapport level** — appended after the existing "Trust is not a single polite word…" paragraph:
> > "You will be shown your CURRENT RAPPORT with this student as a number from 0 to 3. Treat only_if_trust_built facts as locked until that number reaches 3 — until then deflect or downplay them, even if asked directly."
>
> **(B) Emit `rapport_delta`** — appended as the final paragraph:
> > "After your reply, judge how the student's most recent message affected your comfort with them and return it as rapport_delta: +1 if they were warm, respectful, unhurried, or acknowledged how you feel; -1 if they were cold, dismissive, rushed, or accusatory; 0 for ordinary factual questions — which is the usual case, so do not let neutral clinical questions move it."
>
> And the patient will override `_json_fields()` to add `"rapport_delta": 0` to the required JSON shape. Approve both?

Only proceed once the user approves (adjust wording first if they request changes).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_agents_patient.py` (extend the existing persona-anchor test or add a new one):

```python
def test_persona_encodes_the_rapport_mechanism():
    from src.agents.patient import PatientAgent

    persona = PatientAgent("Jane")._persona()
    assert "CURRENT RAPPORT" in persona
    assert "only_if_trust_built facts as locked" in persona
    assert "rapport_delta" in persona


def test_patient_json_fields_requests_rapport_delta():
    from src.agents.patient import PatientAgent

    assert "rapport_delta" in PatientAgent("Jane")._json_fields()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/unit/test_agents_patient.py -v -k "rapport or json_fields"`
Expected: FAIL — anchors absent; `_json_fields` not overridden.

- [ ] **Step 3: Apply the approved wording**

In `src/agents/patient.py`, replace the final line of `_PERSONA_TEMPLATE`
(`Let how you are feeling come through in your words."""`) with:

```python
Let how you are feeling come through in your words.

You will be shown your CURRENT RAPPORT with this student as a number from 0 to 3. \
Treat only_if_trust_built facts as locked until that number reaches 3 — until then \
deflect or downplay them, even if asked directly.

After your reply, judge how the student's most recent message affected your comfort \
with them and return it as rapport_delta: +1 if they were warm, respectful, \
unhurried, or acknowledged how you feel; -1 if they were cold, dismissive, rushed, \
or accusatory; 0 for ordinary factual questions — which is the usual case, so do \
not let neutral clinical questions move it."""
```

Add the override to the `PatientAgent` class (after `_persona`):

```python
    def _json_fields(self) -> str:
        # Patient also reports a bounded rapport nudge (C2 trust model, ADR-027).
        return (
            '{"response_text": "...", "revealed_nodes": [...], '
            '"emotional_state": "...", "rapport_delta": 0}'
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/unit/test_agents_patient.py -v`
Expected: PASS — new tests green and the existing patient tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/agents/patient.py tests/unit/test_agents_patient.py
git commit -m "feat: patient persona honours injected rapport level + emits rapport_delta (C2, ADR-027)"
```

---

## Task 6: `context_builder` — `HistoryTurn` + per-agent slice rendering

**Files:**
- Create: `src/memory/__init__.py`
- Create: `src/memory/context_builder.py`
- Test: `tests/unit/test_memory_context_builder.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_memory_context_builder.py`:

```python
import networkx as nx

from src.state.graph import PatientStateGraph


def _graph(*nodes):
    g = nx.Graph()
    for node in nodes:
        attrs = dict(node)
        nid = attrs.pop("id")
        attrs.setdefault("revealed", False)
        attrs.setdefault("disclosure_difficulty", None)
        attrs.setdefault("metadata", {})
        g.add_node(nid, **attrs)
    return PatientStateGraph(g)


def test_patient_slice_shows_all_categories_with_difficulty_tag():
    from src.memory.context_builder import render_context

    g = _graph(
        {"id": "a", "label": "chest pain", "category": "symptom", "revealed": True},
        {
            "id": "b",
            "label": "cocaine use",
            "category": "hidden",
            "disclosure_difficulty": "only_if_trust_built",
        },
    )
    out = render_context("patient", g, [], None)
    assert "WHAT YOU KNOW ABOUT YOURSELF" in out
    assert "- chest pain [revealed]" in out
    assert "- cocaine use [hidden] (only_if_trust_built)" in out


def test_nurse_slice_excludes_hidden_and_emotional_categories():
    from src.memory.context_builder import render_context

    g = _graph(
        {"id": "a", "label": "chest pain", "category": "symptom"},
        {"id": "b", "label": "cocaine use", "category": "hidden"},
        {"id": "c", "label": "feeling scared", "category": "emotional"},
    )
    out = render_context("nurse", g, [], None)
    assert "WHAT IS DOCUMENTED" in out
    assert "chest pain" in out
    assert "cocaine use" not in out
    assert "feeling scared" not in out


def test_nurse_slice_includes_metadata_values():
    from src.memory.context_builder import render_context

    g = _graph(
        {
            "id": "a",
            "label": "vitals on admission",
            "category": "symptom",
            "metadata": {"bp": "162/94", "hr": 98},
        },
    )
    out = render_context("nurse", g, [], None)
    assert "bp: 162/94" in out
    assert "hr: 98" in out


def test_family_slice_is_social_emotional_family_only():
    from src.memory.context_builder import render_context

    g = _graph(
        {"id": "a", "label": "lives alone", "category": "social"},
        {"id": "b", "label": "chest pain", "category": "symptom"},
        {"id": "c", "label": "cocaine use", "category": "hidden"},
    )
    out = render_context("family", g, [], None)
    assert "lives alone" in out
    assert "chest pain" not in out
    assert "cocaine use" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/unit/test_memory_context_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.memory'`.

- [ ] **Step 3: Create the package and the slice renderer**

Create `src/memory/__init__.py`:

```python
"""Memory & context layer — assembles each agent's per-turn context (Phase 5).

Pure and I/O-free: these modules receive typed objects and return strings; they
never open a DB session or call an LLM. The Phase 6 orchestrator owns those
boundaries and wires the layer to crud, the router, and the agents.
"""
```

Create `src/memory/context_builder.py`:

```python
"""Render an agent's ``context`` string from injected, typed objects.

Owns the per-agent slice *policy* (ADR-024/ADR-028) and the labelled rendering of
state slice -> rapport line -> recent turns (design D6). No DB, no LLM. The graph
supplies the generic ``facts()`` *mechanism*; this module decides which categories
each agent sees and how the blocks are laid out.
"""

from __future__ import annotations

from pydantic import BaseModel

from src.core.config import TRUST_MAX
from src.state.graph import PatientStateGraph

# Slice policy: agent -> visible categories (None = all). Encodes ADR-024.
_SLICE_POLICY: dict[str, set[str] | None] = {
    "patient": None,
    "nurse": {"symptom", "history", "medication", "family_history"},
    "family": {"social", "emotional", "family_history"},
}

_SLICE_LABEL: dict[str, str] = {
    "patient": "WHAT YOU KNOW ABOUT YOURSELF (your full truth; [revealed] = already told the student):",
    "nurse": "WHAT IS DOCUMENTED IN THE CHART:",
    "family": "WHAT YOU KNOW AND HAVE OBSERVED:",
}


class HistoryTurn(BaseModel):
    """One prior turn as the memory layer consumes it — framework-free, so the
    layer never imports db.models. ``addressed_to`` lets the manager thread it."""

    speaker: str
    content: str
    addressed_to: str | None = None


def _render_slice(agent_name: str, graph: PatientStateGraph) -> str:
    facts = graph.facts(_SLICE_POLICY[agent_name])
    by_category: dict[str, list] = {}
    for fact in facts:
        by_category.setdefault(fact.category, []).append(fact)

    lines = [_SLICE_LABEL[agent_name]]
    for category in sorted(by_category):
        lines.append(f"{category}:")
        for fact in by_category[category]:
            state = "revealed" if fact.revealed else "hidden"
            line = f"  - {fact.label} [{state}]"
            # Difficulty only matters to the patient's disclosure hierarchy.
            if agent_name == "patient" and fact.disclosure_difficulty:
                line += f" ({fact.disclosure_difficulty})"
            if fact.metadata:
                meta = ", ".join(f"{k}: {fact.metadata[k]}" for k in sorted(fact.metadata))
                line += f" {{{meta}}}"
            lines.append(line)
    return "\n".join(lines)


def render_context(
    agent_name: str,
    graph: PatientStateGraph,
    thread_turns: list[HistoryTurn],
    trust_level: int | None,
) -> str:
    """Assemble the labelled context block for ``agent_name`` (design D6).

    Args:
        agent_name: patient | nurse | family.
        graph: the live state graph (full truth; sliced here by policy).
        thread_turns: this agent's recent turns, already filtered + windowed.
        trust_level: current rapport (patient only); None omits the rapport line.

    Returns:
        The context string inserted between the agent's persona and the message.
    """
    return _render_slice(agent_name, graph)
```

> Note: this step renders only the slice; the rapport line and recent turns are added in Task 7. The Task 6 tests pass arguments for them but assert only slice content.

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/unit/test_memory_context_builder.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/memory/__init__.py src/memory/context_builder.py tests/unit/test_memory_context_builder.py
git commit -m "feat: memory.context_builder per-agent state slice + HistoryTurn (ADR-024/028)"
```

---

## Task 7: `context_builder` — rapport line + recent turns

**Files:**
- Modify: `src/memory/context_builder.py` (add `_render_rapport`, `_render_turns`; extend `render_context`)
- Test: `tests/unit/test_memory_context_builder.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_memory_context_builder.py`:

```python
def test_rapport_line_appears_for_patient_only():
    from src.memory.context_builder import HistoryTurn, render_context

    g = _graph({"id": "a", "label": "chest pain", "category": "symptom"})
    patient_out = render_context("patient", g, [], 2)
    assert "CURRENT RAPPORT WITH THIS STUDENT: 2 / 3" in patient_out

    nurse_out = render_context("nurse", g, [], 2)
    assert "RAPPORT" not in nurse_out


def test_recent_turns_label_own_turns_as_you():
    from src.memory.context_builder import HistoryTurn, render_context

    g = _graph({"id": "a", "label": "chest pain", "category": "symptom"})
    turns = [
        HistoryTurn(speaker="student", content="Where is the pain?", addressed_to="patient"),
        HistoryTurn(speaker="patient", content="In my chest."),
    ]
    out = render_context("patient", g, turns, 1)
    assert "CONVERSATION SO FAR (most recent last):" in out
    assert "student: Where is the pain?" in out
    assert "you: In my chest." in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/unit/test_memory_context_builder.py -v -k "rapport_line or recent_turns"`
Expected: FAIL — `render_context` currently returns only the slice; no rapport/turns text.

- [ ] **Step 3: Add the two renderers and extend `render_context`**

In `src/memory/context_builder.py`, add after `_render_slice`:

```python
def _render_rapport(agent_name: str, trust_level: int | None) -> str | None:
    # Rapport gates only the patient's disclosure; omitted for everyone else.
    if agent_name != "patient" or trust_level is None:
        return None
    return f"CURRENT RAPPORT WITH THIS STUDENT: {trust_level} / {TRUST_MAX}"


def _render_turns(agent_name: str, thread_turns: list[HistoryTurn]) -> str:
    if not thread_turns:
        return "CONVERSATION SO FAR: (nothing said yet)"
    lines = ["CONVERSATION SO FAR (most recent last):"]
    for turn in thread_turns:
        # Per-agent threading guarantees only this agent + the student appear.
        speaker = "you" if turn.speaker == agent_name else "student"
        lines.append(f"{speaker}: {turn.content}")
    return "\n".join(lines)
```

Replace the body of `render_context` (the `return _render_slice(...)` line) with:

```python
    blocks = [_render_slice(agent_name, graph)]
    rapport = _render_rapport(agent_name, trust_level)
    if rapport is not None:
        blocks.append(rapport)
    blocks.append(_render_turns(agent_name, thread_turns))
    return "\n\n".join(blocks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/unit/test_memory_context_builder.py -v`
Expected: PASS — all context_builder tests green.

- [ ] **Step 5: Commit**

```bash
git add src/memory/context_builder.py tests/unit/test_memory_context_builder.py
git commit -m "feat: memory.context_builder rapport line + recent-turns rendering (D6)"
```

---

## Task 8: `manager` — thread filter, windowing, trust clamp

**Files:**
- Create: `src/memory/manager.py`
- Test: `tests/unit/test_memory_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_memory_manager.py`:

```python
import networkx as nx

from src.memory.context_builder import HistoryTurn
from src.state.graph import PatientStateGraph


def _graph():
    g = nx.Graph()
    g.add_node(
        "a", label="chest pain", category="symptom", revealed=False,
        disclosure_difficulty=None, metadata={},
    )
    return PatientStateGraph(g)


def test_build_context_keeps_only_this_agents_thread():
    from src.memory.manager import build_context

    turns = [
        HistoryTurn(speaker="student", content="patient question", addressed_to="patient"),
        HistoryTurn(speaker="patient", content="patient answer"),
        HistoryTurn(speaker="student", content="nurse question", addressed_to="nurse"),
        HistoryTurn(speaker="nurse", content="nurse answer"),
    ]
    out = build_context("patient", _graph(), turns, trust_level=1)
    assert "patient question" in out
    assert "patient answer" in out
    assert "nurse question" not in out
    assert "nurse answer" not in out


def test_build_context_windows_to_last_2N_turns():
    from src.core.config import RECENT_EXCHANGES_N
    from src.memory.manager import build_context

    turns = []
    for i in range(2 * RECENT_EXCHANGES_N + 4):  # more than the window
        turns.append(
            HistoryTurn(speaker="student", content=f"q{i}", addressed_to="patient")
        )
    out = build_context("patient", _graph(), turns, trust_level=1)
    assert "q0" not in out  # oldest dropped
    assert f"q{2 * RECENT_EXCHANGES_N + 3}" in out  # newest kept


def test_apply_rapport_delta_clamps_to_bounds():
    from src.memory.manager import apply_rapport_delta

    assert apply_rapport_delta(2, 1) == 3
    assert apply_rapport_delta(3, 1) == 3  # clamped at TRUST_MAX
    assert apply_rapport_delta(0, -1) == 0  # clamped at TRUST_MIN
    assert apply_rapport_delta(1, 0) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/unit/test_memory_manager.py -v`
Expected: FAIL — `No module named 'src.memory.manager'`.

- [ ] **Step 3: Implement the manager**

Create `src/memory/manager.py`:

```python
"""Memory coordinator — the layer's public API for the orchestrator (Phase 6).

Given an agent and the already-fetched session data (typed, injected — never a DB
session), it filters to that agent's per-agent thread (D2), windows it to the last
``RECENT_EXCHANGES_N`` exchanges (D6), and delegates rendering to context_builder.
Also hosts the trust clamp. Pure and I/O-free.
"""

from __future__ import annotations

from src.core.config import RECENT_EXCHANGES_N, TRUST_MAX, TRUST_MIN
from src.memory.context_builder import HistoryTurn, render_context
from src.state.graph import PatientStateGraph


def _in_thread(turn: HistoryTurn, agent_name: str) -> bool:
    """A turn belongs to an agent's thread if the agent spoke it, or the student
    addressed it to that agent. Other agents' turns are excluded (D2)."""
    return turn.speaker == agent_name or (
        turn.speaker == "student" and turn.addressed_to == agent_name
    )


def build_context(
    agent_name: str,
    graph: PatientStateGraph,
    all_turns: list[HistoryTurn],
    trust_level: int | None = None,
) -> str:
    """Build ``agent_name``'s context string from all session turns.

    Args:
        agent_name: patient | nurse | family.
        graph: the live state graph.
        all_turns: every turn so far (excluding the current message), as
            HistoryTurns; this function selects the agent's thread.
        trust_level: current rapport (patient only); None omits the rapport line.

    Returns:
        The assembled context string.
    """
    thread = [t for t in all_turns if _in_thread(t, agent_name)]
    window = thread[-(2 * RECENT_EXCHANGES_N) :]  # last N exchanges (~2 turns each)
    return render_context(agent_name, graph, window, trust_level)


def apply_rapport_delta(level: int, delta: int) -> int:
    """Apply a bounded rapport nudge and clamp to [TRUST_MIN, TRUST_MAX] (ADR-027)."""
    return max(TRUST_MIN, min(TRUST_MAX, level + delta))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/unit/test_memory_manager.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/memory/manager.py tests/unit/test_memory_manager.py
git commit -m "feat: memory.manager thread-filter + windowing + rapport clamp (D2/D6/ADR-027)"
```

---

## Task 9: `summarizer` deferred stub

**Files:**
- Create: `src/memory/summarizer.py`
- Test: `tests/unit/test_memory_manager.py` (one guard test) — or a dedicated file

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_memory_manager.py`:

```python
def test_summarizer_is_deferred():
    import pytest

    from src.memory import summarizer

    with pytest.raises(NotImplementedError):
        summarizer.summarize()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.local/bin/uv run pytest tests/unit/test_memory_manager.py::test_summarizer_is_deferred -v`
Expected: FAIL — `No module named 'src.memory.summarizer'`.

- [ ] **Step 3: Create the stub**

Create `src/memory/summarizer.py`:

```python
"""Conversation summariser — deferred (design D5).

The structured stores cover the MVP: the graph's [revealed] flags capture what is
disclosed and the persisted trust_level captures the rapport arc, so no prose
recap is injected. This slot is preserved so the layer's shape is complete; wire
in a real summariser only if a live session overflows the window or needs early
non-factual recall. See docs/specs/2026-06-16-memory-context-layer-design.md.
"""

from __future__ import annotations


def summarize(*args, **kwargs) -> str:  # pragma: no cover - deferred
    """Not implemented for the MVP — see the module docstring (design D5)."""
    raise NotImplementedError("Conversation summarization is deferred (design D5).")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.local/bin/uv run pytest tests/unit/test_memory_manager.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `~/.local/bin/uv run pytest tests/ -q`
Expected: PASS — all prior tests plus the new memory tests (target ~118+).

- [ ] **Step 6: Commit**

```bash
git add src/memory/summarizer.py tests/unit/test_memory_manager.py
git commit -m "feat: memory.summarizer deferred stub (design D5)"
```

---

## Task 10: Documentation + ADRs

**Files:**
- Modify: `docs/decisions.md` (append ADR-026, ADR-027, ADR-028)
- Modify: `docs/project_status.md` (Phase 5 progress; summarizer deferred)
- Modify: `docs/changelog.md` (new milestone entry)
- Modify: `docs/architecture.md` (§ Memory layer + testing-strategy count)

- [ ] **Step 1: Append the three ADRs to `docs/decisions.md`**

Insert before the trailing footer, following the existing ADR structure:

- **ADR-026 — Memory & Context layer: injected typed inputs, per-agent threading, labelled context (D1/D2/D6).** Context is a rendered string; inputs (graph, `HistoryTurn`s, `trust_level`) are injected, not fetched, so the layer is I/O-free and unit-testable. Each agent sees only its own thread (protects the ADR-024 slice on the conversation axis). Context = labelled state slice → patient-only rapport line → last `RECENT_EXCHANGES_N` exchanges.
- **ADR-027 — Trust model (C2).** A persisted `trust_level` (0–3, baseline 1) is nudged by a bounded `rapport_delta` (−1/0/+1) the patient emits in its own JSON (no extra LLM call); `only_if_trust_built` nodes unlock at level 3. Persisted per patient turn for the trajectory (Phase 7). Reversible to a separate-judge design (C1) without touching the rest of the layer.
- **ADR-028 — Per-agent slice: policy in memory, mechanism in graph.** `graph.facts()` is the generic filtering mechanism; the `agent → categories` policy lives in `context_builder`. Keeps the graph free of agent identities.

- [ ] **Step 2: Update `docs/project_status.md`**

Set Current State to "Phase 5 (Memory & Context) complete". Check the Phase 5 items; mark `summarizer.py` as "deferred (design D5)". Add the ADR-026/027/028 bullets to the locked-decisions list. Point What's Next at Phase 6 (Full Conversation Loop), and note the first live agent→provider smoke test now becomes possible once the orchestrator wires context to a real graph.

- [ ] **Step 3: Update `docs/changelog.md`**

Add a `### 2026-06-16 — Phase 5: Memory & Context complete` entry summarising: `context_builder` (per-agent slice via policy + `graph.facts()` mechanism, labelled blocks, rapport line, recent-turns window), `manager` (thread-filter + windowing + rapport clamp), `HistoryTurn`, the C2 trust additions (`AgentResponse.rapport_delta`, patient persona, `trust_level`/`addressed_to` columns), deferred summarizer, ADR-026/027/028, and the new test total.

- [ ] **Step 4: Update `docs/architecture.md`**

Fill in the Memory layer section (the four modules + the live data flow from spec §8), flip its status row to ✅ Phase 5, and update the testing-strategy unit-test count.

- [ ] **Step 5: Commit**

```bash
git add docs/decisions.md docs/project_status.md docs/changelog.md docs/architecture.md
git commit -m "docs: Phase 5 memory layer — ADRs 026-028, status, changelog, architecture"
```

---

## Notes for the implementer

- **Standing rules:** tests NEVER make real LLM or network calls; commit only the files each task lists; do not modify `docs/project_spec.md`. The two ⚠️ approval gates (Tasks 4 and 5) must be cleared with the user before their code is written.
- **`uv`:** run tests via `~/.local/bin/uv run pytest …`. `asyncio_mode=auto` and `pythonpath=["."]` are already configured.
- **DB column note:** the new `ConversationTurn` columns are nullable and picked up by `create_all` (ADR-016, no Alembic). The in-memory test DB recreates each run, so no migration is needed; an existing dev `.db` file would need recreating if one exists.
- **Latent gap closed:** the patient slice now tags each fact with its `disclosure_difficulty`, which is what makes the Phase-4 persona's disclosure hierarchy and the trust gate actually function — they were inert until this layer surfaced that tag in the context.
