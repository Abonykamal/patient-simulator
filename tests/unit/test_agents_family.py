"""Tests for the FamilyAgent persona (Phase 4).

Pipeline behaviour is covered in test_agents_base.py. These tests pin what makes
this agent *the family member*: it routes under the "family" config key and its
prompt encodes the approved guardrails — first person, report observation not
inference, no invented family history, refuse leading-question assumptions, defer
clinical detail to staff, prefer approximate over false precision. LLM is faked.
"""

from __future__ import annotations

from src.agents.family import FamilyAgent


class _FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, agent_name: str, prompt: str) -> str:
        self.calls.append((agent_name, prompt))
        return self._responses.pop(0)


_VALID = (
    '{"response_text": "He has not been himself for a couple of weeks.", '
    '"revealed_nodes": ["work_stress"], "emotional_state": "worried"}'
)


async def test_family_routes_and_responds() -> None:
    llm = _FakeLLM([_VALID])
    agent = FamilyAgent(complete_fn=llm)

    response = await agent.respond("How has he been at home?", context="(what you know)")

    sent_agent_name, sent_prompt = llm.calls[0]
    assert sent_agent_name == "family"  # routes under AGENT_CONFIG["family"]
    assert response.response_text.startswith("He has not been himself")
    assert response.revealed_nodes == ["work_stress"]
    assert response.emotional_state == "worried"


async def test_persona_encodes_the_approved_guardrails() -> None:
    # Characterization test: locks the approved family rules against silent edits.
    llm = _FakeLLM([_VALID])
    agent = FamilyAgent(complete_fn=llm)

    await agent.respond("Has he been coughing blood?", context="(what you know)")
    _, prompt = llm.calls[0]

    assert "first person" in prompt  # #8 perspective
    assert "do not speculate about medical causes" in prompt  # #1 observation not inference
    assert "Do not invent a family history" in prompt  # #3 family-history guard
    assert "Do not accept assumptions built into a question" in prompt  # #7 leading questions
    assert "ask the nurse or doctor" in prompt  # defers clinical to staff
    assert "Prefer approximate answers over false precision" in prompt  # #6 uncertainty
