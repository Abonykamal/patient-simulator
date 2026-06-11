"""Tests for src.db.session — the get_db request-scoped dependency.

These exercise the transaction boundary: get_db must commit when a request
finishes cleanly and roll back when it raises. We drive the async generator
by hand the way FastAPI does — advance to the yield, use the session, then
either advance again (clean finish -> commit) or throw in (error -> rollback).
"""

import pytest

from src.db import crud
from src.db import session as session_mod


async def test_get_db_commits_on_clean_finish(db_sessionmaker, monkeypatch):
    monkeypatch.setattr(session_mod, "get_sessionmaker", lambda: db_sessionmaker)

    gen = session_mod.get_db()
    db = await gen.__anext__()  # FastAPI: enter the dependency
    sim = await crud.create_session(db, "chest_pain", "Chest Pain")
    session_id = sim.id
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()  # FastAPI: request done -> runs the commit

    # A brand-new session sees the row only if it was actually committed.
    async with db_sessionmaker() as verify:
        assert await crud.get_session(verify, session_id) is not None


async def test_get_db_rolls_back_on_error(db_sessionmaker, monkeypatch):
    monkeypatch.setattr(session_mod, "get_sessionmaker", lambda: db_sessionmaker)

    gen = session_mod.get_db()
    db = await gen.__anext__()
    sim = await crud.create_session(db, "chest_pain", "Chest Pain")
    session_id = sim.id
    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("request blew up"))  # error -> rollback

    async with db_sessionmaker() as verify:
        assert await crud.get_session(verify, session_id) is None
