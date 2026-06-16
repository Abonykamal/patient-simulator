"""Memory coordinator — the layer's public API for the orchestrator (Phase 6).

Given an agent and the already-fetched session data (typed, injected — never a DB
session), it filters to that agent's per-agent thread (D2), windows it to the last
``RECENT_EXCHANGES_N`` exchanges (D6), and delegates rendering to context_builder.
It also hosts the trust clamp. Pure and I/O-free, so it unit-tests with plain
objects and no database.
"""

from __future__ import annotations

from src.core.config import RECENT_EXCHANGES_N, TRUST_MAX, TRUST_MIN
from src.memory.context_builder import HistoryTurn, render_context
from src.state.graph import PatientStateGraph


def _in_thread(turn: HistoryTurn, agent_name: str) -> bool:
    """A turn belongs to an agent's thread if the agent spoke it, or the student
    addressed it to that agent. Other agents' turns are excluded (D2) — this is
    what stops one agent's spoken disclosures leaking into another's context."""
    return turn.speaker == agent_name or (
        turn.speaker == "student" and turn.addressed_to == agent_name
    )


def build_context(
    agent_name: str,
    graph: PatientStateGraph,
    all_turns: list[HistoryTurn],
    trust_level: int | None = None,
) -> str:
    """Build ``agent_name``'s context string from all session turns.

    Args:
        agent_name: patient | nurse | family.
        graph: the live state graph.
        all_turns: every turn so far (excluding the current message), as
            HistoryTurns; this selects the agent's own thread.
        trust_level: current rapport (patient only); None omits the rapport line.

    Returns:
        The assembled context string for the agent's prompt.
    """
    thread = [t for t in all_turns if _in_thread(t, agent_name)]
    # An exchange is ~2 turns (student msg + agent reply); keep the last N of them.
    window = thread[-(2 * RECENT_EXCHANGES_N):]
    return render_context(agent_name, graph, window, trust_level)


def apply_rapport_delta(level: int, delta: int) -> int:
    """Apply a bounded rapport nudge and clamp to [TRUST_MIN, TRUST_MAX] (ADR-027).

    Carrying a persisted level and only nudging it (rather than re-judging trust
    from scratch each turn) is what makes rapport both cheap and consistent.
    """
    return max(TRUST_MIN, min(TRUST_MAX, level + delta))
