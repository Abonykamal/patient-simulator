"""Tests for src.evaluation.report — deterministic score + report text (D2/D4)."""

from src.evaluation.report import ScoredResult, format_report, score
from src.evaluation.rubric import RubricItem

RUBRIC = [
    RubricItem(id="a", topic="chest pain", importance="critical"),  # weight 3
    RubricItem(id="b", topic="smoking history", importance="relevant"),  # weight 2
    RubricItem(id="c", topic="occupation", importance="minor"),  # weight 1
]


def test_score_is_weighted_coverage():
    # asked a (3) + c (1) = 4 of total weight 6 → 0.67; covered/missed are topics.
    result = score({"a": True, "b": False, "c": True}, RUBRIC)
    assert result.overall_score == 0.67
    assert result.covered == ["chest pain", "occupation"]
    assert result.missed == ["smoking history"]


def test_score_all_asked_is_one():
    result = score({"a": True, "b": True, "c": True}, RUBRIC)
    assert result.overall_score == 1.0
    assert result.missed == []


def test_score_none_asked_is_zero():
    result = score({"a": False, "b": False, "c": False}, RUBRIC)
    assert result.overall_score == 0.0
    assert result.covered == []


def test_score_missing_verdict_id_counts_as_not_asked():
    # The judge omitted "b"; it must be treated as missed, not dropped.
    result = score({"a": True, "c": True}, RUBRIC)
    assert "smoking history" in result.missed


def test_score_empty_rubric_is_zero_not_crash():
    assert score({}, []).overall_score == 0.0


def test_format_report_includes_score_topics_and_notes():
    scored = ScoredResult(
        overall_score=0.67, covered=["chest pain", "occupation"], missed=["smoking history"]
    )
    text = format_report(scored, "Good rapport; should have asked about smoking.")
    assert "67%" in text
    assert "chest pain" in text and "smoking history" in text
    assert "Good rapport" in text
