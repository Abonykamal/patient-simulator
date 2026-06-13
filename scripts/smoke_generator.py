"""Manual smoke test for the live RAG → LLM path (NOT part of the pytest suite).

This makes a REAL Gemini call and therefore costs free-tier quota, so it is run
by hand, never in CI/tests. It exercises the full Phase 3 chain end to end with
real credentials:

    corpus → embed → ChromaDB retrieve → scenario_generator LLM → schema-validate
    → build into a PatientStateGraph

Run from the project root (PYTHONPATH=. puts the repo on sys.path, the way
pytest does automatically):

    PYTHONPATH=. ~/.local/bin/uv run python scripts/smoke_generator.py

Reads the API key from .env via src.core.config.Settings. Prints a summary of
the generated patient and exits non-zero on failure with a focused diagnosis.
"""

from __future__ import annotations

import asyncio
import sys

from scenarios.schema import Scenario
from src.rag.embedder import Embedder
from src.rag.generator import ScenarioGenerator, ScenarioRequest
from src.rag.retriever import Retriever, ephemeral_collection
from src.state.builder import build_graph

CORPUS_DIR = "src/rag/corpus"
CATEGORY = "chest_pain"


def _print_scenario(scenario: Scenario) -> None:
    print(f"  scenario_id : {scenario.scenario_id}")
    print(f"  patient_name: {scenario.patient_name}")
    print(f"  intro       : {scenario.scenario_intro}")
    print(f"  nodes ({len(scenario.nodes)}):")
    for node in scenario.nodes:
        diff = f", {node.disclosure_difficulty}" if node.disclosure_difficulty else ""
        print(f"    - [{node.category}] {node.label} ({node.importance}{diff})")
    print(f"  edges       : {len(scenario.edges)}")


async def main() -> int:
    print("== Phase 3 live smoke test ==")

    # 1. Ingest corpus into an in-memory collection (real embedder, no network).
    retriever = Retriever(Embedder(), ephemeral_collection())
    n = retriever.ingest_corpus(CORPUS_DIR)
    print(f"[1/3] ingested {n} corpus cases")

    # 2. Generate against the REAL scenario_generator model (this is the live call).
    print(f"[2/3] generating a '{CATEGORY}' patient via the live LLM ...")
    generator = ScenarioGenerator(retriever)  # default complete_fn = real client
    scenario = await generator.generate(ScenarioRequest(category=CATEGORY))
    print("      generation succeeded and validated against the schema:")
    _print_scenario(scenario)

    # 3. Confirm the generated scenario builds into a live patient state graph.
    graph = build_graph(scenario)
    print(f"[3/3] built PatientStateGraph with {len(graph)} nodes")

    print("\nSMOKE TEST PASSED ✅  (real LLM → validated scenario → graph)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001 — a smoke test should explain any failure
        print(f"\nSMOKE TEST FAILED ❌  {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
