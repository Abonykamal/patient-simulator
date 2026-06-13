"""Tests for src.rag.generator — retrieve → prompt → LLM → validate-repair (ADR-022).

The generator is the only Phase 3 piece that talks to an LLM, so the LLM is
*injected*: every test passes a fake ``complete_fn`` that returns canned text.
No real provider call is ever made (that would burn free-tier quota and need
network) — exactly the rule the rest of the suite follows. The retriever is
stubbed too, so these tests isolate the generate logic: prompt grounding, JSON
parsing, and the validate-and-repair loop (decision F2).
"""

import json

import pytest

from scenarios.schema import Scenario
from src.rag.generator import ScenarioGenerationError, ScenarioGenerator, ScenarioRequest
from src.rag.retriever import RetrievedCase
from src.state.builder import build_graph

# A syntactically valid, schema-valid scenario the fake LLM can "return".
_VALID = {
    "scenario_id": "gen_chest_pain",
    "scenario_name": "Generated Chest Pain",
    "patient_name": "Maria Lopez",
    "scenario_intro": "A 61-year-old woman with sudden chest pain.",
    "nodes": [
        {"id": "chest_pain", "label": "crushing chest pain", "category": "symptom"},
        {"id": "smoking", "label": "smokes a pack a day", "category": "social"},
        {"id": "mi", "label": "myocardial infarction", "category": "hidden",
         "importance": "critical"},
    ],
    "edges": [{"source": "smoking", "target": "chest_pain", "relation": "risk_factor"}],
}
VALID_JSON = json.dumps(_VALID)

# Same shape but an illegal category — trips the schema's Literal validation.
_INVALID = json.loads(VALID_JSON)
_INVALID["nodes"][0]["category"] = "cardiac"
INVALID_JSON = json.dumps(_INVALID)


class _StubRetriever:
    """Stand-in for the real Retriever: returns fixed cases, records the query."""

    def __init__(self, cases: list[RetrievedCase]) -> None:
        self._cases = cases
        self.last_call: tuple | None = None

    def query(self, text: str, category: str | None = None, k: int = 3):
        self.last_call = (text, category, k)
        return self._cases


class _FakeLLM:
    """Async stand-in for llm.client.complete: replays canned responses in order."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, agent_name: str, prompt: str) -> str:
        self.calls.append((agent_name, prompt))
        # Past the end, keep returning the last response (for the "always bad" case).
        return self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]


def _case() -> RetrievedCase:
    return RetrievedCase(
        case_id="chest_pain_01",
        specialty="chest_pain",
        text="UNIQUE_CASE_MARKER 63-year-old woman, crushing chest pain, smoker.",
        distance=0.1,
    )


async def test_generate_returns_validated_scenario():
    gen = ScenarioGenerator(_StubRetriever([_case()]), complete_fn=_FakeLLM([VALID_JSON]))
    scenario = await gen.generate(ScenarioRequest(category="chest_pain"))
    assert isinstance(scenario, Scenario)
    assert scenario.patient_name == "Maria Lopez"


async def test_prompt_is_grounded_in_retrieved_cases():
    fake = _FakeLLM([VALID_JSON])
    gen = ScenarioGenerator(_StubRetriever([_case()]), complete_fn=fake)
    await gen.generate(ScenarioRequest(category="chest_pain"))

    agent_name, prompt = fake.calls[0]
    assert agent_name == "scenario_generator"  # routes to the right AGENT_CONFIG entry
    assert "UNIQUE_CASE_MARKER" in prompt  # the retrieved case is in the prompt


async def test_request_category_drives_retrieval_filter():
    stub = _StubRetriever([_case()])
    gen = ScenarioGenerator(stub, complete_fn=_FakeLLM([VALID_JSON]))
    await gen.generate(ScenarioRequest(category="chest_pain"))
    # The retriever was filtered by the requested specialty.
    assert stub.last_call[1] == "chest_pain"


async def test_parses_json_wrapped_in_markdown_fences():
    fenced = f"Here is your scenario:\n```json\n{VALID_JSON}\n```\n"
    gen = ScenarioGenerator(_StubRetriever([_case()]), complete_fn=_FakeLLM([fenced]))
    scenario = await gen.generate(ScenarioRequest(category="chest_pain"))
    assert scenario.scenario_id == "gen_chest_pain"


async def test_repairs_invalid_output_then_succeeds():
    fake = _FakeLLM([INVALID_JSON, VALID_JSON])
    gen = ScenarioGenerator(_StubRetriever([_case()]), complete_fn=fake, max_repairs=2)
    scenario = await gen.generate(ScenarioRequest(category="chest_pain"))

    assert isinstance(scenario, Scenario)
    assert len(fake.calls) == 2  # one failed, one repair
    # The repair prompt fed the validation error back to the model.
    assert "category" in fake.calls[1][1].lower()


async def test_gives_up_after_max_repairs():
    fake = _FakeLLM([INVALID_JSON])  # always invalid
    gen = ScenarioGenerator(_StubRetriever([_case()]), complete_fn=fake, max_repairs=2)
    with pytest.raises(ScenarioGenerationError):
        await gen.generate(ScenarioRequest(category="chest_pain"))
    assert len(fake.calls) == 3  # initial attempt + 2 repairs


async def test_generated_scenario_builds_into_graph():
    # Closes the loop the whole phase exists for: generated → validated → graph.
    gen = ScenarioGenerator(_StubRetriever([_case()]), complete_fn=_FakeLLM([VALID_JSON]))
    scenario = await gen.generate(ScenarioRequest(category="chest_pain"))
    graph = build_graph(scenario)
    assert len(graph) == 3
