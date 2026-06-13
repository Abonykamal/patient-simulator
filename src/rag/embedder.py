"""The text→vector seam for the RAG layer.

One module owns "turn text into an embedding," mirroring how ``llm/client.py``
owns provider calls and ``core/config.py`` owns model choice (ADR-020, decision
B1). Everything that needs a vector — corpus ingestion and query time — goes
through here, so the embedding model is swappable in exactly one place.

We use the ``all-MiniLM-L6-v2`` model in its ONNX-quantized form, which ChromaDB
bundles. It runs locally, needs no API key, and is deterministic — so it costs
no quota and our tests can assert on real vectors instead of mocks (decision
A1). The model file (~80 MB) is downloaded once on first use and cached.
"""

from __future__ import annotations

from chromadb.utils import embedding_functions


class Embedder:
    """Wraps the local ONNX MiniLM model behind a small, stable interface.

    Construction loads the model (downloading it once if absent), so create one
    instance and reuse it for a whole process rather than per call.
    """

    def __init__(self) -> None:
        # ChromaDB's bundled all-MiniLM-L6-v2; same model family as
        # sentence-transformers but the lighter ONNX runtime (no torch).
        self._fn = embedding_functions.ONNXMiniLM_L6_V2()

    def embed(self, text: str) -> list[float]:
        """Embed a single string into a 384-dim vector of plain floats.

        Params: ``text`` — the text to embed.
        Returns: a list of 384 floats. Texts with similar meaning produce
        vectors that are close under cosine similarity.
        """
        return self._to_floats(self._fn([text])[0])

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many strings at once, returning one vector per input.

        Params: ``texts`` — the texts to embed, in order.
        Returns: a list of vectors aligned to ``texts``. Batching is how
        ingestion embeds the whole corpus in a single model call.
        """
        return [self._to_floats(v) for v in self._fn(texts)]

    @staticmethod
    def _to_floats(vector: object) -> list[float]:
        # The ONNX function returns numpy float32 arrays; convert to plain
        # Python floats so the seam never leaks numpy types downstream.
        return [float(x) for x in vector]
