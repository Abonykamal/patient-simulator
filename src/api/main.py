"""FastAPI app entry point + lifespan (Phase 6).

The lifespan builds the expensive collaborators ONCE at startup — the Retriever
(with the corpus embedded into a persistent Chroma store, idempotently), the
ScenarioGenerator, the three agents and the Router — and parks them on
``app.state`` for the ``deps`` providers to hand to routes. The real LLM client is
the agents' default ``complete_fn``, so this is the wiring where live provider
calls finally happen in production.

Run with: ``uvicorn src.api.main:app --reload --port 8000``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.agents.family import FamilyAgent
from src.agents.nurse import NurseAgent
from src.agents.patient import PatientAgent
from src.agents.router import Router
from src.api.routes import conversation, evaluation, sessions
from src.core.logging import get_logger
from src.db.session import init_db
from src.evaluation.judge import Judge
from src.rag.embedder import Embedder
from src.rag.generator import ScenarioGenerator
from src.rag.retriever import Retriever, persistent_collection

log = get_logger("api.main")

CORPUS_DIR = "src/rag/corpus"
CHROMA_PATH = "chroma_data"  # gitignored on-disk Chroma store; embedded once


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the singletons once and expose them on ``app.state``."""
    await init_db()  # create_all (ADR-016)

    retriever = Retriever(Embedder(), persistent_collection(CHROMA_PATH))
    cases = retriever.ingest_corpus(CORPUS_DIR)  # idempotent; embeds on first run only
    log.info("corpus_ingested", cases=cases)

    app.state.generator = ScenarioGenerator(retriever)

    # The nurse/family agents are stateless, so they are built once and shared; the
    # patient agent is parameterised by the patient's name, so the router is built
    # per session via this factory (the orchestrator calls it once it knows the name).
    nurse, family = NurseAgent(), FamilyAgent()

    def build_router(patient_name: str) -> Router:
        return Router(PatientAgent(patient_name), nurse, family)

    app.state.router_factory = build_router
    app.state.judge = Judge()  # stateless; default complete_fn = live LLM (Groq, no fallback)
    log.info("app_ready")
    yield


app = FastAPI(title="Patient Journey Simulator", lifespan=lifespan)
app.include_router(sessions.router)
app.include_router(conversation.router)
app.include_router(evaluation.router)
