"""BaseAgent — the shared machinery every persona reuses (ADR-010).

All three personas (patient, nurse, family) do the same four things:

1. **Assemble** a prompt from the injected conversation *context* (built by the
   memory layer in Phase 5; injected here so agents stay pure), the subclass's
   *persona*, and the student's message.
2. **Call** the LLM via ``llm.client.complete`` — injected as ``complete_fn`` so
   tests drive the loop with a fake and never hit a provider.
3. **Parse / validate / repair** the reply into an :class:`AgentResponse`.
4. **Return** it. The agent never writes to the state graph; it *reports*
   ``revealed_nodes`` and the caller applies ``mark_revealed`` (whose existing
   guard drops hallucinated ids).

Subclasses fill two hooks only — their persona prompt and their graph slice —
which is the template-method shape we settled on (decision A).
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable

from pydantic import BaseModel, ValidationError

# Mirror of llm.client.complete's signature, injected so tests don't hit a provider.
CompleteFn = Callable[[str, str], Awaitable[str]]


class AgentResponseError(RuntimeError):
    """Raised when an agent cannot produce a valid AgentResponse within the
    allowed number of repair attempts. Carries the last failure for debugging."""


class AgentResponse(BaseModel):
    """The structured output every agent returns (ADR-010).

    ``revealed_nodes`` are node ids the agent says it disclosed this turn; the
    caller passes them to ``PatientStateGraph.mark_revealed``. ``emotional_state``
    is a short label feeding the conversation arc and final evaluation.
    """

    response_text: str
    revealed_nodes: list[str] = []
    emotional_state: str


class BaseAgent:
    """Template-method base for the patient/nurse/family agents."""

    #: Key into AGENT_CONFIG; set by each concrete subclass.
    agent_name: str

    def __init__(self, complete_fn: CompleteFn | None = None, *, max_repairs: int = 2) -> None:
        """Params:
        ``complete_fn`` — async ``(agent_name, prompt) -> str``; defaults to the
            real LLM client. Injected in tests.
        ``max_repairs`` — how many times to re-prompt on an invalid reply.
        """
        if complete_fn is None:
            # Lazy import so importing this module never pulls in a provider.
            from src.llm.client import complete as _complete

            complete_fn = _complete
        self._complete = complete_fn
        self._max_repairs = max_repairs

    # --- hooks for subclasses --------------------------------------------------

    def _persona(self) -> str:
        """Return the persona instructions for this agent. Overridden per agent."""
        raise NotImplementedError

    # --- pipeline --------------------------------------------------------------

    async def respond(self, message: str, context: str) -> AgentResponse:
        """Produce this agent's reply to ``message`` given conversation ``context``.

        Args:
            message: the student's message this turn.
            context: pre-assembled context (state summary, recent turns, persona
                framing) built by the caller / memory layer.

        Returns:
            A validated :class:`AgentResponse`.
        """
        prompt = self._build_prompt(message, context)

        last_error: Exception | None = None
        for _ in range(self._max_repairs + 1):
            raw = await self._complete(self.agent_name, prompt)
            try:
                return _parse_response(raw)
            except (ValueError, ValidationError) as exc:
                # ValueError = unparseable JSON; ValidationError = schema miss.
                # Fold the error back into the prompt and try again.
                last_error = exc
                prompt = self._build_repair_prompt(message, context, raw, exc)

        raise AgentResponseError(
            f"no valid response after {self._max_repairs + 1} attempts; "
            f"last error: {last_error}"
        )

    def _build_prompt(self, message: str, context: str) -> str:
        return f"""\
{self._persona()}

{context}

The student says: {message}

Reply ONLY with a JSON object: {{"response_text": "...", "revealed_nodes": [...], "emotional_state": "..."}}"""

    def _build_repair_prompt(
        self, message: str, context: str, bad_output: str, error: Exception
    ) -> str:
        """Re-ask the model, showing it exactly why its last reply was rejected."""
        return f"""\
{self._build_prompt(message, context)}

Your previous reply was REJECTED because it was not valid:
{error}

Your previous reply was:
{bad_output}

Return a corrected JSON object that fixes the error above. Output ONLY the JSON."""


def _extract_json(raw: str) -> dict:
    """Pull the JSON object out of a model reply, tolerating prose/code fences."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return json.loads(raw[start : end + 1])  # JSONDecodeError is a ValueError


def _parse_response(raw: str) -> AgentResponse:
    """Extract JSON from a raw reply and validate it into an AgentResponse."""
    return AgentResponse.model_validate(_extract_json(raw))
