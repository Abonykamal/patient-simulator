"""Evaluation routes — end + judge a session, and read the report back. Thin.

`POST /evaluate` runs the judge (idempotent; ends + saves) and `GET /report` reads
the saved evaluation. A judge failure becomes a **503** — unlike a turn this is
*fail-loud* (a missing/degraded evaluation must not look like a pass). Unknown
session → 404; reading a report before evaluating → 404.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api import deps, schemas
from src.core.logging import get_logger
from src.db import crud
from src.db.models import Evaluation
from src.evaluation import evaluator

log = get_logger("api.evaluation")
router = APIRouter()


def _to_response(ev: Evaluation) -> schemas.EvaluationResponse:
    """Shape a persisted Evaluation row into the API response."""
    return schemas.EvaluationResponse(
        covered=ev.covered_items_json,
        missed=ev.missed_items_json,
        score=ev.overall_score if ev.overall_score is not None else 0.0,
        clinical_reasoning_notes=ev.clinical_reasoning_notes or "",
        full_report=ev.full_report_text or "",
    )


@router.post("/sessions/{session_id}/evaluate", response_model=schemas.EvaluationResponse)
async def evaluate(
    session_id: str,
    db: AsyncSession = Depends(deps.get_db),
    judge=Depends(deps.get_judge),
) -> schemas.EvaluationResponse:
    """End the session, run the judge, persist and return the evaluation."""
    try:
        ev = await evaluator.evaluate_session(db, judge, session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    except Exception as exc:  # judge failure: fail loud, do not fabricate a pass
        log.warning("evaluation_failed", session_id=session_id, error=str(exc))
        raise HTTPException(
            status_code=503, detail="The evaluation could not be generated. Please try again."
        ) from exc
    return _to_response(ev)


@router.get("/sessions/{session_id}/report", response_model=schemas.EvaluationResponse)
async def report(
    session_id: str, db: AsyncSession = Depends(deps.get_db)
) -> schemas.EvaluationResponse:
    """Return the saved evaluation, or 404 if the session has not been evaluated."""
    ev = await crud.get_evaluation(db, session_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="No evaluation for this session yet.")
    return _to_response(ev)
