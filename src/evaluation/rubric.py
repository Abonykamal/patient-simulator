"""Build the grading rubric from a scenario's nodes (D1 / ADR-032).

The rubric is *derived*, not authored separately: every node is a piece of the
patient's history a good student should have asked about, already tagged with the
``importance`` carried since Phase 2 (ADR-017). This consumes that field — no new
schema field, and every dynamically-generated patient gets a rubric for free.

Process-based (ADR-011): an item describes a *topic to ask about*. The judge later
decides whether the student asked, regardless of what the patient actually said.
"""

from __future__ import annotations

from pydantic import BaseModel

from scenarios.schema import Scenario


class RubricItem(BaseModel):
    """One gradeable topic: a node's id, its label as the topic, and its weight."""

    id: str  # the node id (stable handle the judge's verdict refers to)
    topic: str  # the node label — the thing a good student should have asked about
    importance: str  # critical | relevant | minor — drives the score weight


def build_rubric(scenario: Scenario) -> list[RubricItem]:
    """Turn a scenario's nodes into rubric items, preserving node order.

    Args:
        scenario: a validated scenario.

    Returns:
        One :class:`RubricItem` per node, in the scenario's node order.
    """
    return [
        RubricItem(id=node.id, topic=node.label, importance=node.importance)
        for node in scenario.nodes
    ]
