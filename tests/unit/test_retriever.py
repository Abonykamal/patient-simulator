"""Tests for src.rag.retriever — corpus ingestion + semantic retrieval (ADR-021).

The retriever is the librarian over ChromaDB. These tests use the *real* local
embedder and an *in-memory* Chroma collection (decision C2): no network, no
files, no mocks. They pin the behaviours the generator depends on:

- ingestion parses the case category from the *filename* prefix and strips the
  ``# SYNTHETIC CASE`` provenance header before embedding,
- a semantic query returns the most relevant case first, and
- the category metadata filter is a hard guarantee — a query tagged one
  specialty never returns a case from another.
"""

from pathlib import Path

from src.rag.embedder import Embedder
from src.rag.retriever import RetrievedCase, Retriever, ephemeral_collection

_EMB = Embedder()


def _make_retriever() -> Retriever:
    return Retriever(_EMB, ephemeral_collection())


def _write_corpus(dir_: Path, cases: dict[str, str]) -> Path:
    # cases: filename-stem -> body text. Each file gets the real provenance header.
    for stem, body in cases.items():
        (dir_ / f"{stem}.txt").write_text(
            f"# SYNTHETIC CASE — generated for RAG pipeline testing\n\n{body}\n"
        )
    return dir_


def test_ingest_returns_count_and_populates_collection(tmp_path):
    retr = _make_retriever()
    _write_corpus(
        tmp_path,
        {
            "chest_pain_01": "Crushing central chest pain radiating to the left arm with sweating.",
            "dyspnea_01": "Progressive breathlessness, wheeze, and a night-time cough.",
        },
    )
    n = retr.ingest_corpus(tmp_path)
    assert n == 2


def test_query_returns_most_relevant_case_first(tmp_path):
    retr = _make_retriever()
    _write_corpus(
        tmp_path,
        {
            "chest_pain_01": "Crushing central chest pain radiating to the left arm with sweating.",
            "dyspnea_01": "Progressive breathlessness, wheeze, and a night-time cough.",
            "headache_01": "Throbbing one-sided headache with nausea and light sensitivity.",
        },
    )
    retr.ingest_corpus(tmp_path)

    results = retr.query("severe pressure in the chest spreading to the shoulder", k=3)
    assert isinstance(results[0], RetrievedCase)
    assert results[0].case_id == "chest_pain_01"


def test_category_filter_restricts_to_that_specialty(tmp_path):
    retr = _make_retriever()
    _write_corpus(
        tmp_path,
        {
            "chest_pain_01": "Crushing central chest pain radiating to the left arm.",
            "chest_pain_02": "Exertional chest tightness relieved by rest.",
            "dyspnea_01": "Breathless and wheezing, worse at night.",
        },
    )
    retr.ingest_corpus(tmp_path)

    # Even though the query text is about the chest, the filter pins specialty.
    results = retr.query("chest discomfort", category="dyspnea", k=3)
    assert results
    assert all(r.specialty == "dyspnea" for r in results)


def test_ingest_strips_provenance_header(tmp_path):
    retr = _make_retriever()
    _write_corpus(tmp_path, {"chest_pain_01": "Crushing central chest pain."})
    retr.ingest_corpus(tmp_path)

    only = retr.query("chest pain", k=1)[0]
    assert "SYNTHETIC CASE" not in only.text
    assert only.text.startswith("Crushing")


def test_ingests_real_corpus_with_parsed_categories():
    # The authored corpus must load: 15 cases, multi-word specialties parsed
    # from filenames (e.g. abdominal_pain_02 -> "abdominal_pain").
    retr = _make_retriever()
    corpus_dir = Path("src/rag/corpus")
    n = retr.ingest_corpus(corpus_dir)
    assert n == 15

    results = retr.query("tearing chest pain with sweating", category="chest_pain", k=3)
    assert results
    assert all(r.specialty == "chest_pain" for r in results)
