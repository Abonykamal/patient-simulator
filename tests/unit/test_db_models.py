"""Tests for src.db.models — the ORM mapping itself (columns, defaults, JSON)."""

from src.db.models import Base, ConversationTurn, SimulationSession


def test_metadata_has_expected_tables():
    # The model registry maps exactly the three tables the spec defines.
    assert set(Base.metadata.tables) == {
        "sessions",
        "conversation_turns",
        "evaluations",
    }


async def test_session_defaults_and_json_roundtrip(db_session):
    profile = {"name": "John Doe", "age": 54, "history": ["smoker"]}
    db_session.add(
        SimulationSession(
            id="sess-1",
            scenario_id="chest_pain",
            scenario_name="Chest Pain",
            patient_profile_json=profile,
        )
    )
    await db_session.flush()

    fetched = await db_session.get(SimulationSession, "sess-1")
    assert fetched.status == "active"  # column default applied
    assert fetched.started_at is not None  # timestamp default applied
    assert fetched.ended_at is None  # nullable, unset
    assert fetched.patient_profile_json == profile  # dict in, dict out (no manual json)


async def test_turn_revealed_nodes_roundtrip(db_session):
    db_session.add(SimulationSession(id="sess-2", scenario_id="x", scenario_name="X"))
    turn = ConversationTurn(
        session_id="sess-2",
        turn_number=1,
        speaker="patient",
        content="It hurts right here.",
        revealed_nodes_json=["chest_pain", "radiation"],
    )
    db_session.add(turn)
    await db_session.flush()

    fetched = await db_session.get(ConversationTurn, turn.id)
    assert fetched.revealed_nodes_json == ["chest_pain", "radiation"]


async def test_session_turns_relationship_is_ordered(db_session):
    db_session.add(SimulationSession(id="sess-3", scenario_id="x", scenario_name="X"))
    # Insert out of order to prove the relationship's order_by, not insert order.
    db_session.add(
        ConversationTurn(session_id="sess-3", turn_number=2, speaker="patient", content="b")
    )
    db_session.add(
        ConversationTurn(session_id="sess-3", turn_number=1, speaker="student", content="a")
    )
    await db_session.flush()

    fetched = await db_session.get(SimulationSession, "sess-3")
    await db_session.refresh(fetched, ["turns"])  # eager-load the relationship under async
    assert [t.turn_number for t in fetched.turns] == [1, 2]
