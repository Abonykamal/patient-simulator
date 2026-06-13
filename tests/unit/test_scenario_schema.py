"""Tests for scenarios.schema — the validation contract for patient scenarios.

The schema is the bouncer at the door: every patient (hand-authored now,
LLM-generated in Phase 3) must pass through here. The load-bearing guarantees
are (a) core fields are strict so typos fail loudly, (b) the ``metadata`` bag
stays open for per-scenario richness, and (c) the graph is structurally sound
(unique node ids, no edge pointing at a node that doesn't exist) *before* it is
ever turned into a NetworkX graph.
"""

import pytest
from pydantic import ValidationError

from scenarios.schema import Scenario, ScenarioEdge, ScenarioNode


def test_node_applies_core_defaults():
    # Only the three required fields are given; the rest default.
    node = ScenarioNode(id="chest_pain", label="crushing chest pain", category="symptom")
    assert node.revealed is False
    assert node.importance == "relevant"
    assert node.detail is None
    assert node.disclosure_difficulty is None
    assert node.metadata == {}


def test_node_rejects_unknown_core_field():
    # A typo in a core field name ("importnce") must fail, not be silently
    # swallowed — that is the whole point of strict core validation.
    with pytest.raises(ValidationError):
        ScenarioNode(id="x", label="x", category="symptom", importnce="critical")


def test_node_metadata_accepts_arbitrary_keys():
    # The open bag is how a cardiac/neuro/peds scenario carries domain-specific
    # data without a schema change. Anything goes *inside* metadata.
    node = ScenarioNode(
        id="bp",
        label="elevated blood pressure",
        category="symptom",
        metadata={"systolic": 162, "diastolic": 98, "unit": "mmHg"},
    )
    assert node.metadata["systolic"] == 162


def test_node_rejects_invalid_category():
    with pytest.raises(ValidationError):
        ScenarioNode(id="x", label="x", category="not_a_real_category")


def test_edge_relation_accepts_string_or_list():
    single = ScenarioEdge(source="a", target="b", relation="radiates_to")
    multi = ScenarioEdge(source="a", target="b", relation=["risk_factor", "raises_anxiety"])
    assert single.relation == "radiates_to"
    assert multi.relation == ["risk_factor", "raises_anxiety"]


def _two_nodes():
    return [
        ScenarioNode(id="chest_pain", label="chest pain", category="symptom"),
        ScenarioNode(id="smoking", label="smokes a pack a day", category="social"),
    ]


def test_scenario_parses_with_valid_nodes_and_edges():
    scenario = Scenario(
        scenario_id="chest_pain",
        scenario_name="Acute Chest Pain",
        patient_name="John Doe",
        scenario_intro="A 58-year-old man clutching his chest.",
        nodes=_two_nodes(),
        edges=[ScenarioEdge(source="smoking", target="chest_pain", relation="risk_factor")],
    )
    assert len(scenario.nodes) == 2
    assert scenario.edges[0].source == "smoking"


def test_scenario_rejects_duplicate_node_ids():
    dupes = [
        ScenarioNode(id="chest_pain", label="chest pain", category="symptom"),
        ScenarioNode(id="chest_pain", label="again", category="symptom"),
    ]
    with pytest.raises(ValidationError, match="duplicate"):
        Scenario(
            scenario_id="s",
            scenario_name="S",
            patient_name="P",
            scenario_intro="i",
            nodes=dupes,
            edges=[],
        )


def test_scenario_rejects_dangling_edge():
    # Edge target "nonexistent" has no matching node — must fail at load, not
    # surface as a mysterious crash when the graph is built or traversed.
    with pytest.raises(ValidationError, match="nonexistent"):
        Scenario(
            scenario_id="s",
            scenario_name="S",
            patient_name="P",
            scenario_intro="i",
            nodes=_two_nodes(),
            edges=[ScenarioEdge(source="chest_pain", target="nonexistent")],
        )
