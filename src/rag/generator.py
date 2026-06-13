"""Scenario generation: retrieved cases → a fresh, schema-valid patient (ADR-022).

This is the top of the RAG layer and the one piece that calls an LLM. The flow
(decisions D2, E, F2):

1. **Retrieve** the top-k cases for the requested specialty (the metadata filter
   pins the category; semantic rank orders within it).
2. **Prompt** the model to *synthesize a new patient* inspired by those cases —
   not copy one — and to emit JSON matching ``scenarios.schema``.
3. **Validate and repair.** Parse the JSON and validate it against the schema. If
   it fails, feed the exact error back and ask the model to fix it, up to
   ``max_repairs`` times. The schema we built in Phase 2 is therefore not just a
   gate but the *self-correction signal* — its error messages name the offending
   field/id, which is precisely the repair instruction.

The LLM call is injected (``complete_fn``) so tests can drive the whole loop with
canned responses and never touch a real provider.
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable

from pydantic import BaseModel, ValidationError

from scenarios.schema import Scenario
from src.core.logging import get_logger
from src.rag.retriever import RetrievedCase, Retriever

log = get_logger("rag.generator")

# Signature of llm.client.complete — injected so tests don't hit a provider.
CompleteFn = Callable[[str, str], Awaitable[str]]

_AGENT_NAME = "scenario_generator"


class ScenarioRequest(BaseModel):
    """What the caller asks for. ``category`` must match a corpus specialty
    (e.g. "chest_pain") since it drives the retrieval metadata filter; ``notes``
    is optional free text to steer the generation (decision E3)."""

    category: str
    notes: str | None = None


class ScenarioGenerationError(RuntimeError):
    """Raised when the model cannot produce a schema-valid scenario within the
    allowed number of repair attempts. Carries the last failure for debugging."""


class ScenarioGenerator:
    """Generates validated patient scenarios from retrieved clinical cases."""

    def __init__(
        self,
        retriever: Retriever,
        complete_fn: CompleteFn | None = None,
        *,
        k: int = 3,
        max_repairs: int = 2,
    ) -> None:
        """Params:
        ``retriever`` — provides the grounding cases.
        ``complete_fn`` — async ``(agent_name, prompt) -> str``; defaults to the
            real LLM client. Injected in tests.
        ``k`` — how many cases to retrieve for grounding.
        ``max_repairs`` — how many times to re-prompt on a validation failure
            before giving up.
        """
        self._retriever = retriever
        self._k = k
        self._max_repairs = max_repairs
        if complete_fn is None:
            # Imported lazily so importing this module never pulls in a provider.
            from src.llm.client import complete as _complete

            complete_fn = _complete
        self._complete = complete_fn

    async def generate(self, request: ScenarioRequest) -> Scenario:
        """Generate one schema-valid :class:`Scenario` for ``request``.

        Retrieves grounding cases, prompts the model, and validates the result,
        repairing up to ``max_repairs`` times on failure.

        Raises:
            ScenarioGenerationError: if no valid scenario is produced in time.
        """
        cases = self._retriever.query(
            _render_query(request), category=request.category, k=self._k
        )
        prompt = _build_prompt(request, cases)

        last_error: Exception | None = None
        for attempt in range(self._max_repairs + 1):
            raw = await self._complete(_AGENT_NAME, prompt)
            try:
                scenario = _parse_scenario(raw)
                log.info("scenario_generated", category=request.category, attempt=attempt)
                return scenario
            except (ValueError, ValidationError) as exc:
                # ValueError covers JSON parse failures; ValidationError covers
                # schema violations. Either way, fold the error into a repair
                # prompt and try again.
                last_error = exc
                log.warning(
                    "scenario_invalid",
                    category=request.category,
                    attempt=attempt,
                    error=str(exc),
                )
                prompt = _build_repair_prompt(request, cases, raw, exc)

        raise ScenarioGenerationError(
            f"no valid scenario after {self._max_repairs + 1} attempts; "
            f"last error: {last_error}"
        )


# --- prompt construction -------------------------------------------------------


def _render_query(request: ScenarioRequest) -> str:
    """Turn a structured request into the text the retriever embeds."""
    text = f"{request.category.replace('_', ' ')} presentation"
    if request.notes:
        text = f"{text}; {request.notes}"
    return text


def _format_cases(cases: list[RetrievedCase]) -> str:
    return "\n\n".join(f"--- Case {i + 1} ---\n{c.text}" for i, c in enumerate(cases))


# Describes the output contract in prose. The hard contract is scenarios.schema;
# this just steers the model toward it so the first attempt usually validates.
_SCHEMA_BRIEF = """\
Return ONLY a JSON object (no prose, no markdown) with these fields:
- scenario_id: short snake_case string
- scenario_name: short human title
- patient_name: a plausible full name
- scenario_intro: one or two sentences a student sees before the interview
- nodes: a list of clinical facts. Each node has:
    - id: snake_case unique string
    - label: short speakable text (e.g. "crushing chest pain")
    - category: one of "symptom", "history", "hidden", "emotional", "social",
      "medication", "family_history"
    - importance (optional): "critical" | "relevant" | "minor"
    - detail (optional): a longer sentence the patient can give if pressed
    - disclosure_difficulty (optional): "volunteered" | "if_asked" |
      "only_if_asked_directly" | "only_if_trust_built"
    - metadata (optional): an object for extras (e.g. {"systolic": 162})
- edges: a list of associations between nodes. Each edge has source, target
  (both must be node ids that exist in nodes), and an optional relation label.

Include 8-16 nodes spanning several categories, with at least one "hidden" node
the student must work to uncover. Every edge endpoint MUST be an existing node id.
"""


def _build_prompt(request: ScenarioRequest, cases: list[RetrievedCase]) -> str:
    notes = f"\nAdditional guidance: {request.notes}\n" if request.notes else ""
    return f"""\
You are generating a simulated patient for medical students to interview.

Use the real clinical cases below as INSPIRATION. Do not copy any single case —
synthesise a new, plausible patient that blends and varies their details
(demographics, severity, emotional context). The presentation type is:
{request.category}.
{notes}
{_format_cases(cases)}

{_SCHEMA_BRIEF}"""


def _build_repair_prompt(
    request: ScenarioRequest,
    cases: list[RetrievedCase],
    bad_output: str,
    error: Exception,
) -> str:
    """Re-ask the model, showing it exactly why its last output was rejected."""
    return f"""\
{_build_prompt(request, cases)}

Your previous response was REJECTED because it did not satisfy the schema.

Validation error:
{error}

Your previous response was:
{bad_output}

Return a corrected JSON object that fixes the error above. Output ONLY the JSON."""


# --- parsing -------------------------------------------------------------------


def _extract_json(raw: str) -> dict:
    """Pull the JSON object out of a model response, tolerating prose/fences.

    Models often wrap JSON in ```json ... ``` or add a sentence before it. We
    take the substring from the first ``{`` to the last ``}`` and parse that.
    """
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return json.loads(raw[start : end + 1])  # JSONDecodeError is a ValueError


def _parse_scenario(raw: str) -> Scenario:
    """Extract JSON from a raw model response and validate it into a Scenario.

    Raises ``ValueError`` on unparseable JSON or ``ValidationError`` on a schema
    violation — both caught by the repair loop.
    """
    return Scenario.model_validate(_extract_json(raw))
