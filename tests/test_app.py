"""Application factory and v1 routing surface.

Covers verify.md items for routes list, OpenAPI exposure, and docs visibility
by environment (dev vs prod).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

EXPECTED_V1_PATHS = {
    "/api/v1/health/live",
    "/api/v1/health/ready",
    "/api/v1/openapi.json",
    "/api/v1/docs",
}


def test_create_app_exposes_expected_v1_routes() -> None:
    """The real client-facing contract: OpenAPI + the docs/openapi URLs."""
    app = create_app(Settings(environment="dev", log_json=False))
    openapi_paths = set(app.openapi().get("paths", {}).keys())
    # OpenAPI only lists business routes; add the two framework-provided URLs
    # that the spec also pins as part of the v1 surface.
    surface = openapi_paths | {app.openapi_url, app.docs_url}
    missing = EXPECTED_V1_PATHS - surface
    assert not missing, f"missing v1 routes: {missing}"


def test_openapi_url_sits_under_v1_prefix() -> None:
    app = create_app(Settings(environment="dev", log_json=False))
    assert app.openapi_url == "/api/v1/openapi.json"


def test_docs_url_is_wired_in_dev() -> None:
    app = create_app(Settings(environment="dev", log_json=False))
    assert app.docs_url == "/api/v1/docs"


def test_docs_url_is_disabled_in_prod() -> None:
    app = create_app(Settings(environment="prod", log_json=True))
    assert app.docs_url is None


@pytest.mark.asyncio
async def test_openapi_json_returns_200() -> None:
    app = create_app(Settings(environment="dev", log_json=False))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["info"]["title"] == "scraping-platform"


@pytest.mark.asyncio
async def test_docs_returns_200_in_dev() -> None:
    app = create_app(Settings(environment="dev", log_json=False))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/docs")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_docs_returns_404_in_prod() -> None:
    app = create_app(Settings(environment="prod", log_json=True))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/docs")
    assert response.status_code == 404
