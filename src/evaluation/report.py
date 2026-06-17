"""Score the judge's verdict and format the report — pure, no LLM (D2/D4).

The judge does the subjective part (which items were asked); this module does the
arithmetic and presentation. Keeping the score in code makes it reproducible and
unit-testable, and lets us weight by the ``importance`` the rubric carries. The
report text wraps the judge's reasoning narrative with the score and the
covered/missed lists, so it is deterministic and needs no second LLM call.
"""

from __future__ import annotations

from pydantic import BaseModel

from src.evaluation.rubric import RubricItem

# Importance → weight: a missed critical topic costs three times a missed minor one.
_WEIGHTS = {"critical": 3, "relevant": 2, "minor": 1}


class ScoredResult(BaseModel):
    """The computed grade: a 0–1 coverage score plus the covered/missed topics."""

    overall_score: float
    covered: list[str]  # topic labels the student asked about
    missed: list[str]  # topic labels the student did not ask about


def score(asked_by_id: dict[str, bool], rubric_items: list[RubricItem]) -> ScoredResult:
    """Compute weighted coverage from the judge's per-item verdicts.

    Args:
        asked_by_id: ``{rubric item id: asked}`` from the judge. A rubric item the
            judge omitted is treated as not asked (missed), never dropped.
        rubric_items: the rubric being graded against.

    Returns:
        A :class:`ScoredResult`; ``overall_score`` is Σ(weight of asked) ÷ Σ(weight
        of all), rounded to 2 dp, and 0.0 when the rubric is empty.
    """
    covered: list[str] = []
    missed: list[str] = []
    earned = 0
    total = 0
    for item in rubric_items:
        weight = _WEIGHTS.get(item.importance, 1)
        total += weight
        if asked_by_id.get(item.id, False):
            covered.append(item.topic)
            earned += weight
        else:
            missed.append(item.topic)
    overall = round(earned / total, 2) if total else 0.0
    return ScoredResult(overall_score=overall, covered=covered, missed=missed)


def format_report(scored: ScoredResult, clinical_reasoning_notes: str) -> str:
    """Render a human-readable report from the score and the judge's narrative."""
    lines = [
        "CLINICAL HISTORY-TAKING — FEEDBACK",
        "",
        f"Overall score: {scored.overall_score * 100:.0f}%",
        "",
        f"Topics covered ({len(scored.covered)}):",
    ]
    lines += [f"  - {topic}" for topic in scored.covered] or ["  (none)"]
    lines += ["", f"Topics missed ({len(scored.missed)}):"]
    lines += [f"  - {topic}" for topic in scored.missed] or ["  (none)"]
    lines += ["", "Examiner's notes:", clinical_reasoning_notes]
    return "\n".join(lines)
