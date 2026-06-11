"""Shared pytest fixtures.

The db fixtures build a real-but-disposable SQLite database in memory, so db
tests exercise actual SQL (not mocks) while needing no files and no cleanup.
StaticPool keeps a single underlying connection alive for the fixture's
lifetime — without it, an in-memory SQLite database would vanish between
connections and the schema we create would be gone by the next query.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.db.models import Base


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def db_sessionmaker(db_engine):
    # expire_on_commit=False: keep ORM objects usable after commit instead of
    # triggering a lazy reload — important under async, where lazy loads error.
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(db_sessionmaker):
    async with db_sessionmaker() as session:
        yield session
