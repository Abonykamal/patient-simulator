"""Tests for src.db.crud — the public database operations of the db layer."""

from src.db import crud


async def test_create_and_get_session(db_session):
    sim = await crud.create_session(
        db_session, "chest_pain", "Chest Pain", patient_profile={"name": "John"}
    )
    assert sim.id  # a UUID was assigned

    fetched = await crud.get_session(db_session, sim.id)
    assert fetched is sim
    assert fetched.status == "active"
    assert fetched.patient_profile_json == {"name": "John"}


async def test_get_session_unknown_returns_none(db_session):
    assert await crud.get_session(db_session, "does-not-exist") is None


async def test_add_turn_assigns_sequential_numbers(db_session):
    sim = await crud.create_session(db_session, "x", "X")
    t1 = await crud.add_turn(db_session, sim.id, "student", "Where is the pain?")
    t2 = await crud.add_turn(db_session, sim.id, "patient", "In my chest.")
    assert (t1.turn_number, t2.turn_number) == (1, 2)


async def test_add_turn_stores_revealed_nodes(db_session):
    sim = await crud.create_session(db_session, "x", "X")
    turn = await crud.add_turn(
        db_session, sim.id, "patient", "It spreads to my arm.", revealed_nodes=["radiation"]
    )
    assert turn.revealed_nodes_json == ["radiation"]


async def test_get_turns_orders_and_limits_to_recent(db_session):
    sim = await crud.create_session(db_session, "x", "X")
    for i in range(3):
        await crud.add_turn(db_session, sim.id, "student", f"q{i}")

    all_turns = await crud.get_turns(db_session, sim.id)
    assert [t.content for t in all_turns] == ["q0", "q1", "q2"]

    recent = await crud.get_turns(db_session, sim.id, limit=2)
    assert [t.content for t in recent] == ["q1", "q2"]  # last 2, still chronological


async def test_end_session_marks_completed_and_stores_snapshot(db_session):
    sim = await crud.create_session(db_session, "x", "X")
    snapshot = {"nodes": ["chest_pain"], "revealed": ["chest_pain"]}

    ended = await crud.end_session(db_session, sim.id, state_snapshot=snapshot)
    assert ended.status == "completed"
    assert ended.ended_at is not None
    assert ended.state_snapshot_json == snapshot


async def test_save_and_get_evaluation(db_session):
    sim = await crud.create_session(db_session, "x", "X")
    saved = await crud.save_evaluation(
        db_session,
        sim.id,
        rubric_items=["ask onset", "ask radiation"],
        covered_items=["ask onset"],
        missed_items=["ask radiation"],
        overall_score=0.5,
        clinical_reasoning_notes="Solid history, missed risk factors.",
        full_report_text="Full narrative report...",
    )
    assert saved.id is not None

    fetched = await crud.get_evaluation(db_session, sim.id)
    assert fetched.overall_score == 0.5
    assert fetched.covered_items_json == ["ask onset"]
    assert fetched.missed_items_json == ["ask radiation"]
