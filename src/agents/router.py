"""Router — decides which agent answers the student's message (ADR-009).

The cheapest component by design. Two paths cost nothing: an explicitly addressed
message goes straight to that agent, and an unaddressed message defaults to the
patient (the overwhelmingly common target — Decision B). The LLM classifier fires
only when the caller explicitly asks for it (``addressed_to=AUTO``), keeping the
per-turn cost the ADR exists to avoid at zero in the common case.

The router only *resolves* who should answer; the caller invokes that agent's
``respond`` (resolve-only — Decision C). The classifier's LLM call is injected so
tests drive both paths with no real provider call.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from src.agents.base import BaseAgent

CompleteFn = Callable[[str, str], Awaitable[str]]

_AGENT_NAME = "router"

#: Sentinel for ``addressed_to`` asking the router to classify an ambiguous message.
AUTO = "auto"

_TARGETS = ("patient", "nurse", "family")

# The approved classifier prompt. Names the about-vs-to trap explicitly, defaults
# ambiguity to the patient, and demands a single word so parsing is reliable.
_CLASSIFIER_PROMPT = """\
You are routing a medical student's message to the right person in a clinical \
simulation. Three people can answer:
- patient — the person being interviewed (their own symptoms, history, feelings, life)
- nurse — clinical staff (vital signs, test results, the chart, ward observations)
- family — a relative at the bedside (how the patient has been at home, collateral history)

Decide who the student is speaking to. A message can mention a role without being \
addressed to it — "Did the nurse take his blood pressure?" is asked of the \
patient, about the nurse. Judge the intended listener, not which words appear.

If it is unclear or could be anyone, answer "patient".

Reply with exactly one word - patient, nurse, or family. No punctuation, no \
explanation.

Student message: {message}"""


class Router:
    """Resolves a student message to the agent that should answer it."""

    def __init__(
        self,
        patient: BaseAgent,
        nurse: BaseAgent,
        family: BaseAgent,
        complete_fn: CompleteFn | None = None,
    ) -> None:
        """Params:
        ``patient`` / ``nurse`` / ``family`` — the agents to route between.
        ``complete_fn`` — async ``(agent_name, prompt) -> str`` for the classifier;
            defaults to the real LLM client. Injected in tests.
        """
        self._agents = {"patient": patient, "nurse": nurse, "family": family}
        if complete_fn is None:
            from src.llm.client import complete as _complete

            complete_fn = _complete
        self._complete = complete_fn

    async def resolve(self, message: str, addressed_to: str | None = None) -> BaseAgent:
        """Return the agent that should answer ``message``.

        Args:
            message: the student's message this turn.
            addressed_to: an explicit target ("patient"/"nurse"/"family"), ``AUTO``
                to ask the LLM to classify, or ``None`` to default to the patient.

        Returns:
            The chosen agent.
        """
        if addressed_to in self._agents:
            return self._agents[addressed_to]  # explicit addressing — free
        if addressed_to == AUTO:
            return self._agents[await self._classify(message)]
        return self._agents["patient"]  # None / unknown — default to patient

    async def _classify(self, message: str) -> str:
        raw = await self._complete(_AGENT_NAME, _CLASSIFIER_PROMPT.format(message=message))
        return _parse_target(raw)


def _parse_target(raw: str) -> str:
    """Map a classifier reply to a target, defending against chatty/odd output.

    Non-default targets are checked first so an incidental "patient" in a longer
    reply does not override an intended nurse/family. Anything unrecognised falls
    back to the patient — the safe, common default."""
    words = "".join(c if c.isalpha() else " " for c in raw.lower()).split()
    for name in ("nurse", "family", "patient"):
        if name in words:
            return name
    return "patient"
