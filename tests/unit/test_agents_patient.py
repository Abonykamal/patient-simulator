"""Tests for the PatientAgent persona (Phase 4).

The pipeline itself is covered in test_agents_base.py; these tests pin the things
that make this agent *the patient*: it routes under the "patient" config key, it
carries its session identity, and its prompt encodes the approved persona
guardrails (plain language, the disclosure hierarchy, deferring vitals to staff,
no diagnosis leakage, conversational pacing). The LLM is faked — no real call.
"""

from __future__ import annotations

from src.agents.patient import PatientAgent


class _FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, agent_name: str, prompt: str) -> str:
        self.calls.append((agent_name, prompt))
        return self._responses.pop(0)


_VALID = (
    '{"response_text": "It is mostly here in the middle of my chest.", '
    '"revealed_nodes": ["chest_pain"], "emotional_state": "worried"}'
)


async def test_patient_routes_and_responds() -> None:
    llm = _FakeLLM([_VALID])
    agent = PatientAgent(patient_name="Arthur Penhaligon", complete_fn=llm)

    response = await agent.respond("Tell me about the pain.", context="(truth)")

    sent_agent_name, sent_prompt = llm.calls[0]
    assert sent_agent_name == "patient"  # routes under AGENT_CONFIG["patient"]
    assert "Arthur Penhaligon" in sent_prompt  # plays this specific person
    assert response.response_text.startswith("It is mostly here")
    assert response.revealed_nodes == ["chest_pain"]
    assert response.emotional_state == "worried"


async def test_persona_encodes_the_approved_guardrails() -> None:
    # Characterization test: locks the approved persona rules so a future edit
    # can't silently drop one. Each substring maps to a concern we agreed on.
    llm = _FakeLLM([_VALID])
    agent = PatientAgent(patient_name="Arthur Penhaligon", complete_fn=llm)

    await agent.respond("How are you?", context="(truth)")
    _, prompt = llm.calls[0]

    assert "plain, everyday language" in prompt  # no jargon
    assert "1-3 sentences" in prompt  # pacing (#8)
    assert "earn information through follow-up questions" in prompt  # not over-eager (#1)
    assert "realistic vagueness" in prompt  # memory uncertainty (#3)
    assert "NOT know your diagnosis" in prompt  # no diagnosis leakage (#6)
    assert "nurse or doctor would need to check" in prompt  # defer vitals (#7)
    assert "only_if_trust_built" in prompt  # disclosure hierarchy + trust rubric
    assert "Do not accept assumptions built into a question" in prompt  # leading-question guard


def test_persona_encodes_the_rapport_mechanism() -> None:
    # The two Phase-5 additions: honour the injected rapport level, emit a delta.
    agent = PatientAgent("Jane", complete_fn=_FakeLLM([]))
    persona = agent._persona()
    assert "CURRENT RAPPORT" in persona
    assert "only_if_trust_built facts as locked" in persona
    assert "rapport_delta" in persona


def test_patient_json_fields_requests_rapport_delta() -> None:
    agent = PatientAgent("Jane", complete_fn=_FakeLLM([]))
    assert "rapport_delta" in agent._json_fields()
