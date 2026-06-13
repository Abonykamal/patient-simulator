"""Tests for src.state.builder — validated Scenario -> live PatientStateGraph.

The builder is the translator: schema guarantees the shape, the builder turns it
into the NetworkX object the session runs on. These tests prove every node's
core fields and metadata survive the translation, edges carry their relation
label, and the result behaves like the state graph the rest of the system uses.
"""

from scenarios.schema import Scenario, ScenarioEdge, ScenarioNode
from src.state.builder import build_graph
from src.state.graph import PatientStateGraph


def _scenario() -> Scenario:
    return Scenario(
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
            ),
            ScenarioNode(
                id="bp",
                label="elevated blood pressure",
                category="symptom",
                metadata={"systolic": 162, "diastolic": 98},
            ),
            ScenarioNode(id="smoking", label="smokes a pack a day", category="social"),
        ],
        edges=[ScenarioEdge(source="smoking", target="chest_pain", relation="risk_factor")],
    )


def test_build_returns_state_graph_with_all_nodes():
    graph = build_graph(_scenario())
    assert isinstance(graph, PatientStateGraph)
    assert len(graph) == 3


def test_build_preserves_core_fields_and_starts_hidden():
    graph = build_graph(_scenario())
    # Default revealed=False carried through from the schema.
    assert graph.is_revealed("chest_pain") is False
    # The grouped summary reflects the authored labels and categories.
    summary = graph.summary()
    assert "crushing chest pain" in summary
    assert "social" in summary


def test_build_preserves_metadata_bag():
    graph = build_graph(_scenario())
    # The open bag must ride along untouched for downstream LLM context.
    assert graph._g.nodes["bp"]["metadata"] == {"systolic": 162, "diastolic": 98}


def test_build_preserves_edges_with_relation():
    graph = build_graph(_scenario())
    assert graph.neighbors("chest_pain") == ["smoking"]
    assert graph._g["smoking"]["chest_pain"]["relation"] == "risk_factor"
