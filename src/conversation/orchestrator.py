"""The conversation orchestrator — one turn, end to end (Phase 6).

This is the glue the whole project has been building toward: it runs the arrow
chain (router → memory → agent → state → db) for a single turn, and creates a
session. It holds no domain rules — only the *order* — and takes every
collaborator injected, so it unit-tests with fakes and no network.

Two design choices shape the code:

- **Rebuild-from-turns (D2 / ADR-030).** The state graph is not cached or
  snapshotted mid-session; it is rebuilt each turn from the stored scenario and
  the per-turn reveal log. The persisted turns *are* the event log; the graph is
  a projection. That makes the system stateless and restart-safe with no extra
  storage and no chance of a second copy of the truth drifting.
- **Writes after the risky call (D5).** The LLM call happens before any database
  write, so a failed turn leaves zero partial state and the student can simply
  retry. ``get_db`` rolls the (empty) transaction back on the way out.
"""

from __future__ import annotations

from typing import NamedTuple

from scenarios.schema import Scenario
from src.core.config import TRUST_BASELINE
from src.db import crud
from src.db.models import SimulationSession
from src.memory.context_builder import HistoryTurn
from src.memory.manager import apply_rapport_delta, build_context
from src.state.builder import build_graph
from src.state.graph import PatientStateGraph


class TurnResult(NamedTuple):
    """What one turn produced — mapped by the route to ``schemas.TurnResponse``.

    Deliberately omits ``revealed_nodes``: what the student surfaced is internal
    state and must never be echoed back to them.
    """

    speaker: str
    content: str
    emotional_state: str


async def start_session(db, generator, scenario_type: str) -> tuple[SimulationSession, Scenario]:
    """Generate a patient and open a session for it.

    Args:
        db: active database session.
        generator: a ScenarioGenerator (or fake) exposing ``async generate(req)``.
        scenario_type: corpus specialty to generate (e.g. "chest_pain").

    Returns:
        The persisted session and the generated scenario. The *full* scenario is
        stored in ``patient_profile_json`` so ``run_turn`` can rebuild the graph.
    """
    # Imported here so importing the orchestrator never pulls in the RAG stack.
    from src.rag.generator import ScenarioRequest

    scenario = await generator.generate(ScenarioRequest(category=scenario_type))
    session = await crud.create_session(
        db,
        scenario.scenario_id,
        scenario.scenario_name,
        patient_profile=scenario.model_dump(),
    )
    return session, scenario


def _rebuild_graph(session: SimulationSession, turns: list) -> PatientStateGraph:
    """Project the live graph from the stored scenario + the per-turn reveal log."""
    scenario = Scenario.model_validate(session.patient_profile_json)
    graph = build_graph(scenario)
    for turn in turns:
        # Same hallucination-safe guard runs on replay as on the live turn, so the
        # rebuilt state is exactly what the live session produced.
        graph.mark_revealed(turn.revealed_nodes_json or [])
    return graph


def _current_trust(turns: list) -> int:
    """The patient's current rapport: the last patient turn's level, else baseline."""
    for turn in reversed(turns):
        if turn.speaker == "patient" and turn.trust_level is not None:
            return turn.trust_level
    return TRUST_BASELINE


async def run_turn(
    db, router, session_id: str, content: str, addressed_to: str | None = None
) -> TurnResult:
    """Run one conversation turn and persist the exchange.

    Args:
        db: active database session.
        router: a Router (or fake) exposing ``async resolve(message, addressed_to)``.
        session_id: the session this turn belongs to.
        content: the student's message.
        addressed_to: explicit recipient (patient | nurse | family), or None.

    Returns:
        A :class:`TurnResult` with the answering agent, its reply, and its mood.

    Raises:
        LookupError: if ``session_id`` does not exist.
        Exception: any LLM/agent failure propagates *before* anything is written,
            so the turn is retry-safe (D5).
    """
    session = await crud.get_session(db, session_id)
    if session is None:
        raise LookupError(f"unknown session: {session_id}")

    # 1. Reconstitute session state from the DB (the source of truth).
    turns = await crud.get_turns(db, session_id)
    graph = _rebuild_graph(session, turns)
    trust = _current_trust(turns)

    # 2. Resolve who answers, then build *their* context (per-agent slice + thread).
    agent = await router.resolve(content, addressed_to)
    name = agent.agent_name
    is_patient = name == "patient"
    history = [
        HistoryTurn(speaker=t.speaker, content=t.content, addressed_to=t.addressed_to)
        for t in turns
    ]
    context = build_context(name, graph, history, trust if is_patient else None)

    # 3. The risky LLM call — FIRST, before any write, so failure is retry-safe.
    resp = await agent.respond(content, context)

    # 4. Apply the agent's reported results to the (in-memory) graph + trust.
    graph.mark_revealed(resp.revealed_nodes)
    if is_patient:
        trust = apply_rapport_delta(trust, resp.rapport_delta)

    # 5. Persist the exchange. The student turn records the *resolved* recipient so
    #    per-agent threading (ADR-026) attributes it to the right thread.
    await crud.add_turn(db, session_id, "student", content, addressed_to=name)
    await crud.add_turn(
        db,
        session_id,
        name,
        resp.response_text,
        revealed_nodes=resp.revealed_nodes,
        trust_level=trust if is_patient else None,
    )

    return TurnResult(
        speaker=name, content=resp.response_text, emotional_state=resp.emotional_state
    )
