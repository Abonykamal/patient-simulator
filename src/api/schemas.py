"""Request/response models for the HTTP API (spec §API Design).

These are the *contract* the Streamlit frontend and (later) Phase 7 depend on, so
they are deliberately small and stable. Note ``TurnResponse`` does NOT carry
``revealed_nodes``: what the student did or did not surface is internal state and
must never be shown back to them.
"""

from __future__ import annotations

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    """Body of ``POST /sessions`` — which scenario specialty to generate."""

    scenario_type: str  # corpus category, e.g. "chest_pain"


class CreateSessionResponse(BaseModel):
    """Result of ``POST /sessions`` — enough for the UI to render the intro."""

    session_id: str
    scenario_intro: str
    patient_name: str


class SessionStateResponse(BaseModel):
    """Result of ``GET /sessions/{id}`` — intro/metadata plus lifecycle status."""

    session_id: str
    scenario_intro: str
    patient_name: str
    status: str  # active | completed


class TurnRequest(BaseModel):
    """Body of ``POST /sessions/{id}/turns`` — the student's message.

    ``addressed_to`` is the explicit recipient chosen in the UI (patient | nurse |
    family). Optional: if omitted, the router defaults to the patient.
    """

    content: str
    addressed_to: str | None = None


class TurnResponse(BaseModel):
    """Result of ``POST /sessions/{id}/turns`` — who answered and what they said."""

    speaker: str  # patient | nurse | family
    content: str
    emotional_state: str


class EvaluationResponse(BaseModel):
    """Result of ``POST /evaluate`` and ``GET /report`` — the end-of-session grade."""

    covered: list[str]  # topics the student asked about
    missed: list[str]  # topics the student did not ask about
    score: float  # 0–1 weighted coverage
    clinical_reasoning_notes: str
    full_report: str
