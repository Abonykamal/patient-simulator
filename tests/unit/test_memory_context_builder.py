"""Tests for src.memory.context_builder — the pure per-agent context renderer.

These hand the builder a tiny in-memory state graph, a few HistoryTurns, and a
trust level, then assert on the rendered string: per-agent slicing (nurse/family
never see hidden facts), metadata surfacing for the nurse, the patient-only
rapport line, and the you/student turn labelling. No DB, no LLM.
"""

import networkx as nx

from src.state.graph import PatientStateGraph


def _graph(*nodes):
    g = nx.Graph()
    for node in nodes:
        attrs = dict(node)
        nid = attrs.pop("id")
        attrs.setdefault("revealed", False)
        attrs.setdefault("disclosure_difficulty", None)
        attrs.setdefault("metadata", {})
        g.add_node(nid, **attrs)
    return PatientStateGraph(g)


def test_patient_slice_shows_all_categories_with_difficulty_tag():
    from src.memory.context_builder import render_context

    g = _graph(
        {"id": "a", "label": "chest pain", "category": "symptom", "revealed": True},
        {
            "id": "b",
            "label": "cocaine use",
            "category": "hidden",
            "disclosure_difficulty": "only_if_trust_built",
        },
    )
    out = render_context("patient", g, [], None)
    assert "WHAT YOU KNOW ABOUT YOURSELF" in out
    assert "- chest pain [revealed]" in out
    assert "- cocaine use [hidden] (only_if_trust_built)" in out


def test_nurse_slice_excludes_hidden_and_emotional_categories():
    from src.memory.context_builder import render_context

    g = _graph(
        {"id": "a", "label": "chest pain", "category": "symptom"},
        {"id": "b", "label": "cocaine use", "category": "hidden"},
        {"id": "c", "label": "feeling scared", "category": "emotional"},
    )
    out = render_context("nurse", g, [], None)
    assert "WHAT IS DOCUMENTED" in out
    assert "chest pain" in out
    assert "cocaine use" not in out
    assert "feeling scared" not in out


def test_nurse_slice_surfaces_metadata_values():
    from src.memory.context_builder import render_context

    g = _graph(
        {
            "id": "a",
            "label": "vitals on admission",
            "category": "symptom",
            "metadata": {"bp": "162/94", "hr": 98},
        },
    )
    out = render_context("nurse", g, [], None)
    assert "bp: 162/94" in out
    assert "hr: 98" in out


def test_family_slice_is_social_emotional_family_only():
    from src.memory.context_builder import render_context

    g = _graph(
        {"id": "a", "label": "lives alone", "category": "social"},
        {"id": "b", "label": "chest pain", "category": "symptom"},
        {"id": "c", "label": "cocaine use", "category": "hidden"},
    )
    out = render_context("family", g, [], None)
    assert "lives alone" in out
    assert "chest pain" not in out
    assert "cocaine use" not in out


def test_rapport_line_appears_for_patient_only():
    from src.memory.context_builder import render_context

    g = _graph({"id": "a", "label": "chest pain", "category": "symptom"})
    patient_out = render_context("patient", g, [], 2)
    assert "CURRENT RAPPORT WITH THIS STUDENT: 2 / 3" in patient_out

    nurse_out = render_context("nurse", g, [], 2)
    assert "RAPPORT" not in nurse_out


def test_recent_turns_label_own_turns_as_you():
    from src.memory.context_builder import HistoryTurn, render_context

    g = _graph({"id": "a", "label": "chest pain", "category": "symptom"})
    turns = [
        HistoryTurn(speaker="student", content="Where is the pain?", addressed_to="patient"),
        HistoryTurn(speaker="patient", content="In my chest."),
    ]
    out = render_context("patient", g, turns, 1)
    assert "CONVERSATION SO FAR (most recent last):" in out
    assert "student: Where is the pain?" in out
    assert "you: In my chest." in out
