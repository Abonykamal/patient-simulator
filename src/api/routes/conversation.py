"""Conversation route — submit a student message, get the agent's reply. Thin.

Maps the orchestrator's outcomes to HTTP: an unknown session is a 404; any
LLM/agent failure becomes a friendly 503 with nothing persisted (D5), so the
student can simply resend. The happy path returns who answered and what they said.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api import deps, schemas
from src.conversation import orchestrator
from src.core.logging import get_logger

log = get_logger("api.conversation")
router = APIRouter()


@router.post("/sessions/{session_id}/turns", response_model=schemas.TurnResponse)
async def post_turn(
    session_id: str,
    body: schemas.TurnRequest,
    db: AsyncSession = Depends(deps.get_db),
    build_router=Depends(deps.get_router_factory),
) -> schemas.TurnResponse:
    """Run one conversation turn and return the answering agent's reply."""
    try:
        result = await orchestrator.run_turn(
            db, build_router, session_id, body.content, body.addressed_to
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    except Exception as exc:  # provider down or agent could not produce valid output
        log.warning("turn_failed", session_id=session_id, error=str(exc))
        raise HTTPException(
            status_code=503, detail="The reply could not be generated. Please try again."
        ) from exc
    return schemas.TurnResponse(
        speaker=result.speaker, content=result.content, emotional_state=result.emotional_state
    )
