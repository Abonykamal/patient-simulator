"""The live patient state graph for a single session.

``PatientStateGraph`` is a thin behaviour layer over a ``networkx.Graph``. The
graph holds the *full* truth of the patient (every fact, revealed or not); the
``revealed`` flag on each node tracks what the student has uncovered so far. The
class exposes only the verbs the rest of the system needs, so callers never poke
at NetworkX internals directly:

- ``mark_revealed`` — flip nodes to revealed after an agent declares them (ADR-010)
- ``is_revealed`` / ``revealed_ids`` / ``hidden_ids`` — query progress
- ``neighbors`` — the clinical associations (edges), for "related but hidden" hints
- ``summary`` — grouped text of all facts + their revealed state, for the LLM prompt

It depends on nothing of ours (no LLM, no DB) on purpose: pure data + logic means
fast, isolated tests. It is created by ``builder.build_graph`` and read by the
memory manager; agents update it via ``mark_revealed``.
"""

from __future__ import annotations

from collections.abc import Iterable

import networkx as nx


class PatientStateGraph:
    """Behaviour wrapper over a NetworkX graph of patient facts."""

    def __init__(self, graph: nx.Graph) -> None:
        """Wrap an existing NetworkX graph.

        Args:
            graph: a graph whose nodes carry at least ``label``, ``category``,
                and ``revealed`` attributes (the validated core fields the
                builder writes). Ownership transfers to this wrapper.
        """
        self._g = graph

    def __len__(self) -> int:
        """Number of nodes (clinical facts) in the graph."""
        return self._g.number_of_nodes()

    def is_revealed(self, node_id: str) -> bool:
        """Return whether ``node_id`` has been revealed.

        Raises:
            KeyError: if the node does not exist — this is a programming query,
                so an unknown id is surfaced loudly (unlike ``mark_revealed``).
        """
        if node_id not in self._g:
            raise KeyError(node_id)
        return bool(self._g.nodes[node_id]["revealed"])

    def mark_revealed(self, node_ids: Iterable[str]) -> list[str]:
        """Mark nodes as revealed; return the ids that were *newly* revealed.

        Idempotent: re-revealing an already-revealed node is a no-op and is not
        reported. Unknown ids are skipped silently rather than raised — the
        agent's structured output is LLM-generated and may name a hallucinated
        node, which must never crash a live session.

        Args:
            node_ids: ids the agent declared it revealed this turn.

        Returns:
            The subset of ids that existed and flipped from hidden to revealed,
            in input order. This is what the db layer persists per turn.
        """
        newly_revealed: list[str] = []
        for node_id in node_ids:
            if node_id not in self._g:
                continue  # hallucinated id — skip, don't crash
            if not self._g.nodes[node_id]["revealed"]:
                self._g.nodes[node_id]["revealed"] = True
                newly_revealed.append(node_id)
        return newly_revealed

    def revealed_ids(self) -> list[str]:
        """Ids of all currently-revealed nodes (sorted for determinism)."""
        return sorted(n for n, d in self._g.nodes(data=True) if d["revealed"])

    def hidden_ids(self) -> list[str]:
        """Ids of all still-hidden nodes (sorted for determinism)."""
        return sorted(n for n, d in self._g.nodes(data=True) if not d["revealed"])

    def neighbors(self, node_id: str) -> list[str]:
        """Ids clinically associated with ``node_id`` (its edge neighbours).

        Raises:
            KeyError: if the node does not exist.
        """
        if node_id not in self._g:
            raise KeyError(node_id)
        return sorted(self._g.neighbors(node_id))

    def summary(self) -> str:
        """Render the patient's facts grouped by category, marked revealed/hidden.

        This is the text the memory manager injects into an agent's prompt: it
        shows the agent the patient's full truth (so it can answer in character)
        and which facts are already out (so it stays consistent). Deterministic
        ordering — categories then ids sorted — keeps it stable and testable.
        """
        by_category: dict[str, list[tuple[str, str, bool]]] = {}
        for node_id, data in self._g.nodes(data=True):
            by_category.setdefault(data["category"], []).append(
                (node_id, data["label"], data["revealed"])
            )

        lines: list[str] = []
        for category in sorted(by_category):
            lines.append(f"{category}:")
            for _node_id, label, revealed in sorted(by_category[category]):
                state = "revealed" if revealed else "hidden"
                lines.append(f"  - {label} [{state}]")
        return "\n".join(lines)
