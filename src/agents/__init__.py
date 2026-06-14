"""Agents layer — patient, nurse, and family personas plus the router.

Each agent turns the patient's state (data) into a character that talks. All
agents go through ``src.llm.client.complete`` (never a raw provider SDK) and
return a structured :class:`~src.agents.base.AgentResponse` (ADR-010).
"""
