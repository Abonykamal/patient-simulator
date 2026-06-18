# Phase 7 — Evaluation (Design)

**Date:** 2026-06-17
**Status:** Approved — ready to build (TDD)
**Scope:** The end-of-session LLM-as-judge. After the interview, a stronger model
(Groq/Llama-70B, no fallback) reads the transcript and grades the student against a
process-based rubric; we compute a score, format a report, end the session, and
persist the evaluation. Exposed via `POST /sessions/{id}/evaluate` + `GET
/sessions/{id}/report`, with an "End interview & get feedback" button in the UI.

Additive: new `src/evaluation/`, one new route, small additions to `schemas`,
`deps`, `main`, and `frontend`. No reviewed module's behaviour changes.

---

## Decisions (drawn out in design dialogue)

| # | Decision | Rationale | ADR |
|---|----------|-----------|-----|
| D1 | The rubric is **derived from the scenario's nodes** (each node = a topic; `importance` = its weight). No new schema field. *Refined:* only `critical`/`relevant` nodes are graded — `minor` incidental colour is excluded. | ADR-017 carried `importance` for exactly this; every generated patient gets a rubric for free; `minor` trivia ("hairdresser") shouldn't be graded. | ADR-032 |
| D2 | **Judge classifies, code scores.** The judge marks each rubric item `asked`/`not_asked`/`not_applicable` + a reasoning narrative; code computes `overall_score` = weighted coverage, **dropping `not_applicable`** from the denominator. | LLMs are good at "did they ask X?" and at spotting non-questions (findings/observations); a code score is reproducible and testable. `not_applicable` keeps askability off the generator. | ADR-032 |
| D3 | A dedicated **`src/evaluation/evaluator.py`** coordinator (`evaluate_session`, judge injected), keeping the conversation orchestrator focused on the live loop. | Cohesion: rubric/judge/report concerns stay in `src/evaluation/`; conversation doesn't grow an evaluation dependency. | ADR-032 |
| D4 | **`report.py` formats `full_report_text` in code** around the judge's narrative (score + covered/missed lists + notes). | Reproducible, testable, no extra LLM call; the model only writes the part that needs a model. | ADR-032 |
| D5 | `POST /evaluate` is **idempotent** (returns the existing evaluation if present), **ends + judges + saves in one action**, and **fails loud** on judge error (`503`, no fallback). | Saves judge quota, retry-safe, can't overwrite a result; a degraded judge silently misleads, so unlike a turn it must fail loudly (AGENT_CONFIG). | ADR-032 |
| D6 | **No end-of-session graph snapshot** — `evaluate_session` marks the session `completed` only. | Rebuild-from-turns (ADR-030) makes the snapshot redundant; storing it would be a second copy of the truth. Supersedes the Phase-6 doc note. | ADR-030 |

**Judge prompt:** approved (process-based; "asked" = a student utterance explicitly
seeking the info, incl. clinical paraphrase; evidence must be in a student line,
never inferred from the patient's reply; feedback names strongest coverage +
highest-priority/critical gaps; valid-JSON-only). Full text in `judge.py`.

---

## Components

| Module | Responsibility |
|--------|----------------|
| `src/evaluation/rubric.py` | `build_rubric(scenario) -> list[RubricItem]`; `RubricItem(id, topic, importance)` from nodes. |
| `src/evaluation/judge.py` | The LLM-as-judge (LLM injected, `agent_name="judge"` → Groq, no fallback). `judge(rubric_items, transcript) -> JudgeVerdict`; validate-and-repair. |
| `src/evaluation/report.py` | Pure: `score(verdict, rubric_items) -> ScoredResult` (weighted coverage, covered/missed topic lists) + `format_report(...) -> str`. |
| `src/evaluation/evaluator.py` | `evaluate_session(db, judge, session_id)`: idempotency check → load turns → build rubric from stored scenario → render transcript → judge → score+format → `end_session` (completed) → `save_evaluation`. |
| `src/api/routes/evaluation.py` | `POST /sessions/{id}/evaluate`, `GET /sessions/{id}/report` (thin; 404/503). |
| `src/api/schemas.py` | `EvaluationResponse(covered, missed, score, clinical_reasoning_notes, full_report)`. |
| `src/api/deps.py` | `get_judge` (singleton from lifespan). |
| `src/api/main.py` | Build `Judge()` onto `app.state.judge`. |
| `frontend/app.py` | "End interview & get feedback" button → `POST /evaluate` → render report. |
| `scripts/smoke_evaluation.py` | Hand-run live judge over a real (or seeded) transcript. |

## Types & signatures

```python
class RubricItem(BaseModel):       # rubric.py — built only from critical/relevant nodes
    id: str           # node id
    topic: str        # node label — the thing to have asked about
    importance: str   # critical | relevant  (minor nodes are not graded)

class ItemVerdict(BaseModel):      # judge.py
    id: str
    verdict: Literal["asked", "not_asked", "not_applicable"]  # not_applicable = a finding, excluded

class JudgeVerdict(BaseModel):     # judge.py — the judge's structured output
    items: list[ItemVerdict]
    clinical_reasoning_notes: str

class ScoredResult(BaseModel):     # report.py
    overall_score: float           # Σ(weight asked) / Σ(weight all); 0.0 if no items
    covered: list[str]             # topic labels asked
    missed: list[str]              # topic labels not asked

_WEIGHTS = {"critical": 3, "relevant": 2, "minor": 1}

async def evaluate_session(db, judge, session_id) -> Evaluation:
    # if crud.get_evaluation(db, id): return it            (D5 idempotent)
    # session = get_session; LookupError if None
    # scenario = Scenario.model_validate(patient_profile_json); rubric = build_rubric(scenario)
    # transcript = render(crud.get_turns(db, id))
    # verdict = await judge.judge(rubric, transcript)       (risky LLM call; no fallback)
    # scored = report.score(verdict, rubric)
    # text = report.format_report(scored, verdict.clinical_reasoning_notes)
    # crud.end_session(db, id)                              (completed; no snapshot, D6)
    # return crud.save_evaluation(db, id, rubric_items=[...], covered, missed,
    #          overall_score=scored.overall_score, clinical_reasoning_notes=..., full_report_text=text)
```

## API contract

```
POST /sessions/{id}/evaluate   → EvaluationResponse   (ends + judges + saves; 404 unknown; 503 judge fail)
GET  /sessions/{id}/report     → EvaluationResponse   (404 if not yet evaluated)

EvaluationResponse = {covered: [...], missed: [...], score: 0.72,
                      clinical_reasoning_notes: "...", full_report: "..."}
```

## Error handling

The judge call (in `evaluate_session`) runs before the `end_session`/`save` writes;
on failure the route returns **503** and nothing is persisted — but unlike a turn,
the intent is *fail loud* (a missing/degraded evaluation must not look like a pass).
Unknown session → 404.

## Testing

- **rubric.py / report.py** — pure: direct unit tests (nodes → items; covered/missed
  → exact weighted score incl. empty/all/critical-only edges; report text contains
  score + lists + notes).
- **judge.py** — injected fake `complete_fn` with canned JSON; asserts parse + the
  repair loop; one malformed-then-fixed case. No real call.
- **evaluator.py** — in-memory SQLite + fake judge: builds rubric from stored
  scenario, persists evaluation, marks session completed, **idempotent re-run** returns
  the same row without re-judging, unknown session raises.
- **routes** — thin `TestClient` + `dependency_overrides`: evaluate happy path,
  report happy path, report-before-evaluate 404, judge-failure 503.
- **Zero real LLM calls.** Live judge proven only by `scripts/smoke_evaluation.py`.

## Cross-layer touchpoints (consumed, not edited)

`Scenario` + node `importance` (ADR-017) · `crud.get_session/get_turns/end_session/
save_evaluation/get_evaluation` · the LLM client via `agent_name="judge"` (Groq, no
fallback). The `serializer` stays unused (D6).
