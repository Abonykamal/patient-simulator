"""Tests for src.state.graph — the live patient state during a session.

``PatientStateGraph`` wraps a NetworkX graph whose nodes carry the validated
core fields (label, category, revealed). These tests pin the verbs the rest of
the system depends on: flipping nodes to revealed (idempotently, and reporting
only what newly changed), answering "is this revealed?", listing neighbours
(the association edges), and producing the grouped text summary the memory layer
feeds into the LLM prompt.
"""

import networkx as nx
import pytest

from src.state.graph import PatientStateGraph


def _sample_graph() -> PatientStateGraph:
    """A tiny three-node graph built directly, independent of the builder."""
    g = nx.Graph()
    g.add_node("chest_pain", label="chest pain", category="symptom", revealed=False)
    g.add_node("radiation", label="pain radiates to left arm", category="symptom", revealed=False)
    g.add_node("smoking", label="smokes a pack a day", category="social", revealed=False)
    g.add_edge("chest_pain", "radiation", relation="radiates_to")
    g.add_edge("smoking", "chest_pain", relation="risk_factor")
    return PatientStateGraph(g)


def test_len_is_node_count():
    assert len(_sample_graph()) == 3


def test_nodes_start_hidden():
    graph = _sample_graph()
    assert graph.is_revealed("chest_pain") is False
    assert graph.revealed_ids() == []


def test_mark_revealed_flips_and_reports_newly_revealed():
    graph = _sample_graph()
    newly = graph.mark_revealed(["chest_pain", "radiation"])
    assert set(newly) == {"chest_pain", "radiation"}
    assert graph.is_revealed("chest_pain") is True
    assert set(graph.revealed_ids()) == {"chest_pain", "radiation"}


def test_mark_revealed_is_idempotent():
    graph = _sample_graph()
    graph.mark_revealed(["chest_pain"])
    # Marking it again reveals nothing new — only first-time flips are reported.
    assert graph.mark_revealed(["chest_pain"]) == []


def test_mark_revealed_ignores_unknown_ids():
    # The agent's structured output could name a node that doesn't exist (LLM
    # hallucination). That must not crash the session — unknown ids are skipped,
    # and only the real flip is reported.
    graph = _sample_graph()
    newly = graph.mark_revealed(["chest_pain", "ghost_node"])
    assert newly == ["chest_pain"]


def test_is_revealed_raises_on_unknown_node():
    # Querying a node that doesn't exist is a programming error, not LLM output —
    # so it is surfaced loudly, unlike mark_revealed.
    with pytest.raises(KeyError):
        _sample_graph().is_revealed("ghost_node")


def test_neighbors_returns_associated_nodes():
    graph = _sample_graph()
    assert set(graph.neighbors("chest_pain")) == {"radiation", "smoking"}


def test_summary_groups_by_category_and_marks_revealed_state():
    graph = _sample_graph()
    graph.mark_revealed(["chest_pain"])
    summary = graph.summary()
    # Grouped by category heading.
    assert "symptom" in summary.lower()
    assert "social" in summary.lower()
    # The revealed fact is shown as revealed; the hidden ones as hidden.
    assert "chest pain" in summary
    assert "revealed" in summary.lower()
    assert "hidden" in summary.lower()


def _facts_graph() -> PatientStateGraph:
    """A graph whose nodes carry difficulty + metadata, for the facts() accessor."""
    g = nx.Graph()
    g.add_node(
        "chest_pain",
        label="chest pain",
        category="symptom",
        revealed=True,
        disclosure_difficulty=None,
        metadata={"bp": "162/94"},
    )
    g.add_node(
        "cocaine",
        label="cocaine use",
        category="hidden",
        revealed=False,
        disclosure_difficulty="only_if_trust_built",
        metadata={},
    )
    return PatientStateGraph(g)


def test_facts_returns_all_when_no_filter():
    cats = {f.category for f in _facts_graph().facts()}
    assert cats == {"symptom", "hidden"}


def test_facts_filters_to_category_whitelist():
    labels = [f.label for f in _facts_graph().facts({"symptom"})]
    assert labels == ["chest pain"]


def test_facts_carries_difficulty_and_metadata():
    by_label = {f.label: f for f in _facts_graph().facts()}
    assert by_label["chest pain"].revealed is True
    assert by_label["chest pain"].metadata == {"bp": "162/94"}
    assert by_label["cocaine use"].disclosure_difficulty == "only_if_trust_built"
