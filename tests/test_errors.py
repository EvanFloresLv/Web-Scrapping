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
    assert {"code", "loc", "message"}.issubset(body["errors"][0].keys())
    assert body["errors"][0]["code"] == "http.422"
    assert body["errors"][0]["meta"]["type"]  # pydantic error type carried in meta


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


# ---------------------------------------------------------------------------
# Spec 0007 AC coverage
# ---------------------------------------------------------------------------


def test_code_pattern_regex_matches_dotted_shape_only() -> None:
    """covers: AC-2 (code regex `^[a-z][a-z0-9_]*\\.[a-z0-9_.]+$`)."""
    from app.core.errors import CODE_PATTERN

    for ok in (
        "fetch.timeout",
        "workflow.version_not_found",
        "platform.internal_error",
        "http.422",
        "a.b.c.d",
    ):
        assert CODE_PATTERN.fullmatch(ok), f"{ok!r} should pass"

    for bad in (
        "duplicate_website",  # no dot
        "Workflow.not_found",  # uppercase
        ".leading_dot",
        "trailing_dot.",
        "no_prefix",
    ):
        assert not CODE_PATTERN.fullmatch(bad), f"{bad!r} should fail"


def test_assert_codes_valid_catches_bad_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    """covers: AC-2 (startup assertion raises on an invalid code shape).

    Uses a stand in object instead of a real `PlatformError` subclass:
    subclasses register permanently in `PlatformError.__subclasses__()` and
    would poison every later test's `create_app` call.
    """
    from types import SimpleNamespace

    from app.core import errors as errors_mod

    bad = SimpleNamespace(code="no_dot_here", __module__="test", __name__="_Bad")
    monkeypatch.setattr(errors_mod, "_all_platform_error_subclasses", lambda: [bad])
    with pytest.raises(AssertionError, match="dotted error code shape"):
        errors_mod._assert_codes_valid()


def test_assert_codes_valid_catches_duplicate_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """covers: AC-2 Key invariant (one code must map to one subclass)."""
    from types import SimpleNamespace

    from app.core import errors as errors_mod

    a = SimpleNamespace(code="duplicate.code", __module__="test", __name__="_A")
    b = SimpleNamespace(code="duplicate.code", __module__="test", __name__="_B")
    monkeypatch.setattr(errors_mod, "_all_platform_error_subclasses", lambda: [a, b])
    with pytest.raises(AssertionError, match="codes must be unique"):
        errors_mod._assert_codes_valid()


@pytest.mark.asyncio
async def test_correlation_id_omitted_when_context_unset() -> None:
    """covers: AC-4 (no `correlation_id` key when `asgi_correlation_id` context is empty).

    The ASGI middleware normally sets the contextvar, but calling the response
    builder directly (as a middleware or background task might) must not emit
    `"correlation_id": null` or `"correlation_id": "None"`.
    """
    from app.core.errors import _problem_response

    response = _problem_response(
        status_code=500,
        title="t",
        detail=None,
        code="platform.internal_error",
        instance="/x",
    )
    body = response.body.decode()
    assert '"correlation_id"' not in body
    assert '"None"' not in body


@pytest.mark.asyncio
async def test_unhandled_exception_returns_500_platform_internal_error_no_detail() -> None:
    """covers: AC-15 (fallback handler: 500, code=platform.internal_error, detail=None)."""
    app = create_app(Settings(environment="test", log_json=False))

    @app.get("/__crash")
    async def _crash() -> None:
        raise RuntimeError("real stack trace lives in structlog, not the body")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/__crash")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    body = response.json()
    assert body["code"] == "platform.internal_error"
    assert body["status"] == 500
    assert body["title"] == "Internal Server Error"
    assert "detail" not in body, "detail must be omitted so the stack never leaks"
