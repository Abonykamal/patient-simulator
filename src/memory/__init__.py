"""Memory & context layer — assembles each agent's per-turn context (Phase 5).

Pure and I/O-free: these modules receive typed objects and return strings; they
never open a DB session or call an LLM. The Phase 6 orchestrator owns those
boundaries and wires the layer to crud, the router, and the agents.

- ``context_builder`` — renders one agent's context string (slice policy + layout)
- ``manager`` — filters to the agent's thread, windows it, hosts the trust clamp
- ``summarizer`` — deferred stub (design D5)
"""
