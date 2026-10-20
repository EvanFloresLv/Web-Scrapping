"""RFC 7807 Problem Details error contract (spec 0001; consolidated in spec 0007).

Spec 0007 pins:
- Content type `application/problem+json`.
- `type: "about:blank"` by default.
- Stable dotted `code` (regex `^[a-z][a-z0-9_]*\\.[a-z0-9_.]+$`).
- `correlation_id` populated from `asgi_correlation_id.correlation_id.get()`.
- `errors[]` as the single shape for structured per field detail
  (`{code, loc, message, meta?}`).
- `checks` as a first class optional field for the readiness probe payload.
- One shared response builder; no handler or middleware constructs a Problem
  body directly.
"""

from __future__ import annotations

import re
from typing import Any

from asgi_correlation_id import correlation_id
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_CONTENT_TYPE = "application/problem+json"

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_.]+$")
"""Dotted error code shape pinned by spec 0007 AC-2."""


class ErrorDetail(BaseModel):
    """One structured per field error entry in `Problem.errors` (spec 0007 AC-3)."""

    code: str
    loc: list[str | int]
    message: str
    meta: dict[str, Any] | None = None


class Problem(BaseModel):
    """Problem Details payload (RFC 7807, extended per spec 0007)."""

    type: str = Field(default="about:blank")
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str | None = Field(default=None, description="Stable per-domain error code.")
    correlation_id: str | None = None
    errors: list[ErrorDetail] | None = None
    checks: dict[str, str] | None = None


class PlatformError(Exception):
    """Base class for errors that map 1:1 to a Problem response.

    Subclasses set `status_code`, `code` (dotted per spec 0007 AC-2), and
    `title`. Optionally they set `self.errors` with `ErrorDetail` entries;
    the shared `_platform_error_handler` renders them verbatim onto the
    response body (AC-3).
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "platform.internal_error"
    title: str = "Internal Server Error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        errors: list[ErrorDetail] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        if code is not None:
            self.code = code
        self.errors: list[ErrorDetail] | None = errors


def _problem_response(
    *,
    status_code: int,
    title: str,
    detail: str | None,
    code: str | None,
    instance: str | None,
    errors: list[ErrorDetail] | None = None,
    checks: dict[str, str] | None = None,
) -> JSONResponse:
    """Build a Problem Details response (spec 0007 Key invariants).

    The ONLY place a Problem body is constructed. Handlers and middleware
    call this; nothing else serialises `application/problem+json`.
    """
    problem = Problem(
        title=title,
        status=status_code,
        detail=detail,
        instance=instance,
        code=code,
        correlation_id=correlation_id.get(),
        errors=errors,
        checks=checks,
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
        errors=exc.errors,
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
    """Render `RequestValidationError` as Problem Details with `errors[]` (AC-3).

    Each entry is `{code: "http.422", loc, message, meta: {"type": <pydantic type>}}`.
    """
    entries = [
        ErrorDetail(
            code="http.422",
            loc=list(err["loc"]),
            message=err["msg"],
            meta={"type": err["type"]},
        )
        for err in exc.errors()
    ]
    return _problem_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        title="Unprocessable Entity",
        detail="Request validation failed.",
        code="http.422",
        instance=str(request.url.path),
        errors=entries,
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last resort handler (spec 0007 AC-15). Message is logged, not returned."""
    return _problem_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        title="Internal Server Error",
        detail=None,
        code="platform.internal_error",
        instance=str(request.url.path),
    )


def _all_platform_error_subclasses() -> list[type[PlatformError]]:
    """Walk the full `PlatformError` subclass tree (recursive)."""
    seen: set[type[PlatformError]] = set()
    stack: list[type[PlatformError]] = [PlatformError]
    out: list[type[PlatformError]] = []
    while stack:
        cls = stack.pop()
        for sub in cls.__subclasses__():
            if sub in seen:
                continue
            seen.add(sub)
            out.append(sub)
            stack.append(sub)
    return out


def _assert_codes_valid() -> None:
    """Spec 0007 Key invariants: every registered code matches AC-2 and is unique.

    Called from `register_exception_handlers` so a bad rename fails fast at
    app startup (and in CI), not in production.
    """
    seen: dict[str, type[PlatformError]] = {}
    for cls in _all_platform_error_subclasses():
        code = cls.code
        if not CODE_PATTERN.fullmatch(code):
            raise AssertionError(
                f"{cls.__module__}.{cls.__name__}.code={code!r} violates the dotted "
                f"error code shape required by spec 0007 AC-2 ({CODE_PATTERN.pattern!r})."
            )
        if code in seen and seen[code] is not cls:
            raise AssertionError(
                f"Error code {code!r} is registered on both "
                f"{seen[code].__module__}.{seen[code].__name__} and "
                f"{cls.__module__}.{cls.__name__}; codes must be unique "
                f"(spec 0007 Key invariants)."
            )
        seen[code] = cls


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the five shared handlers from spec 0007 AC-1 onto `app`.

    Also runs the startup assertions that enforce the AC-2 regex and the
    uniqueness invariant across every registered `PlatformError` subclass.
    """
    _assert_codes_valid()
    app.add_exception_handler(PlatformError, _platform_error_handler)  # type: ignore[arg-type]
    # Catches both FastAPI's HTTPException (subclass) and Starlette's own (used by
    # the default 404/405/etc. middleware, which bypass FastAPI's).
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_exception_handler)


__all__ = [
    "CODE_PATTERN",
    "PROBLEM_CONTENT_TYPE",
    "ErrorDetail",
    "PlatformError",
    "Problem",
    "_problem_response",
    "register_exception_handlers",
]
