"""FastAPI layer (Phase 6) — a thin HTTP wrapper over the orchestrator.

Routes unpack the request, call ``src.conversation.orchestrator``, and shape the
response. No business logic lives here (CLAUDE.md). The expensive collaborators
(generator, agents, router) are built once in ``main.py``'s lifespan and handed to
routes via ``deps.py`` so tests can override them with fakes.
"""
