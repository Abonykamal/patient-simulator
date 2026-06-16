"""Render an agent's ``context`` string from injected, typed objects.

This is the pure heart of the memory layer (design D6). It owns the per-agent
slice *policy* (which categories each agent may see — ADR-024/ADR-028) and the
labelled layout: state slice -> patient-only rapport line -> recent turns. The
graph supplies the generic ``facts()`` *mechanism*; this module decides policy and
presentation. No DB, no LLM — it is handed everything it needs.

The output is the string the agent drops between its persona and the student's
message (the agent emits persona + message itself, so this never includes them).
"""

from __future__ import annotations

from pydantic import BaseModel

from src.core.config import TRUST_MAX
from src.state.graph import PatientStateGraph

# Slice policy: agent -> visible categories (None = all). The literal encoding of
# ADR-024. Lives here, in the agent-aware layer, so the graph stays agent-agnostic.
_SLICE_POLICY: dict[str, set[str] | None] = {
    "patient": None,
    "nurse": {"symptom", "history", "medication", "family_history"},
    "family": {"social", "emotional", "family_history"},
}

# The header that frames each agent's slice (and tells it what the markers mean).
_SLICE_LABEL: dict[str, str] = {
    "patient": "WHAT YOU KNOW ABOUT YOURSELF (your full truth; [revealed] = already told the student):",
    "nurse": "WHAT IS DOCUMENTED IN THE CHART:",
    "family": "WHAT YOU KNOW AND HAVE OBSERVED:",
}


class HistoryTurn(BaseModel):
    """One prior turn as the memory layer consumes it.

    Framework-free (not a SQLAlchemy row), so the memory layer never imports
    ``db.models``. ``speaker`` drives the rendered label; ``addressed_to`` lets the
    manager thread a student turn to the right agent.
    """

    speaker: str
    content: str
    addressed_to: str | None = None


def _render_slice(agent_name: str, graph: PatientStateGraph) -> str:
    """Render the agent's visible facts, grouped by category, with state markers."""
    facts = graph.facts(_SLICE_POLICY[agent_name])
    by_category: dict[str, list] = {}
    for fact in facts:
        by_category.setdefault(fact.category, []).append(fact)

    lines = [_SLICE_LABEL[agent_name]]
    for category in sorted(by_category):
        lines.append(f"{category}:")
        for fact in by_category[category]:
            state = "revealed" if fact.revealed else "hidden"
            line = f"  - {fact.label} [{state}]"
            # Difficulty only matters to the patient's disclosure hierarchy.
            if agent_name == "patient" and fact.disclosure_difficulty:
                line += f" ({fact.disclosure_difficulty})"
            # Metadata (e.g. vitals) is the objective data the nurse reports.
            if fact.metadata:
                meta = ", ".join(f"{k}: {fact.metadata[k]}" for k in sorted(fact.metadata))
                line += f" {{{meta}}}"
            lines.append(line)
    return "\n".join(lines)


def _render_rapport(agent_name: str, trust_level: int | None) -> str | None:
    """The current rapport level — patient only; gates its sensitive disclosures."""
    if agent_name != "patient" or trust_level is None:
        return None
    return f"CURRENT RAPPORT WITH THIS STUDENT: {trust_level} / {TRUST_MAX}"


def _render_turns(agent_name: str, thread_turns: list[HistoryTurn]) -> str:
    """Render the recent thread; the agent's own turns are labelled "you"."""
    if not thread_turns:
        return "CONVERSATION SO FAR: (nothing said yet)"
    lines = ["CONVERSATION SO FAR (most recent last):"]
    for turn in thread_turns:
        # Per-agent threading guarantees only this agent + the student appear.
        speaker = "you" if turn.speaker == agent_name else "student"
        lines.append(f"{speaker}: {turn.content}")
    return "\n".join(lines)


def render_context(
    agent_name: str,
    graph: PatientStateGraph,
    thread_turns: list[HistoryTurn],
    trust_level: int | None,
) -> str:
    """Assemble the labelled context block for ``agent_name`` (design D6).

    Args:
        agent_name: patient | nurse | family.
        graph: the live state graph (full truth; sliced here by policy).
        thread_turns: this agent's recent turns, already filtered + windowed.
        trust_level: current rapport (patient only); None omits the rapport line.

    Returns:
        The context string inserted between the agent's persona and the message.
    """
    blocks = [_render_slice(agent_name, graph)]
    rapport = _render_rapport(agent_name, trust_level)
    if rapport is not None:
        blocks.append(rapport)
    blocks.append(_render_turns(agent_name, thread_turns))
    return "\n\n".join(blocks)
