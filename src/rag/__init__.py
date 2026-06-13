"""RAG layer: embedding, retrieval (ChromaDB), and scenario generation.

Turns the synthetic clinical corpus into searchable vectors and uses retrieved
cases to generate fresh patient scenarios that validate against
``scenarios.schema``. See docs/architecture.md §6.
"""
