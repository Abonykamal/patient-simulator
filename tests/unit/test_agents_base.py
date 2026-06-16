"""Tests for the BaseAgent machinery (Phase 4, ADR-010).

BaseAgent owns the shared agent pipeline: assemble prompt -> call the LLM ->
parse/validate/repair the JSON into an AgentResponse. The LLM is injected
(``complete_fn``) so these tests drive the whole loop with canned responses and
never touch a real provider — same discipline as the Phase 3 generator tests.
"""

from __future__ import annotations

import pytest

from src.agents.base import AgentResponse, AgentResponseError, BaseAgent


class _StubAgent(BaseAgent):
    """Minimal concrete agent: just enough to exercise the base pipeline."""

    agent_name = "patient"

    def _persona(self) -> str:
        return "You are a patient being interviewed."


class _FakeLLM:
    """Async stand-in for llm.client.complete. Replays canned responses in order
    and records every call so tests can assert on what was sent."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, agent_name: str, prompt: str) -> str:
        self.calls.append((agent_name, prompt))
        return self._responses.pop(0)


async def test_returns_validated_response() -> None:
    llm = _FakeLLM(
        [
            '{"response_text": "It hurts right here in my chest.", '
            '"revealed_nodes": ["chest_pain"], "emotional_state": "anxious"}'
        ]
    )
    agent = _StubAgent(complete_fn=llm)

    response = await agent.respond("Where does it hurt?", context="(state summary)")

    assert isinstance(response, AgentResponse)
    assert response.response_text == "It hurts right here in my chest."
    assert response.revealed_nodes == ["chest_pain"]
    assert response.emotional_state == "anxious"


async def test_repairs_invalid_reply_then_succeeds() -> None:
    # First reply is missing the required emotional_state; second is valid.
    llm = _FakeLLM(
        [
            '{"response_text": "It hurts.", "revealed_nodes": ["chest_pain"]}',
            '{"response_text": "It hurts.", "revealed_nodes": ["chest_pain"], '
            '"emotional_state": "anxious"}',
        ]
    )
    agent = _StubAgent(complete_fn=llm)

    response = await agent.respond("Where does it hurt?", context="(state summary)")

    assert response.emotional_state == "anxious"
    assert len(llm.calls) == 2  # it had to ask again
    # The repair prompt should tell the model why its last reply was rejected.
    assert "emotional_state" in llm.calls[1][1]


async def test_gives_up_after_max_repairs() -> None:
    # Always invalid (never any emotional_state); max_repairs=1 -> 2 attempts.
    llm = _FakeLLM(['{"response_text": "x", "revealed_nodes": []}'] * 5)
    agent = _StubAgent(complete_fn=llm, max_repairs=1)

    with pytest.raises(AgentResponseError):
        await agent.respond("Where does it hurt?", context="(state summary)")

    assert len(llm.calls) == 2  # initial + 1 repair, then give up


async def test_prompt_carries_persona_context_and_message() -> None:
    llm = _FakeLLM(['{"response_text": "ok", "revealed_nodes": [], "emotional_state": "calm"}'])
    agent = _StubAgent(complete_fn=llm)

    await agent.respond("Does it radiate?", context="REVEALED: chest_pain")

    sent_agent_name, sent_prompt = llm.calls[0]
    assert sent_agent_name == "patient"  # routes under the agent's config key
    assert "You are a patient being interviewed." in sent_prompt  # persona
    assert "REVEALED: chest_pain" in sent_prompt  # injected context
    assert "Does it radiate?" in sent_prompt  # the student's message


def test_agent_response_defaults_rapport_delta_to_zero() -> None:
    resp = AgentResponse(response_text="hi", emotional_state="calm")
    assert resp.rapport_delta == 0


def test_agent_response_accepts_rapport_delta() -> None:
    resp = AgentResponse(response_text="hi", emotional_state="calm", rapport_delta=-1)
    assert resp.rapport_delta == -1


def test_base_json_fields_excludes_rapport_delta() -> None:
    # The shared default stays the original 3-field shape so nurse/family/router
    # prompts are unchanged; only the patient overrides this (Task 5).
    agent = _StubAgent(complete_fn=_FakeLLM([]))
    fields = agent._json_fields()
    assert "response_text" in fields
    assert "rapport_delta" not in fields
