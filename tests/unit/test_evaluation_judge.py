"""Tests for src.evaluation.judge — the LLM-as-judge (injected fake, no real call).

The judge returns a per-item verdict of "asked" / "not_asked" / "not_applicable"
(the last for findings/observations that aren't real questions).
"""

import pytest

from src.evaluation.judge import Judge, JudgeError, JudgeVerdict
from src.evaluation.rubric import RubricItem

RUBRIC = [
    RubricItem(id="a", topic="chest pain radiation", importance="critical"),
    RubricItem(id="b", topic="stable vital signs", importance="relevant"),
]
TRANSCRIPT = "student: Does the pain travel anywhere?\npatient: Yes, to my arm."


def _judge_returning(reply: str):
    """A Judge whose LLM always returns ``reply``; also records the calls."""
    calls: list[tuple[str, str]] = []

    async def fake_complete(agent_name: str, prompt: str) -> str:
        calls.append((agent_name, prompt))
        return reply

    return Judge(fake_complete), calls


async def test_judge_parses_three_state_verdict_and_uses_judge_route():
    reply = (
        '{"items": [{"id": "a", "verdict": "asked"}, {"id": "b", "verdict": "not_applicable"}], '
        '"clinical_reasoning_notes": "Asked about radiation; vitals are a finding."}'
    )
    judge, calls = _judge_returning(reply)

    verdict = await judge.judge(RUBRIC, TRANSCRIPT)

    assert isinstance(verdict, JudgeVerdict)
    assert {iv.id: iv.verdict for iv in verdict.items} == {"a": "asked", "b": "not_applicable"}
    assert calls[0][0] == "judge"  # routed to the judge model (Groq, no fallback)
    assert "chest pain radiation" in calls[0][1]
    assert "Does the pain travel anywhere?" in calls[0][1]


async def test_judge_tolerates_prose_and_code_fences():
    reply = (
        "Here is my assessment:\n```json\n"
        '{"items": [{"id": "a", "verdict": "asked"}], "clinical_reasoning_notes": "ok"}\n```'
    )
    judge, _ = _judge_returning(reply)

    verdict = await judge.judge(RUBRIC, TRANSCRIPT)

    assert verdict.items[0].verdict == "asked"


async def test_judge_repairs_an_unknown_verdict_then_succeeds():
    replies = iter(
        [
            '{"items": [{"id": "a", "verdict": "maybe"}], "clinical_reasoning_notes": "x"}',
            '{"items": [{"id": "a", "verdict": "not_asked"}], "clinical_reasoning_notes": "ok"}',
        ]
    )

    async def fake_complete(agent_name: str, prompt: str) -> str:
        return next(replies)

    verdict = await Judge(fake_complete).judge(RUBRIC, TRANSCRIPT)

    assert verdict.items[0].verdict == "not_asked"


async def test_judge_raises_after_max_repairs():
    async def fake_complete(agent_name: str, prompt: str) -> str:
        return "never valid json"

    with pytest.raises(JudgeError):
        await Judge(fake_complete, max_repairs=1).judge(RUBRIC, TRANSCRIPT)
