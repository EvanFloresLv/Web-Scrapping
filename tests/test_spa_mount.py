"""SPA router mount (spec 0008 AC-10).

With `SERVE_ADMIN_UI=true` and a stub `index.html` on disk:
- GET `/websites` (HTML `Accept`) returns the SPA HTML with 200.
- GET `/api/v1/websites` still returns backend JSON (401 Problem Details
  without the API key, so a reserved prefix is never shadowed).
- GET `/websites` (JSON `Accept`) returns a Problem Details 404, so a
  typed JSON client that misroutes a call does NOT get SPA HTML.
- GET `/api/v1/does-not-exist` returns Problem Details 404 (reserved
  prefix fallthrough).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.startup_state import mark_startup_complete
from app.main import create_app
from tests.conftest import TEST_ADMIN_API_KEY


@pytest.fixture
def spa_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "frontend-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>admin</title>", encoding="utf-8")
    return dist


@pytest.mark.asyncio
async def test_spa_serves_index_on_html_accept(spa_dist: Path) -> None:
    app = create_app(
        Settings(
            environment="test",
            log_json=False,
            admin_api_key=TEST_ADMIN_API_KEY,
            serve_admin_ui=True,
            admin_ui_dist_path=str(spa_dist),
        )
    )
    mark_startup_complete()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/websites", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "admin" in resp.text


@pytest.mark.asyncio
async def test_spa_returns_404_on_json_accept(spa_dist: Path) -> None:
    app = create_app(
        Settings(
            environment="test",
            log_json=False,
            admin_api_key=TEST_ADMIN_API_KEY,
            serve_admin_ui=True,
            admin_ui_dist_path=str(spa_dist),
        )
    )
    mark_startup_complete()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/websites", headers={"Accept": "application/json"})
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_reserved_prefix_still_yields_problem_details(spa_dist: Path) -> None:
    app = create_app(
        Settings(
            environment="test",
            log_json=False,
            admin_api_key=TEST_ADMIN_API_KEY,
            serve_admin_ui=True,
            admin_ui_dist_path=str(spa_dist),
        )
    )
    mark_startup_complete()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/does-not-exist", headers={"Accept": "text/html"})
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_api_route_still_wins_over_spa(spa_dist: Path) -> None:
    app = create_app(
        Settings(
            environment="test",
            log_json=False,
            admin_api_key=TEST_ADMIN_API_KEY,
            serve_admin_ui=True,
            admin_ui_dist_path=str(spa_dist),
        )
    )
    mark_startup_complete()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Without the API key: backend 401 Problem Details, never SPA HTML.
        resp = await ac.get("/api/v1/websites", headers={"Accept": "text/html"})
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_spa_disabled_by_default() -> None:
    app = create_app(
        Settings(
            environment="test",
            log_json=False,
            admin_api_key=TEST_ADMIN_API_KEY,
        )
    )
    mark_startup_complete()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/websites", headers={"Accept": "text/html"})
    assert resp.status_code == 404
