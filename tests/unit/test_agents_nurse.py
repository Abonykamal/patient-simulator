"""Tests for the NurseAgent persona (Phase 4).

Pipeline behaviour is covered in test_agents_base.py. These tests pin what makes
this agent *the nurse*: it routes under the "nurse" config key and its prompt
encodes the approved guardrails — report only documented facts, no clinical
reasoning, defer diagnosis to the doctor and personal history to the patient,
give exact recorded values, and don't dump the chart. LLM is faked.
"""

from __future__ import annotations

from src.agents.nurse import NurseAgent


class _FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, agent_name: str, prompt: str) -> str:
        self.calls.append((agent_name, prompt))
        return self._responses.pop(0)


_VALID = (
    '{"response_text": "His blood pressure was 158 over 92.", '
    '"revealed_nodes": ["vitals"], "emotional_state": "neutral"}'
)


async def test_nurse_routes_and_responds() -> None:
    llm = _FakeLLM([_VALID])
    agent = NurseAgent(complete_fn=llm)

    response = await agent.respond("What are his vitals?", context="(chart)")

    sent_agent_name, sent_prompt = llm.calls[0]
    assert sent_agent_name == "nurse"  # routes under AGENT_CONFIG["nurse"]
    assert response.response_text.startswith("His blood pressure")
    assert response.revealed_nodes == ["vitals"]
    assert response.emotional_state == "neutral"


async def test_persona_encodes_the_approved_guardrails() -> None:
    # Characterization test: locks the approved nurse rules against silent edits.
    llm = _FakeLLM([_VALID])
    agent = NurseAgent(complete_fn=llm)

    await agent.respond("What's wrong with him?", context="(chart)")
    _, prompt = llm.calls[0]

    assert "explicitly documented" in prompt  # grounding to the chart
    assert "treat it as unknown" in prompt  # softened no-outside-facts (#4)
    assert "speculate about causes" in prompt  # no clinical reasoning (#3)
    assert "You'd need to ask the doctor" in prompt  # no diagnosis
    assert "direct them to ask the patient" in prompt  # defer personal history
    assert "Answer only the question asked" in prompt  # no chart-dumping
    assert "Do not accept assumptions built into a question" in prompt  # leading-question guard
