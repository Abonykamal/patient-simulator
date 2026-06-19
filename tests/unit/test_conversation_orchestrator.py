"""Tests for src.conversation.orchestrator — the per-turn loop.

All collaborators (generator, router, agents) are fakes, so these run with no
network. The db is the real in-memory SQLite from conftest, so persistence and
the rebuild-from-turns lifecycle (D2) are exercised for real.
"""

import pytest

from scenarios.schema import Scenario
from src.agents.base import AgentResponse, AgentResponseError
from src.conversation.orchestrator import SessionClosedError, run_turn, start_session
from src.db import crud
from src.rag.generator import ScenarioRequest


def _scenario() -> Scenario:
    """A tiny but complete scenario: one plain symptom and one trust-gated secret."""
    return Scenario(
        scenario_id="sc1",
        scenario_name="Chest Pain",
        patient_name="Mr Adams",
        scenario_intro="54-year-old man with chest pain.",
        nodes=[
            {"id": "sym_pain", "label": "crushing chest pain", "category": "symptom"},
            {
                "id": "hidden_cocaine",
                "label": "cocaine use this morning",
                "category": "hidden",
                "disclosure_difficulty": "only_if_trust_built",
            },
        ],
        edges=[{"source": "sym_pain", "target": "hidden_cocaine", "relation": "precipitant"}],
    )


class FakeGenerator:
    """Stands in for ScenarioGenerator; records the request, returns a canned scenario."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.request: ScenarioRequest | None = None

    async def generate(self, request: ScenarioRequest) -> Scenario:
        self.request = request
        return self.scenario


class FakeAgent:
    """Stands in for a persona agent; records what context it was handed."""

    def __init__(self, agent_name: str, response: AgentResponse | Exception) -> None:
        self.agent_name = agent_name
        self._response = response
        self.received_message: str | None = None
        self.received_context: str | None = None

    async def respond(self, message: str, context: str) -> AgentResponse:
        self.received_message = message
        self.received_context = context
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class FakeRouter:
    """Stands in for Router; resolves to a fixed agent, records the addressing."""

    def __init__(self, agent: FakeAgent) -> None:
        self.agent = agent
        self.received: tuple[str, str | None] | None = None

    async def resolve(self, message: str, addressed_to: str | None = None) -> FakeAgent:
        self.received = (message, addressed_to)
        return self.agent


class FakeRouterFactory:
    """Stands in for the injected ``(patient_name) -> Router`` factory."""

    def __init__(self, router: FakeRouter) -> None:
        self.router = router
        self.patient_name: str | None = None

    def __call__(self, patient_name: str) -> FakeRouter:
        self.patient_name = patient_name
        return self.router


async def _make_session(db_session, scenario: Scenario):
    return await crud.create_session(
        db_session,
        scenario.scenario_id,
        scenario.scenario_name,
        patient_profile=scenario.model_dump(),
    )


# --- start_session ---------------------------------------------------------------


async def test_start_session_generates_persists_and_returns(db_session):
    scenario = _scenario()
    gen = FakeGenerator(scenario)

    session, returned = await start_session(db_session, gen, "chest_pain")

    assert gen.request.category == "chest_pain"  # asked for the right specialty
    assert returned == scenario
    fetched = await crud.get_session(db_session, session.id)
    assert fetched.scenario_id == "sc1"
    assert fetched.scenario_name == "Chest Pain"
    # The FULL scenario is stored so the graph can be rebuilt each turn (D2).
    assert fetched.patient_profile_json == scenario.model_dump()


# --- run_turn: happy path --------------------------------------------------------


async def test_run_turn_patient_persists_exchange_and_marks_reveals(db_session):
    scenario = _scenario()
    sim = await _make_session(db_session, scenario)
    agent = FakeAgent(
        "patient",
        AgentResponse(
            response_text="It's in my chest.",
            revealed_nodes=["sym_pain"],
            emotional_state="anxious",
            rapport_delta=1,
        ),
    )

    factory = FakeRouterFactory(FakeRouter(agent))
    result = await run_turn(db_session, factory, sim.id, "Where's the pain?", "patient")

    assert result.speaker == "patient"
    assert result.content == "It's in my chest."
    assert result.emotional_state == "anxious"
    assert factory.patient_name == "Mr Adams"  # router built with this session's patient

    turns = await crud.get_turns(db_session, sim.id)
    assert [t.speaker for t in turns] == ["student", "patient"]
    student, patient = turns
    assert student.content == "Where's the pain?"
    assert student.addressed_to == "patient"
    assert patient.revealed_nodes_json == ["sym_pain"]
    assert patient.trust_level == 2  # baseline 1 + delta 1


async def test_run_turn_replays_prior_reveals_into_context(db_session):
    """Event sourcing (D2): a reveal in turn 1 shows as revealed in turn 2's context."""
    scenario = _scenario()
    sim = await _make_session(db_session, scenario)

    agent1 = FakeAgent(
        "patient",
        AgentResponse(response_text="ok", revealed_nodes=["sym_pain"], emotional_state="calm"),
    )
    await run_turn(db_session, FakeRouterFactory(FakeRouter(agent1)), sim.id, "q1", "patient")
    # Before this turn, sym_pain was disclosed once; the rebuilt graph must reflect it.
    assert "crushing chest pain [hidden]" in agent1.received_context

    agent2 = FakeAgent(
        "patient",
        AgentResponse(response_text="ok", revealed_nodes=[], emotional_state="calm"),
    )
    await run_turn(db_session, FakeRouterFactory(FakeRouter(agent2)), sim.id, "q2", "patient")
    assert "crushing chest pain [revealed]" in agent2.received_context


async def test_run_turn_stores_resolved_agent_as_addressed_to(db_session):
    """ADR-026 ripple: the student turn records who actually answered, not the raw input."""
    scenario = _scenario()
    sim = await _make_session(db_session, scenario)
    nurse = FakeAgent("nurse", AgentResponse(response_text="BP 148/92.", emotional_state="neutral"))
    router = FakeRouter(nurse)

    await run_turn(
        db_session, FakeRouterFactory(router), sim.id, "What's his BP?", addressed_to=None
    )

    assert router.received == ("What's his BP?", None)  # raw input passed through
    turns = await crud.get_turns(db_session, sim.id)
    student = turns[0]
    assert student.addressed_to == "nurse"  # resolved name, not None/"auto"


async def test_run_turn_nonpatient_turn_carries_no_trust(db_session):
    scenario = _scenario()
    sim = await _make_session(db_session, scenario)
    nurse = FakeAgent(
        "nurse",
        AgentResponse(response_text="BP 148/92.", emotional_state="neutral", rapport_delta=1),
    )

    await run_turn(
        db_session, FakeRouterFactory(FakeRouter(nurse)), sim.id, "What's his BP?", "nurse"
    )

    turns = await crud.get_turns(db_session, sim.id)
    nurse_turn = turns[1]
    assert nurse_turn.trust_level is None  # trust is patient-only (ADR-027)
    assert "CURRENT RAPPORT" not in nurse.received_context  # no rapport line for the nurse


async def test_run_turn_reads_back_trust_and_clamps(db_session):
    """Current trust comes from the last patient turn; the nudge clamps at TRUST_MAX."""
    scenario = _scenario()
    sim = await _make_session(db_session, scenario)
    await crud.add_turn(db_session, sim.id, "student", "earlier q", addressed_to="patient")
    await crud.add_turn(db_session, sim.id, "patient", "earlier a", trust_level=3)

    agent = FakeAgent(
        "patient",
        AgentResponse(response_text="thanks", emotional_state="warm", rapport_delta=1),
    )
    await run_turn(
        db_session, FakeRouterFactory(FakeRouter(agent)), sim.id, "You're very kind", "patient"
    )

    assert "CURRENT RAPPORT WITH THIS STUDENT: 3 / 3" in agent.received_context  # read-back
    turns = await crud.get_turns(db_session, sim.id)
    assert turns[-1].trust_level == 3  # clamp(3 + 1) == 3


async def test_run_turn_agent_failure_persists_nothing(db_session):
    """Writes happen after the LLM call, so a failed turn leaves zero state (D5)."""
    scenario = _scenario()
    sim = await _make_session(db_session, scenario)
    agent = FakeAgent("patient", AgentResponseError("model would not comply"))

    with pytest.raises(AgentResponseError):
        await run_turn(
            db_session, FakeRouterFactory(FakeRouter(agent)), sim.id, "Where's the pain?", "patient"
        )

    assert await crud.get_turns(db_session, sim.id) == []  # nothing persisted → retry-safe


async def test_run_turn_unknown_session_raises_lookuperror(db_session):
    agent = FakeAgent("patient", AgentResponse(response_text="hi", emotional_state="calm"))
    with pytest.raises(LookupError):
        await run_turn(
            db_session, FakeRouterFactory(FakeRouter(agent)), "no-such-session", "hello", "patient"
        )


async def test_run_turn_completed_session_rejects(db_session):
    """A graded (completed) session must not accept further turns (ADR-033)."""
    scenario = _scenario()
    sim = await _make_session(db_session, scenario)
    await crud.end_session(db_session, sim.id)  # session is now completed
    agent = FakeAgent("patient", AgentResponse(response_text="hi", emotional_state="calm"))

    with pytest.raises(SessionClosedError):
        await run_turn(
            db_session, FakeRouterFactory(FakeRouter(agent)), sim.id, "One more question?", "patient"
        )

    # The guard runs before any write, so nothing is persisted (consistent with D5).
    assert await crud.get_turns(db_session, sim.id) == []
