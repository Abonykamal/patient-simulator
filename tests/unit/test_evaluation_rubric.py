"""Tests for src.evaluation.rubric — clinically-weighted nodes → rubric items.

Only ``critical``/``relevant`` nodes are graded; ``minor`` incidental colour is
excluded. Whether a kept item is actually an askable question (vs a finding) is
decided downstream by the judge, not here (ADR-032).
"""

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


def test_build_rubric_keeps_critical_and_relevant_in_order():
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
        ]
    )
    assert build_rubric(sc) == [
        RubricItem(id="sym_pain", topic="chest pain", importance="critical"),
        RubricItem(id="hist_smoke", topic="smoking history", importance="relevant"),
    ]


def test_build_rubric_excludes_minor_incidental_nodes():
    # Minor "incidental colour" stays in the graph for realism but isn't graded.
    sc = _scenario(
        [
            {
                "id": "sym_pain",
                "label": "chest pain",
                "category": "symptom",
                "importance": "critical",
            },
            {
                "id": "soc_job",
                "label": "works as a hairdresser",
                "category": "social",
                "importance": "minor",
            },
        ]
    )
    assert [item.id for item in build_rubric(sc)] == ["sym_pain"]


def test_build_rubric_uses_schema_default_importance():
    # A node with no explicit importance takes the schema default ("relevant").
    sc = _scenario([{"id": "n1", "label": "a topic", "category": "symptom"}])
    assert build_rubric(sc) == [RubricItem(id="n1", topic="a topic", importance="relevant")]
