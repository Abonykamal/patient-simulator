"""Session routes — create a session, read its intro/metadata. Thin (CLAUDE.md).

The handlers unpack the request, call the orchestrator / crud, and shape the
response. The only logic here is HTTP concerns: status codes and never leaking a
provider failure as a 500 (it becomes a friendly 503, per D5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from scenarios.schema import Scenario
from src.api import deps, schemas
from src.conversation import orchestrator
from src.core.logging import get_logger
from src.db import crud

log = get_logger("api.sessions")
router = APIRouter()


@router.post("/sessions", response_model=schemas.CreateSessionResponse)
async def create_session(
    body: schemas.CreateSessionRequest,
    db: AsyncSession = Depends(deps.get_db),
    generator=Depends(deps.get_generator),
) -> schemas.CreateSessionResponse:
    """Generate a patient and open a session; return enough to render the intro."""
    try:
        session, scenario = await orchestrator.start_session(db, generator, body.scenario_type)
    except Exception as exc:  # never surface a provider/generation error as a 500
        log.warning("session_start_failed", scenario_type=body.scenario_type, error=str(exc))
        raise HTTPException(
            status_code=503, detail="Could not start the scenario. Please try again."
        ) from exc
    return schemas.CreateSessionResponse(
        session_id=session.id,
        scenario_intro=scenario.scenario_intro,
        patient_name=scenario.patient_name,
    )


@router.get("/sessions/{session_id}", response_model=schemas.SessionStateResponse)
async def get_session(
    session_id: str, db: AsyncSession = Depends(deps.get_db)
) -> schemas.SessionStateResponse:
    """Return a session's intro/metadata and lifecycle status."""
    session = await crud.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    scenario = Scenario.model_validate(session.patient_profile_json)
    return schemas.SessionStateResponse(
        session_id=session.id,
        scenario_intro=scenario.scenario_intro,
        patient_name=scenario.patient_name,
        status=session.status,
    )
