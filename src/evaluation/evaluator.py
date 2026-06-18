"""The evaluation coordinator (D3 / ADR-032) — one end-of-session grade, end to end.

Mirrors the conversation orchestrator's shape: pure-ish glue that knows the *order*
of operations, with the judge injected so it unit-tests with a fake and no network.
It lives here, in the evaluation layer, so rubric/judge/report concerns stay
together and the conversation orchestrator isn't burdened with evaluation.

Like ``run_turn``, the risky LLM call (the judge) happens *before* any write, so a
judge failure leaves the session un-ended and unevaluated — but unlike a turn the
intent is *fail loud*: a missing evaluation must never look like a pass.
"""

from __future__ import annotations

from scenarios.schema import Scenario
from src.db import crud
from src.db.models import Evaluation
from src.evaluation import report
from src.evaluation.rubric import build_rubric


def _render_transcript(turns: list) -> str:
    """Render persisted turns into the labelled transcript the judge grades."""
    return "\n".join(f"{turn.speaker}: {turn.content}" for turn in turns)


async def evaluate_session(db, judge, session_id: str) -> Evaluation:
    """Grade a session: judge the transcript, score it, end the session, persist it.

    Args:
        db: active database session.
        judge: a Judge (or fake) exposing ``async judge(rubric_items, transcript)``.
        session_id: the session to evaluate.

    Returns:
        The persisted :class:`Evaluation`. If the session is already evaluated, that
        existing evaluation is returned unchanged (idempotent, D5 — no re-judge).

    Raises:
        LookupError: if ``session_id`` does not exist.
        Exception: a judge failure propagates (fail loud) before anything is written.
    """
    existing = await crud.get_evaluation(db, session_id)
    if existing is not None:
        return existing  # idempotent: don't spend judge quota or overwrite (D5)

    session = await crud.get_session(db, session_id)
    if session is None:
        raise LookupError(f"unknown session: {session_id}")

    scenario = Scenario.model_validate(session.patient_profile_json)
    rubric = build_rubric(scenario)
    turns = await crud.get_turns(db, session_id)
    transcript = _render_transcript(turns)

    # The risky LLM call — first, before any write; fails loud (no fallback).
    verdict = await judge.judge(rubric, transcript)

    verdicts = {item.id: item.verdict for item in verdict.items}
    scored = report.score(verdicts, rubric)
    full_report = report.format_report(scored, verdict.clinical_reasoning_notes)

    # Mark the session completed (no graph snapshot — redundant under ADR-030, D6).
    await crud.end_session(db, session_id)
    return await crud.save_evaluation(
        db,
        session_id,
        rubric_items=[item.model_dump() for item in rubric],
        covered_items=scored.covered,
        missed_items=scored.missed,
        overall_score=scored.overall_score,
        clinical_reasoning_notes=verdict.clinical_reasoning_notes,
        full_report_text=full_report,
    )
