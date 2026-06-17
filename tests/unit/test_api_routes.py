"""Thin tests for the FastAPI routes — the HTTP seam only.

The orchestrator's behaviour (DB, reveals, trust, retry-safety) is tested directly
in test_conversation_orchestrator.py. Here we only prove the routes parse the
request, shape the response, and map outcomes to status codes. We therefore
override the dependency providers with dummies (so the real lifespan singletons
are never built — no ONNX download, no network) and monkeypatch the orchestrator
call itself.
"""

import pytest
from fastapi.testclient import TestClient

from scenarios.schema import Scenario
from src.agents.base import AgentResponseError
from src.api import deps
from src.api.main import app
from src.api.routes import conversation as conv_routes
from src.api.routes import evaluation as eval_routes
from src.api.routes import sessions as sess_routes
from src.conversation.orchestrator import TurnResult


def _scenario() -> Scenario:
    return Scenario(
        scenario_id="sc1",
        scenario_name="Chest Pain",
        patient_name="Mr Adams",
        scenario_intro="54-year-old man with chest pain.",
        nodes=[{"id": "sym_pain", "label": "chest pain", "category": "symptom"}],
    )


@pytest.fixture
def client():
    # Bypass the lifespan singletons + real db: these routes only need the HTTP seam.
    app.dependency_overrides[deps.get_db] = lambda: object()
    app.dependency_overrides[deps.get_generator] = lambda: object()
    app.dependency_overrides[deps.get_router_factory] = lambda: object()
    app.dependency_overrides[deps.get_judge] = lambda: object()
    yield TestClient(app)
    app.dependency_overrides.clear()


class _FakeEvaluation:
    """Minimal stand-in for the Evaluation ORM row the routes shape into a response."""

    covered_items_json = ["chest pain"]
    missed_items_json = ["smoking history"]
    overall_score = 0.6
    clinical_reasoning_notes = "Asked about pain; missed smoking."
    full_report_text = "CLINICAL HISTORY-TAKING — FEEDBACK\n\nOverall score: 60%"


# --- POST /sessions --------------------------------------------------------------


def test_create_session_returns_intro(client, monkeypatch):
    scenario = _scenario()

    class FakeSession:
        id = "sess-1"

    async def fake_start(db, generator, scenario_type):
        assert scenario_type == "chest_pain"
        return FakeSession(), scenario

    monkeypatch.setattr(sess_routes.orchestrator, "start_session", fake_start)

    r = client.post("/sessions", json={"scenario_type": "chest_pain"})

    assert r.status_code == 200
    assert r.json() == {
        "session_id": "sess-1",
        "scenario_intro": scenario.scenario_intro,
        "patient_name": scenario.patient_name,
    }


def test_create_session_failure_returns_503(client, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(sess_routes.orchestrator, "start_session", boom)

    r = client.post("/sessions", json={"scenario_type": "chest_pain"})

    assert r.status_code == 503


# --- GET /sessions/{id} ----------------------------------------------------------


def test_get_session_returns_state(client, monkeypatch):
    scenario = _scenario()

    class FakeSession:
        id = "sess-1"
        status = "active"
        patient_profile_json = scenario.model_dump()

    async def fake_get(db, session_id):
        return FakeSession()

    monkeypatch.setattr(sess_routes.crud, "get_session", fake_get)

    r = client.get("/sessions/sess-1")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "active"
    assert body["patient_name"] == scenario.patient_name


def test_get_session_unknown_returns_404(client, monkeypatch):
    async def fake_get(db, session_id):
        return None

    monkeypatch.setattr(sess_routes.crud, "get_session", fake_get)

    r = client.get("/sessions/nope")

    assert r.status_code == 404


# --- POST /sessions/{id}/turns ---------------------------------------------------


def test_post_turn_returns_reply(client, monkeypatch):
    async def fake_run(db, router, session_id, content, addressed_to):
        assert (content, addressed_to) == ("Where?", "patient")
        return TurnResult(speaker="patient", content="It hurts here.", emotional_state="anxious")

    monkeypatch.setattr(conv_routes.orchestrator, "run_turn", fake_run)

    r = client.post("/sessions/sess-1/turns", json={"content": "Where?", "addressed_to": "patient"})

    assert r.status_code == 200
    assert r.json() == {
        "speaker": "patient",
        "content": "It hurts here.",
        "emotional_state": "anxious",
    }


def test_post_turn_unknown_session_returns_404(client, monkeypatch):
    async def boom(*args, **kwargs):
        raise LookupError("nope")

    monkeypatch.setattr(conv_routes.orchestrator, "run_turn", boom)

    r = client.post("/sessions/nope/turns", json={"content": "Where?"})

    assert r.status_code == 404


def test_post_turn_agent_failure_returns_503(client, monkeypatch):
    async def boom(*args, **kwargs):
        raise AgentResponseError("bad json")

    monkeypatch.setattr(conv_routes.orchestrator, "run_turn", boom)

    r = client.post("/sessions/sess-1/turns", json={"content": "Where?"})

    assert r.status_code == 503


# --- POST /sessions/{id}/evaluate & GET /sessions/{id}/report --------------------


def test_evaluate_returns_report(client, monkeypatch):
    async def fake_eval(db, judge, session_id):
        return _FakeEvaluation()

    monkeypatch.setattr(eval_routes.evaluator, "evaluate_session", fake_eval)

    r = client.post("/sessions/sess-1/evaluate")

    assert r.status_code == 200
    body = r.json()
    assert body["score"] == 0.6
    assert body["covered"] == ["chest pain"]
    assert body["missed"] == ["smoking history"]
    assert "60%" in body["full_report"]


def test_evaluate_unknown_session_returns_404(client, monkeypatch):
    async def boom(*args, **kwargs):
        raise LookupError("nope")

    monkeypatch.setattr(eval_routes.evaluator, "evaluate_session", boom)

    r = client.post("/sessions/nope/evaluate")

    assert r.status_code == 404


def test_evaluate_judge_failure_returns_503(client, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("judge unreachable")

    monkeypatch.setattr(eval_routes.evaluator, "evaluate_session", boom)

    r = client.post("/sessions/sess-1/evaluate")

    assert r.status_code == 503


def test_get_report_returns_saved_evaluation(client, monkeypatch):
    async def fake_get(db, session_id):
        return _FakeEvaluation()

    monkeypatch.setattr(eval_routes.crud, "get_evaluation", fake_get)

    r = client.get("/sessions/sess-1/report")

    assert r.status_code == 200
    assert r.json()["score"] == 0.6


def test_get_report_before_evaluation_returns_404(client, monkeypatch):
    async def fake_get(db, session_id):
        return None

    monkeypatch.setattr(eval_routes.crud, "get_evaluation", fake_get)

    r = client.get("/sessions/sess-1/report")

    assert r.status_code == 404
