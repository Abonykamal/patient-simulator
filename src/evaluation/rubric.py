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


# Only clinically weighted topics are graded. "minor" nodes are incidental colour
# (occupation, living situation) — they stay in the graph so the patient can mention
# them (realism), but the student is not marked on eliciting them (live runs showed
# minor nodes like "hairdresser"/"lives alone" cluttering the report). Findings and
# observations that aren't real questions ("stable vital signs", "downplaying
# symptoms") are filtered later, by the judge, as ``not_applicable`` (ADR-032).
_GRADED_IMPORTANCE = {"critical", "relevant"}


class RubricItem(BaseModel):
    """One gradeable topic: a node's id, its label as the topic, and its weight."""

    id: str  # the node id (stable handle the judge's verdict refers to)
    topic: str  # the node label — the thing a good student should have asked about
    importance: str  # critical | relevant — drives the score weight (minor is not graded)


def build_rubric(scenario: Scenario) -> list[RubricItem]:
    """Turn a scenario's clinically-weighted nodes into rubric items, in node order.

    Only ``critical`` and ``relevant`` nodes are included; ``minor`` incidental
    facts are excluded (they stay in the graph for realism — see module note).
    Whether a kept item is actually an askable question (vs a finding/observation)
    is decided downstream by the judge (``not_applicable``), keeping that judgement
    off the generator.

    Args:
        scenario: a validated scenario.

    Returns:
        One :class:`RubricItem` per graded node, in the scenario's node order.
    """
    return [
        RubricItem(id=node.id, topic=node.label, importance=node.importance)
        for node in scenario.nodes
        if node.importance in _GRADED_IMPORTANCE
    ]
