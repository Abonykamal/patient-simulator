"""The LLM-as-judge (ADR-032). Reads the transcript, grades the questioning.

A stronger model (``agent_name="judge"`` → Groq/Llama-70B, no fallback per
AGENT_CONFIG) classifies each rubric item asked/not-asked and writes a reasoning
narrative. It does only the subjective part; the score and report are computed in
code (report.py). The LLM call is injected so tests drive it with canned replies
and never hit a provider — and like the agents it validates-and-repairs, re-asking
with the exact error when a reply is unparseable.

The prompt is the wording approved with the user: process-based (grade asking, not
the patient's answers), "asked" requires a student utterance explicitly seeking the
info (incl. clinical paraphrase), evidence may never be inferred from the patient's
reply, feedback names strongest coverage + highest-priority gaps, valid JSON only.
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable

from pydantic import BaseModel, ValidationError

from src.evaluation.rubric import RubricItem

# Mirror of llm.client.complete's signature, injected so tests don't hit a provider.
CompleteFn = Callable[[str, str], Awaitable[str]]

_AGENT_NAME = "judge"


class JudgeError(RuntimeError):
    """Raised when the judge cannot produce a valid verdict within the allowed
    repair attempts. Carries the last failure for debugging."""


class ItemVerdict(BaseModel):
    """The judge's call on one rubric item: was this topic asked about?"""

    id: str
    asked: bool


class JudgeVerdict(BaseModel):
    """The judge's structured output: a per-item verdict + a reasoning narrative."""

    items: list[ItemVerdict]
    clinical_reasoning_notes: str


# The approved judge prompt. ``{rubric}`` / ``{transcript}`` are substituted by
# str.replace (not .format) because the JSON example below contains literal braces.
_JUDGE_PROMPT = """\
You are an experienced clinical examiner assessing a medical student's
history-taking interview. The student interviewed a simulated patient and could
also question a nurse and a family member. Grade the student's QUESTIONING — not
the patient's answers.

Grade by PROCESS, not content. Each rubric item names a piece of this patient's
history; credit the student for ASKING about that topic, whatever the patient
said. Rules:
- Mark an item "asked" only when a student utterance explicitly seeks the
  information that item represents — directly or through clinically standard
  equivalent phrasing or a recognised paraphrase (e.g. "Does the pain travel
  anywhere?" satisfies a radiation item; "Do you use tobacco?" satisfies a
  smoking item).
- The evidence MUST appear in a line spoken by the student. Never infer that a
  question was asked from the patient's reply: if the patient mentions something
  the student never explicitly asked about, that item is NOT asked.
- Do not require the patient to confirm anything — a question the patient denied
  or deflected still counts as asked.

RUBRIC — the topics a good student should have asked about (id, topic, importance):
{rubric}

TRANSCRIPT — the encounter. Grade ONLY lines labelled "student:"; the other lines
are context:
{transcript}

For every rubric item decide whether the student asked about it. Then write 2-4
sentences of clinical-reasoning feedback naming (1) the student's strongest areas
of coverage and (2) the highest-priority topics missed — prioritise items marked
"critical". Be specific and constructive.

Output VALID JSON ONLY — no markdown, no code fences, no extra keys. Use exactly
this shape, one entry per rubric item, with the ids above:
{"items": [{"id": "<rubric id>", "asked": true or false}], "clinical_reasoning_notes": "<2-4 sentences>"}"""


class Judge:
    """The end-of-session LLM-as-judge."""

    def __init__(self, complete_fn: CompleteFn | None = None, *, max_repairs: int = 2) -> None:
        """Params:
        ``complete_fn`` — async ``(agent_name, prompt) -> str``; defaults to the real
            LLM client. Injected in tests.
        ``max_repairs`` — how many times to re-ask on an invalid reply.
        """
        if complete_fn is None:
            from src.llm.client import complete as _complete

            complete_fn = _complete
        self._complete = complete_fn
        self._max_repairs = max_repairs

    async def judge(self, rubric_items: list[RubricItem], transcript: str) -> JudgeVerdict:
        """Grade ``transcript`` against ``rubric_items``.

        Args:
            rubric_items: the topics to grade (from ``rubric.build_rubric``).
            transcript: the rendered encounter ("student:"/"patient:"/… lines).

        Returns:
            A validated :class:`JudgeVerdict`.

        Raises:
            JudgeError: if no valid verdict is produced within the repair budget.
        """
        prompt = self._build_prompt(rubric_items, transcript)

        last_error: Exception | None = None
        for _ in range(self._max_repairs + 1):
            raw = await self._complete(_AGENT_NAME, prompt)
            try:
                return _parse(raw)
            except (ValueError, ValidationError) as exc:
                last_error = exc
                prompt = self._build_repair_prompt(rubric_items, transcript, raw, exc)

        raise JudgeError(
            f"no valid verdict after {self._max_repairs + 1} attempts; last error: {last_error}"
        )

    def _build_prompt(self, rubric_items: list[RubricItem], transcript: str) -> str:
        rubric = "\n".join(f"- [{i.id}] {i.topic} ({i.importance})" for i in rubric_items)
        return _JUDGE_PROMPT.replace("{rubric}", rubric).replace("{transcript}", transcript)

    def _build_repair_prompt(
        self, rubric_items: list[RubricItem], transcript: str, bad_output: str, error: Exception
    ) -> str:
        return f"""\
{self._build_prompt(rubric_items, transcript)}

Your previous reply was REJECTED because it was not valid:
{error}

Your previous reply was:
{bad_output}

Return a corrected JSON object that fixes the error above. Output ONLY the JSON."""


def _extract_json(raw: str) -> dict:
    """Pull the JSON object out of a reply, tolerating prose/code fences."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return json.loads(raw[start : end + 1])  # JSONDecodeError is a ValueError


def _parse(raw: str) -> JudgeVerdict:
    return JudgeVerdict.model_validate(_extract_json(raw))
