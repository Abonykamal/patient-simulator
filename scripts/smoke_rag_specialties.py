"""Manual cross-specialty smoke test for the RAG pipeline (NOT part of pytest).

Phase 8 verification that the RAG → generation chain works across *every* corpus
specialty, not just chest pain. For each category it checks the whole path with
real credentials:

    retrieve (category-filtered) → scenario_generator LLM → schema-validate
    → build PatientStateGraph → derive the evaluation rubric

It makes ONE live Gemini call per category (more only if a scenario needs a
validation repair), so it costs free-tier quota and is run by hand, never in CI.

Two things are asserted that the single-category smoke does not:
  - the metadata pre-filter is a *hard* guarantee — every retrieved case for a
    request carries the requested specialty (ADR-021), and
  - each generated patient is distinct (different name), i.e. the pipeline isn't
    collapsing to one scenario.

Run from the project root:

    PYTHONPATH=. ~/.local/bin/uv run python scripts/smoke_rag_specialties.py

Prints a per-specialty summary and a final table; exits non-zero on the first
failure with a focused diagnosis.
"""

from __future__ import annotations

import asyncio
import sys

from scenarios.schema import Scenario
from src.evaluation.rubric import build_rubric
from src.rag.embedder import Embedder
from src.rag.generator import ScenarioGenerator, ScenarioRequest, _render_query
from src.rag.retriever import Retriever, ephemeral_collection
from src.state.builder import build_graph

CORPUS_DIR = "src/rag/corpus"

# Every specialty the corpus covers (Phase 3): the app's five presenting complaints.
CATEGORIES = ["chest_pain", "dyspnea", "abdominal_pain", "headache", "leg_swelling"]


def _verify_retrieval_is_category_pinned(retriever: Retriever, category: str) -> int:
    """Retrieval for ``category`` must return ONLY that specialty (hard filter)."""
    cases = retriever.query(_render_query(ScenarioRequest(category=category)), category=category)
    if not cases:
        raise AssertionError(f"retrieval returned no cases for '{category}'")
    off_specialty = [c.case_id for c in cases if c.specialty != category]
    if off_specialty:
        raise AssertionError(
            f"category filter leaked for '{category}': off-specialty cases {off_specialty}"
        )
    return len(cases)


async def _generate_and_check(generator: ScenarioGenerator, category: str) -> Scenario:
    """Generate one patient for ``category`` and confirm it builds + yields a rubric."""
    scenario = await generator.generate(ScenarioRequest(category=category))
    graph = build_graph(scenario)  # raises if the validated scenario won't build
    rubric = build_rubric(scenario)  # the evaluation rubric for this generated patient
    print(
        f"      ✓ {category:14s} → {scenario.patient_name!r:22s} "
        f"{len(scenario.nodes):2d} nodes, {len(graph):2d} graph nodes, "
        f"{len(rubric):2d} graded topics"
    )
    print(f"        intro: {scenario.scenario_intro}")
    return scenario


async def main() -> int:
    print("== Phase 8 cross-specialty RAG smoke test ==")

    retriever = Retriever(Embedder(), ephemeral_collection())
    n = retriever.ingest_corpus(CORPUS_DIR)
    print(f"[1/3] ingested {n} corpus cases across {len(CATEGORIES)} specialties\n")

    print("[2/3] verifying the category metadata filter is a hard guarantee ...")
    for category in CATEGORIES:
        k = _verify_retrieval_is_category_pinned(retriever, category)
        print(f"      ✓ {category:14s} → {k} cases, all specialty='{category}'")

    print("\n[3/3] generating one patient per specialty via the live LLM ...")
    generator = ScenarioGenerator(retriever)  # default complete_fn = real client
    scenarios = [await _generate_and_check(generator, category) for category in CATEGORIES]

    # Distinctness: different specialties must not collapse to the same patient.
    names = [s.patient_name for s in scenarios]
    if len(set(names)) != len(names):
        raise AssertionError(f"generated patients are not distinct: {names}")

    print(f"\nSMOKE TEST PASSED ✅  {len(scenarios)} specialties generated, validated, distinct")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001 — a smoke test should explain any failure
        print(f"\nSMOKE TEST FAILED ❌  {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
