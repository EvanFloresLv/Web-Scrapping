"""RFC 7807 Problem Details error contract.

Per spec 0001:
- Content type `application/problem+json`.
- `type: "about:blank"` by default.
- Stable per-domain `code` enum (added by each domain spec).
- `correlation_id` as an extension field, bound from asgi-correlation-id.
"""

from __future__ import annotations

from typing import Any

from asgi_correlation_id import correlation_id
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_CONTENT_TYPE = "application/problem+json"


class Problem(BaseModel):
    """Problem Details payload (RFC 7807, extended)."""

    type: str = Field(default="about:blank")
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str | None = Field(default=None, description="Stable per-domain error code.")
    correlation_id: str | None = None


class PlatformError(Exception):
    """Base class for errors that map 1:1 to a Problem response.

    Domain specs add subclasses with their own `code` constants.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "platform.internal_error"
    title: str = "Internal Server Error"

    def __init__(self, detail: str | None = None, *, code: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        if code is not None:
            self.code = code


def _problem_response(
    *,
    status_code: int,
    title: str,
    detail: str | None,
    code: str | None,
    instance: str | None,
) -> JSONResponse:
    problem = Problem(
        title=title,
        status=status_code,
        detail=detail,
        instance=instance,
        code=code,
        correlation_id=correlation_id.get(),
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def _platform_error_handler(request: Request, exc: PlatformError) -> JSONResponse:
    return _problem_response(
        status_code=exc.status_code,
        title=exc.title,
        detail=exc.detail,
        code=exc.code,
        instance=str(request.url.path),
    )


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _problem_response(
        status_code=exc.status_code,
        title=exc.detail if isinstance(exc.detail, str) else "HTTP error",
        detail=exc.detail if not isinstance(exc.detail, str) else None,
        code=f"http.{exc.status_code}",
        instance=str(request.url.path),
    )


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    detail_payload: list[dict[str, Any]] = [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in exc.errors()
    ]
    problem = Problem(
        title="Unprocessable Entity",
        status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Request validation failed.",
        instance=str(request.url.path),
        code="http.422",
        correlation_id=correlation_id.get(),
    )
    body = problem.model_dump(exclude_none=True)
    body["errors"] = detail_payload
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=body,
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Last-resort handler. Specific errors should be raised as PlatformError subclasses.
    return _problem_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        title="Internal Server Error",
        detail=None,
        code="platform.internal_error",
        instance=str(request.url.path),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(PlatformError, _platform_error_handler)  # type: ignore[arg-type]
    # Catches both FastAPI's HTTPException (subclass) and Starlette's own (used by
    # the default 404/405/etc. middleware, which bypass FastAPI's).
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_exception_handler)
