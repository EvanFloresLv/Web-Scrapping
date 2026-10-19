"""Problem Details error contract (RFC 7807 + spec 0001 extensions).

Covers the Problem payload shape, the content type pin, the PlatformError
mapping, and that validation errors surface as 422 Problem+json with an
`errors` list.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings
from app.core.errors import (
    PROBLEM_CONTENT_TYPE,
    PlatformError,
    Problem,
    register_exception_handlers,
)
from app.main import create_app


def test_problem_default_type_is_about_blank() -> None:
    p = Problem(title="t", status=500)
    dumped = p.model_dump(exclude_none=True)
    assert dumped["type"] == "about:blank"
    assert dumped["title"] == "t"
    assert dumped["status"] == 500
    # None-valued fields must not appear on the wire.
    assert "detail" not in dumped
    assert "correlation_id" not in dumped


def test_problem_content_type_constant() -> None:
    assert PROBLEM_CONTENT_TYPE == "application/problem+json"


def test_platform_error_defaults_and_override() -> None:
    err = PlatformError("boom")
    assert err.status_code == 500
    assert err.code == "platform.internal_error"
    assert err.title == "Internal Server Error"
    assert err.detail == "boom"

    err2 = PlatformError("nope", code="widgets.not_found")
    assert err2.code == "widgets.not_found"


@pytest.mark.asyncio
async def test_platform_error_renders_as_problem_json() -> None:
    """Raising PlatformError in a route surfaces as Problem+json with its code."""

    class BoomError(PlatformError):
        status_code = 418
        code = "widgets.teapot"
        title = "I'm a teapot"

    app = create_app(Settings(environment="test", log_json=False))

    @app.get("/__boom")
    async def _boom() -> None:
        raise BoomError("brew denied")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/__boom")

    assert response.status_code == 418
    assert response.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    body = response.json()
    assert body["code"] == "widgets.teapot"
    assert body["title"] == "I'm a teapot"
    assert body["detail"] == "brew denied"
    assert body["instance"] == "/__boom"


@pytest.mark.asyncio
async def test_validation_error_returns_422_problem_with_errors_list() -> None:
    class Payload(BaseModel):
        name: str
        age: int

    app = create_app(Settings(environment="test", log_json=False))

    @app.post("/__echo")
    async def _echo(payload: Payload) -> Payload:
        return payload

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/__echo", json={"name": "ok"})  # age missing

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    body = response.json()
    assert body["code"] == "http.422"
    assert body["status"] == 422
    assert isinstance(body["errors"], list)
    assert body["errors"]  # at least one entry
    assert {"loc", "msg", "type"}.issubset(body["errors"][0].keys())


@pytest.mark.asyncio
async def test_starlette_http_exception_also_renders_as_problem() -> None:
    """Starlette-raised HTTPExceptions (not just FastAPI's) must hit the handler."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/__starlette")
    async def _s() -> None:
        raise StarletteHTTPException(status_code=409, detail="conflict")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/__starlette")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    body = response.json()
    assert body["code"] == "http.409"
