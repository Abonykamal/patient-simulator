"""Conversation summariser — deferred (design D5).

The structured stores cover the MVP: the graph's [revealed] flags capture what is
disclosed and the persisted trust_level captures the rapport arc, so no prose
recap is injected. This slot is preserved so the layer's shape is complete; wire
in a real summariser only if a live session overflows the window or needs early
non-factual recall. See docs/specs/2026-06-16-memory-context-layer-design.md.
"""

from __future__ import annotations


def summarize(*args, **kwargs) -> str:  # pragma: no cover - deferred
    """Not implemented for the MVP — see the module docstring (design D5)."""
    raise NotImplementedError("Conversation summarization is deferred (design D5).")
