"""Database engine, session factory, and the request-scoped ``get_db`` dependency.

This is the only module that creates the async engine. The engine and session
factory are lazy module-level singletons so configuration (the database URL
from Settings) is read once, on first use. ``get_db`` implements the
unit-of-work boundary from ADR-014: one session per request, committed on a
clean finish and rolled back on error.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import get_settings
from src.db.models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the lazily-created async engine (one per process)."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the lazily-created session factory bound to the engine."""
    global _sessionmaker
    if _sessionmaker is None:
        # expire_on_commit=False keeps objects usable after commit, avoiding
        # async-illegal lazy reloads when a route returns ORM data post-commit.
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def init_db() -> None:
    """Create any missing tables from the models (ADR-016: create_all, not Alembic)."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped session; commit on success, roll back on error.

    Use as a FastAPI dependency: ``db: AsyncSession = Depends(get_db)``.
    The whole request is one transaction, so multi-step CRUD operations
    succeed or fail together.

    Yields:
        An ``AsyncSession`` for the duration of one request.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
