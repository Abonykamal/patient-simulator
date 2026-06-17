"""Conversation orchestration (Phase 6).

The thin glue that runs one turn end-to-end: resolve the agent (router), build its
context (memory), call it (agent → LLM), apply the results to the rebuilt state
graph, and persist the exchange. It owns no domain rules of its own — only the
*order* of operations — and takes every collaborator injected, so the whole loop
unit-tests with fakes and no network. See
docs/specs/2026-06-17-conversation-loop-design.md.
"""
