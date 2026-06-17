"""Manual smoke test for the live LLM-as-judge (NOT part of the pytest suite).

This makes ONE real Groq/Llama call — the judge — so it costs free-tier quota and
is run by hand, never in CI/tests. To stay focused on the judge (and cheap), it
seeds a hand-written scenario + transcript directly into an in-memory DB rather
than generating a patient and running live agents (smoke_conversation.py covers
that path). It then grades through the real evaluation chain:

    build_rubric → judge (LIVE) → score → format → end + save

Run from the project root:

    PYTHONPATH=. ~/.local/bin/uv run python scripts/smoke_evaluation.py

Reads the API key from .env via src.core.config. Prints the report and exits
non-zero on failure with a focused diagnosis.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from scenarios.schema import Scenario
from src.db import crud
from src.db.models import Base
from src.evaluation.evaluator import evaluate_session
from src.evaluation.judge import Judge

SCENARIO = Scenario(
    scenario_id="smoke_eval",
    scenario_name="Chest Pain",
    patient_name="Mr Adams",
    scenario_intro="54-year-old man with chest pain.",
    nodes=[
        {
            "id": "sym_onset",
            "label": "chest pain since this morning",
            "category": "symptom",
            "importance": "critical",
        },
        {
            "id": "sym_radiation",
            "label": "pain radiating to the left arm",
            "category": "symptom",
            "importance": "critical",
        },
        {
            "id": "hist_smoking",
            "label": "smoking history",
            "category": "history",
            "importance": "relevant",
        },
        {
            "id": "hist_family",
            "label": "family history of cardiac disease",
            "category": "family_history",
            "importance": "relevant",
        },
        {
            "id": "soc_job",
            "label": "works as a taxi driver",
            "category": "social",
            "importance": "minor",
        },
    ],
)

# A student who asked about onset + radiation but skipped smoking/family/social —
# so a correct judge should mark the first two asked and the rest missed.
TRANSCRIPT = [
    ("student", "Hello, what brought you in today?", "patient"),
    ("patient", "I've had chest pain since this morning.", None),
    ("student", "Does the pain spread anywhere, such as into your arm?", "patient"),
    ("patient", "Yes — down my left arm.", None),
]


async def main() -> int:
    print("== Phase 7 live judge smoke test ==")

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async with sessionmaker() as db:
        sim = await crud.create_session(
            db, SCENARIO.scenario_id, SCENARIO.scenario_name, patient_profile=SCENARIO.model_dump()
        )
        for speaker, content, to in TRANSCRIPT:
            await crud.add_turn(db, sim.id, speaker, content, addressed_to=to)
        print("[1/2] seeded a scripted transcript (no live agent calls)")

        print("[2/2] grading via the LIVE judge (Groq/Llama) ...")
        ev = await evaluate_session(db, Judge(), sim.id)  # the live judge call
        await db.commit()

        print("\n--- REPORT ---")
        print(ev.full_report_text)
        print(
            f"\nscore={ev.overall_score}  "
            f"covered={ev.covered_items_json}  missed={ev.missed_items_json}"
        )

    await engine.dispose()
    print("\nSMOKE TEST PASSED ✅  (live judge → scored evaluation)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001 — a smoke test should explain any failure
        print(f"\nSMOKE TEST FAILED ❌  {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
