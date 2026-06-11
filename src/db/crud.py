"""CRUD operations — the only public API of the db layer.

Every function takes an ``AsyncSession`` as its first argument (ADR-014) and
``flush``es rather than commits: the transaction boundary belongs to the
request (``get_db``) or the test. No raw SQL exists outside this module.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.db.models import ConversationTurn, Evaluation, SimulationSession

log = get_logger("db.crud")


async def create_session(
    db: AsyncSession,
    scenario_id: str,
    scenario_name: str,
    patient_profile: dict | None = None,
) -> SimulationSession:
    """Create a new simulation session row.

    Args:
        db: Active database session.
        scenario_id: Identifier of the scenario template.
        scenario_name: Human-readable scenario name.
        patient_profile: The generated patient as a dict, or None if not yet set.

    Returns:
        The persisted ``SimulationSession`` (with its UUID assigned).
    """
    sim = SimulationSession(
        id=str(uuid.uuid4()),
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        patient_profile_json=patient_profile,
    )
    db.add(sim)
    await db.flush()
    log.info("session_created", session_id=sim.id, scenario_id=scenario_id)
    return sim


async def get_session(db: AsyncSession, session_id: str) -> SimulationSession | None:
    """Fetch a session by id, or None if it does not exist."""
    return await db.get(SimulationSession, session_id)


async def add_turn(
    db: AsyncSession,
    session_id: str,
    speaker: str,
    content: str,
    revealed_nodes: list | None = None,
) -> ConversationTurn:
    """Append a conversation turn, auto-assigning the next sequential turn number.

    Args:
        db: Active database session.
        session_id: Owning session id.
        speaker: One of student | patient | nurse | family.
        content: The message text.
        revealed_nodes: State-graph node ids revealed by this turn, if any.

    Returns:
        The persisted ``ConversationTurn``.
    """
    existing = await db.scalar(
        select(func.count())
        .select_from(ConversationTurn)
        .where(ConversationTurn.session_id == session_id)
    )
    turn = ConversationTurn(
        session_id=session_id,
        turn_number=(existing or 0) + 1,
        speaker=speaker,
        content=content,
        revealed_nodes_json=revealed_nodes or [],
    )
    db.add(turn)
    await db.flush()
    return turn


async def get_turns(
    db: AsyncSession, session_id: str, limit: int | None = None
) -> list[ConversationTurn]:
    """Return a session's turns in chronological order.

    Args:
        db: Active database session.
        session_id: Owning session id.
        limit: If given, return only the most recent ``limit`` turns
            (still ordered oldest-to-newest). If None, return all.

    Returns:
        Turns ordered by ascending turn number.
    """
    if limit is not None:
        stmt = (
            select(ConversationTurn)
            .where(ConversationTurn.session_id == session_id)
            .order_by(ConversationTurn.turn_number.desc())
            .limit(limit)
        )
        rows = list((await db.scalars(stmt)).all())
        rows.reverse()  # fetched newest-first for the limit; hand back chronological
        return rows

    stmt = (
        select(ConversationTurn)
        .where(ConversationTurn.session_id == session_id)
        .order_by(ConversationTurn.turn_number)
    )
    return list((await db.scalars(stmt)).all())


async def end_session(
    db: AsyncSession, session_id: str, state_snapshot: dict | None = None
) -> SimulationSession | None:
    """Mark a session completed and store the final state-graph snapshot.

    Args:
        db: Active database session.
        session_id: Session to end.
        state_snapshot: Serialized final state graph, or None.

    Returns:
        The updated session, or None if no such session exists.
    """
    sim = await db.get(SimulationSession, session_id)
    if sim is None:
        return None
    sim.status = "completed"
    sim.ended_at = datetime.now(UTC)
    sim.state_snapshot_json = state_snapshot
    await db.flush()
    log.info("session_ended", session_id=session_id)
    return sim


async def save_evaluation(
    db: AsyncSession,
    session_id: str,
    rubric_items: list,
    covered_items: list,
    missed_items: list,
    overall_score: float | None = None,
    clinical_reasoning_notes: str | None = None,
    full_report_text: str | None = None,
) -> Evaluation:
    """Persist the judge's evaluation for a session.

    Returns:
        The persisted ``Evaluation``.
    """
    evaluation = Evaluation(
        session_id=session_id,
        rubric_items_json=rubric_items,
        covered_items_json=covered_items,
        missed_items_json=missed_items,
        overall_score=overall_score,
        clinical_reasoning_notes=clinical_reasoning_notes,
        full_report_text=full_report_text,
    )
    db.add(evaluation)
    await db.flush()
    log.info("evaluation_saved", session_id=session_id, overall_score=overall_score)
    return evaluation


async def get_evaluation(db: AsyncSession, session_id: str) -> Evaluation | None:
    """Fetch the evaluation for a session, or None if none exists."""
    return await db.scalar(select(Evaluation).where(Evaluation.session_id == session_id))
