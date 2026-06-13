"""Build a live PatientStateGraph from a validated Scenario.

Schema (``scenarios.schema``) guarantees the *shape*; this module constructs the
runtime object. Every node attribute — core fields and the ``metadata`` bag — is
copied onto the NetworkX node so the graph is the single source of truth for the
session and serializes back losslessly. Edges carry their ``relation`` label.

It is called once per session at start (after RAG generates / a file supplies the
scenario) and produces the graph the agents and memory manager then operate on.
"""

from __future__ import annotations

import networkx as nx

from scenarios.schema import Scenario
from src.state.graph import PatientStateGraph


def build_graph(scenario: Scenario) -> PatientStateGraph:
    """Construct a ``PatientStateGraph`` from a validated scenario.

    Args:
        scenario: a schema-validated scenario (unique ids, no dangling edges are
            already guaranteed, so this function does no integrity checking).

    Returns:
        A live state graph with every node starting at its authored ``revealed``
        state (``False`` by default) and edges labelled with their relation.
    """
    g = nx.Graph()
    for node in scenario.nodes:
        # Store the full node so the graph is lossless and serialization is
        # trivial. model_dump(exclude={"id"}) keeps the id as the node key only.
        g.add_node(node.id, **node.model_dump(exclude={"id"}))
    for edge in scenario.edges:
        g.add_edge(edge.source, edge.target, relation=edge.relation)
    return PatientStateGraph(g)
