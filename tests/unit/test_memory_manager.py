"""Tests for src.memory.manager — the layer's public API for the orchestrator.

The manager filters all session turns down to one agent's thread (per-agent
threading, D2), windows it to the last few exchanges (D6), delegates rendering to
context_builder, and hosts the trust clamp. Pure and I/O-free — fed typed objects.
"""

import networkx as nx

from src.memory.context_builder import HistoryTurn
from src.state.graph import PatientStateGraph


def _graph():
    g = nx.Graph()
    g.add_node(
        "a",
        label="chest pain",
        category="symptom",
        revealed=False,
        disclosure_difficulty=None,
        metadata={},
    )
    return PatientStateGraph(g)


def test_build_context_keeps_only_this_agents_thread():
    from src.memory.manager import build_context

    turns = [
        HistoryTurn(speaker="student", content="patient question", addressed_to="patient"),
        HistoryTurn(speaker="patient", content="patient answer"),
        HistoryTurn(speaker="student", content="nurse question", addressed_to="nurse"),
        HistoryTurn(speaker="nurse", content="nurse answer"),
    ]
    out = build_context("patient", _graph(), turns, trust_level=1)
    assert "patient question" in out
    assert "patient answer" in out
    assert "nurse question" not in out
    assert "nurse answer" not in out


def test_build_context_windows_to_last_2N_turns():
    from src.core.config import RECENT_EXCHANGES_N
    from src.memory.manager import build_context

    turns = [
        HistoryTurn(speaker="student", content=f"q{i}", addressed_to="patient")
        for i in range(2 * RECENT_EXCHANGES_N + 4)  # more than the window
    ]
    out = build_context("patient", _graph(), turns, trust_level=1)
    assert "q0" not in out  # oldest dropped
    assert f"q{2 * RECENT_EXCHANGES_N + 3}" in out  # newest kept


def test_apply_rapport_delta_clamps_to_bounds():
    from src.memory.manager import apply_rapport_delta

    assert apply_rapport_delta(2, 1) == 3
    assert apply_rapport_delta(3, 1) == 3  # clamped at TRUST_MAX
    assert apply_rapport_delta(0, -1) == 0  # clamped at TRUST_MIN
    assert apply_rapport_delta(1, 0) == 1


def test_summarizer_is_deferred():
    import pytest

    from src.memory import summarizer

    with pytest.raises(NotImplementedError):
        summarizer.summarize()
