"""SQLAlchemy ORM models — the three tables defined in the spec.

These encode the schema; they do not contain business logic. JSON-shaped
columns use SQLAlchemy's ``JSON`` type (ADR-015), so callers assign and read
back Python dicts/lists and never touch json.dumps/loads. The class is named
``SimulationSession`` (not ``Session``) to avoid shadowing SQLAlchemy's own
session concept in code that handles both.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    """Timezone-aware current UTC time, used as a column default."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base; ``Base.metadata`` drives table creation."""


class SimulationSession(Base):
    """One simulation session — maps to the ``sessions`` table."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID assigned by crud
    scenario_id: Mapped[str] = mapped_column(String, nullable=False)
    scenario_name: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    patient_profile_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    state_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    turns: Mapped[list[ConversationTurn]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConversationTurn.turn_number",
    )
    evaluation: Mapped[Evaluation | None] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ConversationTurn(Base):
    """One message exchanged in a session — maps to ``conversation_turns``."""

    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(
        String, nullable=False
    )  # student | patient | nurse | family
    content: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    revealed_nodes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)

    session: Mapped[SimulationSession] = relationship(back_populates="turns")


class Evaluation(Base):
    """One end-of-session evaluation — maps to the ``evaluations`` table."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    rubric_items_json: Mapped[list] = mapped_column(JSON, nullable=False)
    covered_items_json: Mapped[list] = mapped_column(JSON, nullable=False)
    missed_items_json: Mapped[list] = mapped_column(JSON, nullable=False)
    clinical_reasoning_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    full_report_text: Mapped[str | None] = mapped_column(String, nullable=True)

    session: Mapped[SimulationSession] = relationship(back_populates="evaluation")
