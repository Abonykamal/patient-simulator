"""Serialize the patient state graph to JSON and back.

At session end the final graph is snapshotted into the ``state_snapshot_json``
SQLite column (ADR-015: the db layer just persists whatever dict it is handed —
turning the graph into that dict is this layer's job).

We use NetworkX's built-in node-link format (ADR-019) rather than rolling our
own: it is battle-tested and round-trips node/edge attributes for free. The
``edges="edges"`` argument is pinned on both calls because the keyword's default
changed across NetworkX versions and the unpinned call emits a FutureWarning —
we keep both runtime and test output pristine.
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from src.state.graph import PatientStateGraph

# Pinned so the node-link default-arg change across NetworkX versions never
# leaks a FutureWarning into our output. Both directions must use the same value.
_EDGES_KEY = "edges"


def serialize(graph: PatientStateGraph) -> dict[str, Any]:
    """Convert a state graph into a plain, JSON-serializable dict.

    Args:
        graph: the live patient state graph.

    Returns:
        A node-link dict (nodes with their attributes + edges with relation)
        safe to pass straight to ``json.dumps`` / a SQLAlchemy JSON column.
    """
    return nx.node_link_data(graph._g, edges=_EDGES_KEY)


def deserialize(data: dict[str, Any]) -> PatientStateGraph:
    """Rebuild a state graph from a node-link dict produced by ``serialize``.

    Args:
        data: a node-link dict (typically loaded from ``state_snapshot_json``).

    Returns:
        A ``PatientStateGraph`` indistinguishable from the serialized original —
        same nodes, edges, attributes, and revealed flags.
    """
    g = nx.node_link_graph(data, edges=_EDGES_KEY)
    return PatientStateGraph(g)
