"""Smoke tests for the scaffold.

Verifies the FastAPI app boots, the v1 prefix is wired, correlation IDs come back,
Problem Details handles unknown routes, and the request-size cap rejects oversize bodies.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.database import get_session
from app.main import create_app


@pytest.mark.asyncio
async def test_live_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_live_echoes_correlation_id(client: AsyncClient) -> None:
    request_id = "test-correlation-id-abc123"
    response = await client.get("/api/v1/health/live", headers={"X-Request-ID": request_id})
    assert response.status_code == 200
    assert response.headers.get("x-request-id") == request_id


@pytest.mark.asyncio
async def test_ready_reports_database_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["database"] is True
    assert payload["status"] == "ok"


@pytest.mark.asyncio
async def test_unknown_route_returns_problem_details(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    payload = response.json()
    assert payload["status"] == 404
    assert payload["code"] == "http.404"
    assert "correlation_id" in payload


@pytest.mark.asyncio
async def test_oversize_body_is_rejected(client: AsyncClient) -> None:
    big = {"blob": "x" * (2 * 1024 * 1024)}  # 2 MB
    response = await client.post("/api/v1/health/live", json=big)
    # Health route rejects POST with 405, but the size middleware runs first
    # and should answer 413 for oversize bodies regardless of the route.
    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "http.413"


@pytest.mark.asyncio
async def test_live_generates_correlation_id_when_absent(client: AsyncClient) -> None:
    """If the caller does not send X-Request-ID, the middleware generates one."""
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    generated = response.headers.get("x-request-id")
    assert generated, "x-request-id header missing from response"
    assert len(generated) >= 8


class _ExplodingSession:
    """Session stand-in that raises on execute, to drive the degraded ready path."""

    async def execute(self, _stmt):  # type: ignore[no-untyped-def]
        raise RuntimeError("database unreachable")


async def _override_exploding_session() -> AsyncIterator[_ExplodingSession]:
    yield _ExplodingSession()


@pytest.mark.asyncio
async def test_ready_reports_degraded_when_database_fails() -> None:
    app = create_app(Settings(environment="test", log_json=False))
    app.dependency_overrides[get_session] = _override_exploding_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["database"] is False
    assert payload["status"] == "degraded"
