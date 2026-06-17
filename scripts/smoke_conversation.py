"""Manual smoke test for the live conversation loop (NOT part of the pytest suite).

This makes REAL Gemini calls — scenario generation AND the first live *agent*
replies — so it costs free-tier quota and is run by hand, never in CI/tests. It
exercises the full Phase 6 chain end to end with real credentials:

    start_session (RAG generate → graph) → run_turn × N
    (router → memory context → agent LLM → mark_revealed → trust → persist)

Run from the project root:

    PYTHONPATH=. ~/.local/bin/uv run python scripts/smoke_conversation.py

Uses a fresh in-memory SQLite DB so it never touches your real database. Reads the
API key from .env via src.core.config. Prints the scripted interview and the final
state, and exits non-zero on failure with a focused diagnosis.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.agents.family import FamilyAgent
from src.agents.nurse import NurseAgent
from src.agents.patient import PatientAgent
from src.agents.router import Router
from src.conversation.orchestrator import run_turn, start_session
from src.db import crud
from src.db.models import Base
from src.rag.embedder import Embedder
from src.rag.generator import ScenarioGenerator
from src.rag.retriever import Retriever, ephemeral_collection

CORPUS_DIR = "src/rag/corpus"
CATEGORY = "chest_pain"

# A tiny scripted interview touching all three agents. The two warm patient turns
# also let us watch trust move (rapport_delta) across the encounter.
SCRIPT = [
    ("Hello, I'm one of the doctors. What brought you in today?", "patient"),
    (
        "That sounds really frightening — I'm sorry you're going through it. When did it start?",
        "patient",
    ),
    ("Could you check his blood pressure for me?", "nurse"),
    ("Has he seemed himself at home over the last few days?", "family"),
]


async def main() -> int:
    print("== Phase 6 live smoke test ==")

    # Fresh in-memory DB for this run (StaticPool keeps the single connection alive).
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    # Real RAG generator (ephemeral Chroma; the embedder runs locally) + real agents.
    retriever = Retriever(Embedder(), ephemeral_collection())
    retriever.ingest_corpus(CORPUS_DIR)
    generator = ScenarioGenerator(retriever)
    router = Router(PatientAgent(), NurseAgent(), FamilyAgent())  # default = live LLM

    async with sessionmaker() as db:
        print(f"[1/3] generating a '{CATEGORY}' patient via the live LLM ...")
        session, scenario = await start_session(db, generator, CATEGORY)
        print(f"      patient : {scenario.patient_name}")
        print(f"      intro   : {scenario.scenario_intro}")

        print("[2/3] running a scripted interview (live agent calls) ...")
        for content, to in SCRIPT:
            print(f"\n  student → {to}: {content}")
            result = await run_turn(db, router, session.id, content, to)
            print(f"  {result.speaker} ({result.emotional_state}): {result.content}")

        await db.commit()

        print("\n[3/3] final session state:")
        turns = await crud.get_turns(db, session.id)
        revealed = sorted({n for t in turns for n in (t.revealed_nodes_json or [])})
        trust = next(
            (
                t.trust_level
                for t in reversed(turns)
                if t.speaker == "patient" and t.trust_level is not None
            ),
            None,
        )
        print(f"      turns persisted : {len(turns)}")
        print(f"      revealed nodes  : {revealed}")
        print(f"      final trust     : {trust}")

    await engine.dispose()
    print("\nSMOKE TEST PASSED ✅  (live generation + live agents through the full loop)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001 — a smoke test should explain any failure
        print(f"\nSMOKE TEST FAILED ❌  {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
