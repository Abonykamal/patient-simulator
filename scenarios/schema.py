"""Scenario schema — the validation contract for a patient.

A *scenario* is the full truth of a simulated patient: a set of clinical facts
(nodes) and the clinical associations between them (edges), plus identity fields
for the encounter. Both hand-authored files and (later) LLM-generated JSON must
validate against these models before anything turns them into a live graph.

Design (ADR-017):
- **Core fields are strict.** ``ScenarioNode`` forbids unknown top-level fields,
  so a typo like ``importnce`` fails at load instead of silently vanishing. The
  system's own logic depends only on these validated core fields.
- **One open bag.** ``metadata`` is a free-form dict for per-scenario richness
  (a cardiac case's troponin, a neuro case's GCS) so new specialties need no
  schema change. Rule: core logic never branches on ``metadata`` — it is for
  display, LLM context, and agent flavour only.
- **Structural integrity is enforced once, here.** ``Scenario`` rejects
  duplicate node ids and dangling edges (an edge referencing a missing node),
  so the builder and every later traversal can assume a sound graph.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

# Categories drive how the state-graph summary groups facts for the LLM. Kept as
# a closed set so an unrecognized category is a load-time error, not a silently
# mis-grouped node.
NodeCategory = Literal[
    "symptom",
    "history",
    "hidden",
    "emotional",
    "social",
    "medication",
    "family_history",
]

# How clinically important uncovering this fact is. Consumed by the process-based
# rubric in Phase 7; carried (not read) now so authored files are complete.
Importance = Literal["critical", "relevant", "minor"]

# How readily the patient gives this fact up. Lets a scenario author mark
# sensitive facts (substance use, non-adherence) as hard to extract; the patient
# agent (Phase 4) honours it in its prompt. Optional — most nodes don't set it.
DisclosureDifficulty = Literal[
    "volunteered",
    "if_asked",
    "only_if_asked_directly",
    "only_if_trust_built",
]


class ScenarioNode(BaseModel):
    """One clinical fact about the patient.

    The five core fields below are what the router, graph summary, and rubric
    rely on, so they are strictly validated (``extra="forbid"``). Per-scenario
    extras go in ``metadata``, never as loose top-level keys.
    """

    model_config = ConfigDict(extra="forbid")

    id: str  # stable handle the agent's revealed_nodes[] refers to
    label: str  # short speakable text ("crushing chest pain")
    category: NodeCategory
    revealed: bool = False
    importance: Importance = "relevant"
    detail: str | None = None  # longer text the agent can elaborate when pressed
    disclosure_difficulty: DisclosureDifficulty | None = None
    metadata: dict[str, Any] = {}  # open bag — see module docstring


class ScenarioEdge(BaseModel):
    """A clinical association between two nodes (undirected; see ADR-018).

    ``relation`` labels the association ("risk_factor", "radiates_to"). A list is
    allowed when a single pair is related in more than one way, avoiding the need
    for parallel edges / a MultiGraph.
    """

    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    relation: str | list[str] | None = None


class Scenario(BaseModel):
    """A complete, validated patient scenario."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    scenario_name: str
    patient_name: str
    scenario_intro: str
    nodes: list[ScenarioNode]
    edges: list[ScenarioEdge] = []

    @model_validator(mode="after")
    def _check_graph_integrity(self) -> Scenario:
        """Reject duplicate node ids and edges pointing at missing nodes.

        Enforced here, once, so the builder and all later traversal can trust the
        graph is sound. A dangling edge names the offending id in the error so a
        scenario author (or the Phase 3 generator's output) can be fixed fast.
        """
        ids = [n.id for n in self.nodes]
        seen: set[str] = set()
        duplicates = {i for i in ids if i in seen or seen.add(i)}
        if duplicates:
            raise ValueError(f"duplicate node ids: {sorted(duplicates)}")

        known = set(ids)
        for edge in self.edges:
            for endpoint in (edge.source, edge.target):
                if endpoint not in known:
                    raise ValueError(f"edge references nonexistent node id: {endpoint!r}")
        return self


def load_scenario(path: str | Path) -> Scenario:
    """Read a scenario JSON file and validate it into a ``Scenario``.

    Args:
        path: Path to a scenario ``.json`` file.

    Returns:
        The validated scenario.

    Raises:
        pydantic.ValidationError: if the file violates the schema.
        FileNotFoundError / json.JSONDecodeError: on read/parse failure.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Scenario.model_validate(data)
