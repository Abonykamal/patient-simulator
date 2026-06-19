"""Request/response models for the HTTP API (spec §API Design).

These are the *contract* the Streamlit frontend and (later) Phase 7 depend on, so
they are deliberately small and stable. Note ``TurnResponse`` does NOT carry
``revealed_nodes``: what the student did or did not surface is internal state and
must never be shown back to them.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints


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

    ``content`` must carry an actual question — a blank or whitespace-only message
    is rejected (422) before any agent/LLM work, never sent as an empty prompt.
    ``addressed_to`` is the explicit recipient chosen in the UI; the contract is
    strict (patient | nurse | family) since the UI is a fixed dropdown, so an
    unknown value is a bug we surface (422) rather than silently coerce. Optional:
    if omitted, the router defaults to the patient.
    """

    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    addressed_to: Literal["patient", "nurse", "family"] | None = None


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
