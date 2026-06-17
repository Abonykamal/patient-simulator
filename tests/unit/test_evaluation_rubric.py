"""Tests for src.evaluation.rubric — scenario nodes → gradeable rubric items (D1)."""

from scenarios.schema import Scenario
from src.evaluation.rubric import RubricItem, build_rubric


def _scenario(nodes) -> Scenario:
    return Scenario(
        scenario_id="sc1",
        scenario_name="X",
        patient_name="Mr Adams",
        scenario_intro="intro",
        nodes=nodes,
    )


def test_build_rubric_maps_each_node_to_an_item_preserving_order():
    sc = _scenario(
        [
            {
                "id": "sym_pain",
                "label": "chest pain",
                "category": "symptom",
                "importance": "critical",
            },
            {
                "id": "hist_smoke",
                "label": "smoking history",
                "category": "history",
                "importance": "relevant",
            },
            {
                "id": "soc_job",
                "label": "works as an accountant",
                "category": "social",
                "importance": "minor",
            },
        ]
    )
    assert build_rubric(sc) == [
        RubricItem(id="sym_pain", topic="chest pain", importance="critical"),
        RubricItem(id="hist_smoke", topic="smoking history", importance="relevant"),
        RubricItem(id="soc_job", topic="works as an accountant", importance="minor"),
    ]


def test_build_rubric_uses_schema_default_importance():
    # A node with no explicit importance takes the schema default ("relevant").
    sc = _scenario([{"id": "n1", "label": "a topic", "category": "symptom"}])
    assert build_rubric(sc) == [RubricItem(id="n1", topic="a topic", importance="relevant")]
