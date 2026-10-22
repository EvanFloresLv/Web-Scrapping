"""Admin UI API key gate (spec 0008 AC-9, AC-18).

Covers the router group dependency: every `/api/v1` endpoint requires a
matching `X-API-Key` except the two public ones (`/api/v1/_meta/error-codes`
and `/api/v1/health/*`), and the structlog header deny list is applied so
the key never lands in a captured log.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.logging import SENSITIVE_REQUEST_HEADERS, redact_headers
from app.core.startup_state import assert_required_settings, mark_startup_complete
from app.main import create_app
from tests.conftest import TEST_ADMIN_API_KEY


def _build_app() -> AsyncClient:
    app = create_app(Settings(environment="test", log_json=False, admin_api_key=TEST_ADMIN_API_KEY))
    mark_startup_complete()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_protected_endpoint_without_header_returns_401_problem() -> None:
    async with _build_app() as ac:
        response = await ac.get("/api/v1/websites")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "admin_ui.unauthenticated"
    assert body["title"] == "Unauthorized"


@pytest.mark.asyncio
async def test_protected_endpoint_with_wrong_header_returns_401() -> None:
    async with _build_app() as ac:
        response = await ac.get("/api/v1/websites", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401
    assert response.json()["code"] == "admin_ui.unauthenticated"


@pytest.mark.asyncio
async def test_health_live_is_public() -> None:
    async with _build_app() as ac:
        response = await ac.get("/api/v1/health/live")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_meta_error_codes_is_public() -> None:
    async with _build_app() as ac:
        response = await ac.get("/api/v1/_meta/error-codes")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_ui_unauthenticated_code_is_in_registry() -> None:
    async with _build_app() as ac:
        response = await ac.get("/api/v1/_meta/error-codes")
    codes = {entry["code"] for entry in response.json()}
    assert "admin_ui.unauthenticated" in codes


def test_header_deny_list_covers_api_key_and_authorization() -> None:
    assert "x-api-key" in SENSITIVE_REQUEST_HEADERS
    assert "authorization" in SENSITIVE_REQUEST_HEADERS


def test_redact_headers_redacts_sensitive_values_only() -> None:
    out = redact_headers(
        {
            "X-API-Key": "secret-key",
            "Authorization": "Bearer token",
            "X-Request-ID": "req-123",
        }
    )
    assert out["x-api-key"] == "<redacted>"
    assert out["authorization"] == "<redacted>"
    assert out["x-request-id"] == "req-123"


def test_settings_validator_rejects_blank_admin_api_key() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(environment="test", admin_api_key="   ")


def test_settings_validator_rejects_too_short_admin_api_key() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(environment="test", admin_api_key="short")


def test_assert_required_settings_passes_on_valid_key() -> None:
    assert_required_settings(
        Settings(environment="test", admin_api_key=TEST_ADMIN_API_KEY)
    )  # no raise
