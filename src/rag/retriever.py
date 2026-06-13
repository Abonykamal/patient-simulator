"""Corpus ingestion and semantic retrieval over ChromaDB (ADR-021).

The retriever is the librarian: it embeds the synthetic clinical corpus once
(ingestion) and, at generation time, returns the few cases most relevant to a
request (query). It owns three decisions we settled in Phase 3 planning:

- **Whole-case documents, no chunking.** Each ``.txt`` file is one embedding;
  the case is already the right unit to hand the generator as inspiration.
- **Semantic search + metadata pre-filter.** Pure dense (vector) retrieval —
  hybrid/BM25 is overkill for a small, meaning-driven corpus. The category is
  stored as metadata so a ``where`` filter can hard-restrict results to one
  specialty (a thing neither plain semantic nor hybrid guarantees).
- **Filename is the source of truth for category.** ``chest_pain_01.txt`` →
  specialty ``chest_pain``; the trailing ``_NN`` is dropped.

Embeddings always come from our :class:`~src.rag.embedder.Embedder` seam, so the
collection is created without its own embedding function — we pass vectors in
explicitly at both add and query time.
"""

from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.config import Settings
from pydantic import BaseModel

from src.rag.embedder import Embedder

_PROVENANCE_MARKER = "# SYNTHETIC CASE"
_DEFAULT_COLLECTION = "clinical_cases"

# Telemetry off so test/app output stays pristine and nothing phones home.
_CHROMA_SETTINGS = Settings(anonymized_telemetry=False)


class RetrievedCase(BaseModel):
    """One case returned by a query: enough for the generator to use it."""

    case_id: str
    specialty: str
    text: str
    distance: float


def ephemeral_collection(name: str = _DEFAULT_COLLECTION):
    """An in-memory Chroma collection — used by tests (decision C2)."""
    client = chromadb.EphemeralClient(settings=_CHROMA_SETTINGS)
    return client.get_or_create_collection(name)


def persistent_collection(path: str | Path, name: str = _DEFAULT_COLLECTION):
    """An on-disk Chroma collection — used by the app so the corpus is embedded
    once and survives restarts (decision C1)."""
    client = chromadb.PersistentClient(path=str(path), settings=_CHROMA_SETTINGS)
    return client.get_or_create_collection(name)


def _category_from_stem(stem: str) -> str:
    # "abdominal_pain_02" -> "abdominal_pain": drop the trailing numeric index.
    head, _, tail = stem.rpartition("_")
    return head if head and tail.isdigit() else stem


def _read_case(path: Path) -> tuple[str, str, str]:
    """Return (case_id, specialty, clinical_text) for one corpus file.

    The provenance header is stripped so it never pollutes the embedding — all
    cases share that line, so embedding it would add identical noise to every
    vector.
    """
    lines = path.read_text().splitlines()
    body = [ln for ln in lines if not ln.startswith(_PROVENANCE_MARKER)]
    text = "\n".join(body).strip()
    return path.stem, _category_from_stem(path.stem), text


class Retriever:
    """Embeds the corpus into a Chroma collection and answers nearest-case queries."""

    def __init__(self, embedder: Embedder, collection) -> None:
        # The collection is injected so callers choose persistence: ephemeral in
        # tests, on-disk in the app. The retriever itself is agnostic.
        self._embedder = embedder
        self._collection = collection

    def ingest_corpus(self, corpus_dir: str | Path) -> int:
        """Embed every ``.txt`` case under ``corpus_dir`` into the collection.

        Params: ``corpus_dir`` — folder of corpus files.
        Returns: the number of cases ingested. Uses ``upsert`` so re-running is
        idempotent (same id overwrites rather than erroring).
        """
        paths = sorted(Path(corpus_dir).glob("*.txt"))
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, str]] = []
        for path in paths:
            case_id, specialty, text = _read_case(path)
            ids.append(case_id)
            documents.append(text)
            metadatas.append({"specialty": specialty, "source": path.name})

        if ids:
            embeddings = self._embedder.embed_batch(documents)
            self._collection.upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )
        return len(ids)

    def query(
        self, text: str, category: str | None = None, k: int = 3
    ) -> list[RetrievedCase]:
        """Return the ``k`` cases most similar to ``text``, nearest first.

        Params:
            ``text`` — the request to match against (rendered query text).
            ``category`` — if given, restrict to that specialty via metadata
                filter; this is a hard guarantee, not a ranking nudge.
            ``k`` — how many cases to return.
        Returns: a list of :class:`RetrievedCase`, closest match first.
        """
        query_embedding = self._embedder.embed(text)
        where = {"specialty": category} if category else None
        result = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where=where,
        )
        # Chroma nests each field one level deep (one list per query); we sent one.
        ids = result["ids"][0]
        documents = result["documents"][0]
        metadatas = result["metadatas"][0]
        distances = result["distances"][0]
        return [
            RetrievedCase(
                case_id=ids[i],
                specialty=metadatas[i]["specialty"],
                text=documents[i],
                distance=distances[i],
            )
            for i in range(len(ids))
        ]
