"""Dependency providers for the routes — the one seam tests override.

``get_db`` is re-exported from the db layer so routes and tests reference a single
symbol. ``get_generator`` / ``get_router`` read the singletons that ``main.py``'s
lifespan built once onto ``app.state``; in tests they are swapped for fakes via
``app.dependency_overrides`` so no real generator/agent is ever constructed.
"""

from __future__ import annotations

from fastapi import Request

from src.db.session import get_db  # noqa: F401 — re-exported as the shared db dep

__all__ = ["get_db", "get_generator", "get_router_factory", "get_judge"]


def get_generator(request: Request):
    """The ScenarioGenerator built once in the app lifespan."""
    return request.app.state.generator


def get_judge(request: Request):
    """The LLM-as-judge built once in the app lifespan (Groq, no fallback)."""
    return request.app.state.judge


def get_router_factory(request: Request):
    """The ``(patient_name) -> Router`` factory built in the app lifespan.

    A factory, not a single Router: the patient agent is parameterised by the
    patient's name, so the router is built per session (the stateless nurse/family
    agents are shared inside it)."""
    return request.app.state.router_factory
