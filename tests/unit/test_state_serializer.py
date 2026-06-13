"""Tests for src.state.serializer — graph <-> JSON for the SQLite snapshot.

The contract is round-trip fidelity: a graph serialized and rebuilt must be
indistinguishable from the original, revealed flags and edge relations included.
The output must also be plain-JSON-serializable, because it lands in the
``state_snapshot_json`` column at session end.
"""

import json
import warnings

from scenarios.schema import Scenario, ScenarioEdge, ScenarioNode
from src.state.builder import build_graph
from src.state.serializer import deserialize, serialize


def _graph_with_progress():
    scenario = Scenario(
        scenario_id="chest_pain",
        scenario_name="Acute Chest Pain",
        patient_name="John Doe",
        scenario_intro="A 58-year-old man clutching his chest.",
        nodes=[
            ScenarioNode(
                id="chest_pain",
                label="crushing chest pain",
                category="symptom",
                importance="critical",
                metadata={"onset": "2h ago"},
            ),
            ScenarioNode(id="smoking", label="smokes a pack a day", category="social"),
        ],
        edges=[ScenarioEdge(source="smoking", target="chest_pain", relation="risk_factor")],
    )
    graph = build_graph(scenario)
    graph.mark_revealed(["chest_pain"])  # mid-session progress to preserve
    return graph


def test_serialize_output_is_plain_json():
    data = serialize(_graph_with_progress())
    # Must survive json.dumps unchanged — it is stored in a JSON column.
    assert json.loads(json.dumps(data)) == data


def test_roundtrip_preserves_nodes_edges_and_revealed_state():
    original = _graph_with_progress()
    restored = deserialize(serialize(original))

    assert len(restored) == len(original)
    assert restored.revealed_ids() == original.revealed_ids()
    assert restored.is_revealed("chest_pain") is True
    assert restored.is_revealed("smoking") is False
    assert restored.summary() == original.summary()


def test_roundtrip_preserves_metadata_and_edge_relation():
    restored = deserialize(serialize(_graph_with_progress()))
    assert restored._g.nodes["chest_pain"]["metadata"] == {"onset": "2h ago"}
    assert restored._g["smoking"]["chest_pain"]["relation"] == "risk_factor"


def test_serialize_emits_no_warnings():
    # NetworkX's node-link helpers warn on a default-arg change across versions;
    # the serializer must pin the call so test/runtime output stays pristine.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        deserialize(serialize(_graph_with_progress()))
