"""Shared pytest fixtures.

The Postgres `testcontainers` fixture is session scoped per spec 0001; it is
added in Feature 3 when the first ORM models land. For the scaffold smoke test
we only need the HTTP app and a stubbed DB session that answers readiness.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.database import get_session
from app.main import create_app


class _StubSession:
    """Minimal async-session stand-in for the scaffold tests.

    Feature 3 replaces this with a real session bound to the testcontainers
    Postgres instance.
    """

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


@pytest.fixture
async def client(test_settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(test_settings)
    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
