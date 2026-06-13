"""Tests for the authored chest_pain.json scenario.

This guards the real data file the same way the schema guards generated JSON: it
must validate, exercise the optional fields and metadata bag we designed, and
build into a working graph. If a future edit introduces a dangling edge or a bad
category, this fails immediately instead of at session start.
"""

from pathlib import Path

from scenarios.schema import load_scenario
from src.state.builder import build_graph

CHEST_PAIN = Path("scenarios/chest_pain.json")


def test_chest_pain_file_validates():
    scenario = load_scenario(CHEST_PAIN)
    assert scenario.scenario_id == "chest_pain"
    assert scenario.patient_name == "John Doe"
    assert len(scenario.nodes) >= 10  # a clinically rich patient, not a toy


def test_chest_pain_exercises_optional_fields_and_metadata():
    scenario = load_scenario(CHEST_PAIN)
    by_id = {n.id: n for n in scenario.nodes}
    # A hidden, hard-to-disclose precipitant — the design's whole point.
    assert by_id["cocaine_use"].category == "hidden"
    assert by_id["cocaine_use"].disclosure_difficulty == "only_if_trust_built"
    # The metadata bag carries objective vitals without a schema change.
    assert by_id["elevated_bp"].metadata["systolic"] == 162


def test_chest_pain_builds_into_a_graph_that_starts_fully_hidden():
    graph = build_graph(load_scenario(CHEST_PAIN))
    # Nothing is revealed until the student uncovers it.
    assert graph.revealed_ids() == []
    # The critical chest_pain node is associated with its radiation/risk nodes.
    assert "radiation" in graph.neighbors("chest_pain")
    assert "smoking" in graph.neighbors("chest_pain")
