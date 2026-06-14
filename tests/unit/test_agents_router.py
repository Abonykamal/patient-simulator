"""Tests for the Router (Phase 4, ADR-009).

The router decides which agent answers. The common paths are free (no LLM):
explicit addressing wins, and an unaddressed message defaults to the patient. The
LLM classifier fires only when the caller explicitly asks for it ("auto"), and
even then routing is parsed defensively so a chatty/unknown reply can't break it.
The LLM is faked — no real call.
"""

from __future__ import annotations

from src.agents.router import AUTO, Router


class _Sentinel:
    """Stand-in for an agent — the router only stores and returns it."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, agent_name: str, prompt: str) -> str:
        self.calls.append((agent_name, prompt))
        return self._responses.pop(0)


def _make_router(llm: _FakeLLM | None = None) -> tuple[Router, dict[str, _Sentinel]]:
    agents = {n: _Sentinel(n) for n in ("patient", "nurse", "family")}
    router = Router(
        patient=agents["patient"],
        nurse=agents["nurse"],
        family=agents["family"],
        complete_fn=llm,
    )
    return router, agents


async def test_explicit_address_wins_without_llm() -> None:
    llm = _FakeLLM([])  # if the classifier is called, .pop(0) would error
    router, agents = _make_router(llm)

    result = await router.resolve("What are his vitals?", addressed_to="nurse")

    assert result is agents["nurse"]
    assert llm.calls == []  # explicit addressing is free


async def test_unaddressed_defaults_to_patient_without_llm() -> None:
    llm = _FakeLLM([])
    router, agents = _make_router(llm)

    result = await router.resolve("Tell me about the pain.", addressed_to=None)

    assert result is agents["patient"]
    assert llm.calls == []  # default-to-patient is free (Decision B)


async def test_auto_invokes_classifier() -> None:
    llm = _FakeLLM(["nurse"])
    router, agents = _make_router(llm)

    result = await router.resolve("Has anyone checked on him?", addressed_to=AUTO)

    assert result is agents["nurse"]
    sent_agent_name, sent_prompt = llm.calls[0]
    assert sent_agent_name == "router"  # routes under AGENT_CONFIG["router"]
    assert "Has anyone checked on him?" in sent_prompt  # message is grounded in
    assert "about" in sent_prompt  # the about-vs-to instruction is present


async def test_classifier_parses_defensively() -> None:
    # A chatty / unrecognised reply must fall back to patient, not crash.
    llm = _FakeLLM(["I think this is for the patient, probably."])
    router, agents = _make_router(llm)
    assert await router.resolve("hmm", addressed_to=AUTO) is agents["patient"]

    # A one-word reply with stray punctuation/case still routes.
    llm2 = _FakeLLM(["Family.\n"])
    router2, agents2 = _make_router(llm2)
    assert await router2.resolve("hmm", addressed_to=AUTO) is agents2["family"]
