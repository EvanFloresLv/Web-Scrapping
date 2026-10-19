"""Shared pytest fixtures.

Two layers:

- `client` + stub session: the scaffold smoke tests that only need the HTTP app
  and never touch Postgres (health, startup).
- `pg_engine` + `db_session` + `api_client`: a session scoped Postgres
  (testcontainers) with real tables, used by the websites domain tests. Each
  test runs against a clean table set (`TRUNCATE … RESTART IDENTITY CASCADE`
  before every test), per spec 0001.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

# Importing the domain's models registers them on `Base.metadata` so
# `create_all` builds every table/index this suite exercises. Add new domains
# here as they land.
import app.domains.executions.models
import app.domains.websites.models
import app.domains.workflows.models  # noqa: F401
from app.core.config import Settings
from app.core.database import Base, get_session
from app.main import create_app


class _StubSession:
    """Minimal async-session stand-in for the scaffold tests."""

    async def execute(self, _stmt):  # type: ignore[no-untyped-def]
        class _Result:
            def scalar_one(self) -> int:
                return 1

        return _Result()


async def _override_get_session() -> AsyncIterator[_StubSession]:
    yield _StubSession()


@pytest.fixture
def test_settings() -> Settings:
    return Settings(environment="test", log_json=False)


@pytest_asyncio.fixture
async def client(test_settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(test_settings)
    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Postgres-backed fixtures for the websites domain tests (spec 0002).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _pg_container() -> AsyncIterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        yield pg


@pytest_asyncio.fixture(scope="session")
async def pg_engine(_pg_container: PostgresContainer) -> AsyncIterator[AsyncEngine]:
    """Session scoped async engine with every ORM table created."""
    url = _pg_container.get_connection_url()
    # NullPool: pytest-asyncio runs each test in its own event loop, so a
    # connection pulled from a shared pool would land on the wrong loop and
    # raise "another operation is in progress". A fresh connection per use
    # keeps the engine session-scoped but loop safe.
    engine = create_async_engine(url, future=True, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def _truncate_all(pg_engine: AsyncEngine) -> AsyncIterator[None]:
    """Reset every table before each test to keep tests independent."""
    from sqlalchemy import text

    table_names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    async with pg_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
    yield


@pytest_asyncio.fixture
async def db_session(
    pg_engine: AsyncEngine,
    _truncate_all: None,
) -> AsyncIterator[AsyncSession]:
    """One `AsyncSession` per test, committed by the handler under test."""
    factory = async_sessionmaker(bind=pg_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def api_client(
    test_settings: Settings,
    pg_engine: AsyncEngine,
    _truncate_all: None,
) -> AsyncIterator[AsyncClient]:
    """`AsyncClient` wired to the FastAPI app, each request on its own session."""
    factory = async_sessionmaker(bind=pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app = create_app(test_settings)
    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
