"""Tests for src.rag.embedder — the text→vector seam (ADR-020, B1).

The embedder is the single place that owns "turn text into an embedding."
These tests run against the *real* local ONNX MiniLM model (no mocks): it is
free, offline, and deterministic, so we can assert the one property that
actually makes retrieval work — text with similar *meaning* lands at similar
vectors, even when the words differ.
"""

import math

from src.rag.embedder import Embedder

# Build the model once for the module; constructing it loads the ONNX model.
_EMB = Embedder()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb)


def test_embed_returns_fixed_length_float_vector():
    vec = _EMB.embed("crushing chest pain radiating to the left arm")
    assert len(vec) == 384
    assert all(isinstance(x, float) for x in vec)


def test_embed_is_deterministic():
    # Same text in → identical vector out. Retrieval relies on this stability.
    a = _EMB.embed("shortness of breath on exertion")
    b = _EMB.embed("shortness of breath on exertion")
    assert a == b


def test_similar_meaning_is_closer_than_dissimilar():
    # The load-bearing property: meaning, not exact words. A paraphrase of the
    # query must sit closer than an unrelated clinical sentence.
    query = _EMB.embed("crushing chest pain radiating to the arm")
    paraphrase = _EMB.embed("severe retrosternal pressure spreading to the shoulder")
    unrelated = _EMB.embed("itchy red rash on both ankles for three weeks")

    assert _cosine(query, paraphrase) > _cosine(query, unrelated)


def test_embed_batch_returns_one_vector_per_input():
    vecs = _EMB.embed_batch(["fever and productive cough", "swollen painful calf"])
    assert len(vecs) == 2
    assert all(len(v) == 384 for v in vecs)
