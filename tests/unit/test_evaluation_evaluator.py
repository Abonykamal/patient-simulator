"""Tests for src.evaluation.evaluator — the coordinator (real in-memory DB, fake judge)."""

import pytest

from scenarios.schema import Scenario
from src.db import crud
from src.evaluation.evaluator import evaluate_session
from src.evaluation.judge import ItemVerdict, JudgeVerdict


def _scenario() -> Scenario:
    return Scenario(
        scenario_id="sc1",
        scenario_name="Chest Pain",
        patient_name="Mr Adams",
        scenario_intro="intro",
        nodes=[
            {
                "id": "sym_pain",
                "label": "chest pain",
                "category": "symptom",
                "importance": "critical",
            },
            {
                "id": "hist_smoke",
                "label": "smoking history",
                "category": "history",
                "importance": "relevant",
            },
        ],
    )


class FakeJudge:
    """Stands in for the Judge; returns a canned verdict, records calls + transcript."""

    def __init__(self, verdict: JudgeVerdict) -> None:
        self.verdict = verdict
        self.calls = 0
        self.last_transcript: str | None = None

    async def judge(self, rubric_items, transcript: str) -> JudgeVerdict:
        self.calls += 1
        self.last_transcript = transcript
        return self.verdict


async def _seed(db) -> str:
    sc = _scenario()
    sim = await crud.create_session(
        db, sc.scenario_id, sc.scenario_name, patient_profile=sc.model_dump()
    )
    await crud.add_turn(db, sim.id, "student", "Do you have chest pain?", addressed_to="patient")
    await crud.add_turn(db, sim.id, "patient", "Yes, it's crushing.", revealed_nodes=["sym_pain"])
    return sim.id


async def test_evaluate_session_scores_persists_and_completes(db_session):
    session_id = await _seed(db_session)
    verdict = JudgeVerdict(
        items=[ItemVerdict(id="sym_pain", asked=True), ItemVerdict(id="hist_smoke", asked=False)],
        clinical_reasoning_notes="Asked about pain; missed smoking history.",
    )
    judge = FakeJudge(verdict)

    ev = await evaluate_session(db_session, judge, session_id)

    # sym_pain critical(3) asked, hist_smoke relevant(2) missed → 3/5 = 0.6
    assert ev.overall_score == 0.6
    assert ev.covered_items_json == ["chest pain"]
    assert ev.missed_items_json == ["smoking history"]
    assert "missed smoking" in ev.clinical_reasoning_notes
    assert "60%" in ev.full_report_text
    # the judge graded a transcript containing the student's line
    assert "student: Do you have chest pain?" in judge.last_transcript
    # session is now completed and the evaluation is retrievable
    assert (await crud.get_session(db_session, session_id)).status == "completed"
    assert (await crud.get_evaluation(db_session, session_id)).id == ev.id


async def test_evaluate_session_is_idempotent(db_session):
    session_id = await _seed(db_session)
    judge = FakeJudge(
        JudgeVerdict(items=[ItemVerdict(id="sym_pain", asked=True)], clinical_reasoning_notes="ok")
    )

    first = await evaluate_session(db_session, judge, session_id)
    second = await evaluate_session(db_session, judge, session_id)

    assert judge.calls == 1  # not re-judged (D5)
    assert second.id == first.id  # same row returned


async def test_evaluate_session_unknown_raises_lookuperror(db_session):
    judge = FakeJudge(JudgeVerdict(items=[], clinical_reasoning_notes=""))
    with pytest.raises(LookupError):
        await evaluate_session(db_session, judge, "no-such-session")
