"""Evaluation layer (Phase 7) — the end-of-session LLM-as-judge.

A stronger model (Groq/Llama-70B, no fallback) reads the transcript and grades the
student against a process-based rubric derived from the scenario's nodes. The judge
classifies each rubric item asked/not-asked; the score and report are computed in
code (reproducible, testable). See docs/specs/2026-06-17-evaluation-design.md.

Modules: rubric (nodes → gradeable items), judge (the LLM-as-judge), report (score +
format), evaluator (the coordinator). Pure except judge, which calls the LLM client.
"""
