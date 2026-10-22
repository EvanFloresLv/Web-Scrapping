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

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

# Set BEFORE any `app.*` import so `Settings()` without an explicit key reads
# a valid value from the environment (spec 0008 requires one at startup).
os.environ.setdefault("ADMIN_API_KEY", "test-admin-api-key-0123456789")

import pytest
import pytest_asyncio
import structlog
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
import app.core.observability.models
import app.domains.executions.models
import app.domains.websites.models
import app.domains.workflows.models  # noqa: F401
from app.core.alembic_head import EXPECTED_HEAD
from app.core.config import Settings
from app.core.database import Base, get_session, get_session_factory
from app.core.startup_state import mark_startup_complete
from app.domains.extraction.dependencies import get_http_client
from app.main import create_app


class _StubSession:
    """Minimal async session stand in for the scaffold tests.

    Supports both the `SELECT 1` liveness probe and the readiness
    `SELECT version_num FROM alembic_version` lookup by sniffing the SQL text.
    """

    async def execute(self, stmt):  # type: ignore[no-untyped-def]
        rendered = str(stmt)

        class _Result:
            def __init__(self, value: int | str | None) -> None:
                self._value = value

            def scalar_one(self):  # type: ignore[no-untyped-def]
                return self._value

            def scalar_one_or_none(self):  # type: ignore[no-untyped-def]
                return self._value

        if "alembic_version" in rendered:
            return _Result(EXPECTED_HEAD)
        return _Result(1)


async def _override_get_session() -> AsyncIterator[_StubSession]:
    yield _StubSession()


class _StubSessionFactory:
    """Context manager that hands out `_StubSession` instances per `__aenter__`.

    Mimics the `async_sessionmaker(...)()` surface the readiness probe uses:
    `async with factory() as session: ...`.
    """

    def __call__(self) -> _StubSessionFactory:
        return self

    async def __aenter__(self) -> _StubSession:
        return _StubSession()

    async def __aexit__(self, *_: object) -> None:
        return None


def _override_get_session_factory() -> _StubSessionFactory:
    return _StubSessionFactory()


TEST_ADMIN_API_KEY = "test-admin-api-key-0123456789"


@pytest.fixture
def caplog_structlog() -> Iterator[list[dict[str, Any]]]:
    """Spec 0011 AC-11: capture emitted structlog events as plain dicts.

    Keeps `merge_contextvars` in front of the capture sink so contextvar
    bound fields (`correlation_id`, `execution_id`, ...) land on captured
    events too, which the stock `structlog.testing.capture_logs()` drops.
    Redaction assertions still need a dedicated rendered sink (see
    `tests/test_logging_contract.py`), because the processor chain after
    the capture point is bypassed by design.
    """
    entries: list[dict[str, Any]] = []

    def _capture(_logger: Any, name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        # Mirror structlog's own `capture_logs` convention: expose the
        # call method (`info`, `debug`, ...) as `log_level` so tests can
        # filter by severity even though the usual `add_log_level`
        # processor is bypassed by this fixture.
        event_dict.setdefault("log_level", name)
        entries.append(dict(event_dict))
        raise structlog.DropEvent

    old_config = structlog.get_config()
    structlog.configure(
        processors=[structlog.contextvars.merge_contextvars, _capture],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    try:
        yield entries
    finally:
        structlog.configure(**old_config)


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        environment="test",
        log_json=False,
        admin_api_key=TEST_ADMIN_API_KEY,
    )


@pytest_asyncio.fixture
async def client(test_settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(test_settings)
    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_session_factory] = _override_get_session_factory
    # ASGITransport skips the FastAPI lifespan, so the readiness `startup`
    # gate stays `False` under test unless we flip it here (per spec 0007 AC-12
    # the flag is per worker and is set at the end of `_lifespan`).
    mark_startup_complete()
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
    """`AsyncClient` wired to the FastAPI app, each request on its own session.

    Also installs a real `httpx.AsyncClient` as the extraction `get_http_client`
    override. `respx` can mock routes against this client (ASGI test runs skip
    the app lifespan, so `app.state.http_client` is never populated by that path).
    """
    import httpx

    factory = async_sessionmaker(bind=pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    outbound = httpx.AsyncClient()

    def _override_http_client() -> httpx.AsyncClient:
        return outbound

    app = create_app(test_settings)
    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[get_session_factory] = _override_get_session_factory
    app.dependency_overrides[get_http_client] = _override_http_client
    mark_startup_complete()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": TEST_ADMIN_API_KEY},
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
    await outbound.aclose()
