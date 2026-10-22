"""FastAPI application factory.

Wires: config, logging, correlation IDs, Problem Details, request size limits, v1 router.
Startup/shutdown: lifespan context handles the DB engine lifecycle.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.api.spa import mount_spa_router
from app.api.v1.executions import register_execution_handlers
from app.api.v1.extraction import register_extraction_handlers
from app.api.v1.router import api_v1_router
from app.api.v1.websites import register_website_handlers
from app.api.v1.workflows import register_workflow_handlers
from app.core.config import Settings, get_settings
from app.core.database import dispose_engine
from app.core.errors import _problem_response, register_exception_handlers
from app.core.logging import configure_logging, get_logger, redact_headers
from app.core.startup_state import (
    assert_required_settings,
    mark_startup_complete,
    reset_for_tests,
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Emit a structlog event per request with the headers redacted.

    Spec 0008 AC-18: `x-api-key` and `authorization` are replaced with
    `"<redacted>"` before serialisation so a captured admin API key cannot
    land in logs. Lives in `app.core.logging.SENSITIVE_REQUEST_HEADERS`.
    """

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._log = get_logger("app.request")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        safe_headers = redact_headers(dict(request.headers))
        response = await call_next(request)
        self._log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            headers=safe_headers,
        )
        return response


class RequestBodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose declared Content-Length exceeds the configured cap."""

    def __init__(self, app: object, max_bytes: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                size = 0
            if size > self.max_bytes:
                return _problem_response(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    title="Payload Too Large",
                    detail=f"Request body exceeds {self.max_bytes} bytes.",
                    code="http.413",
                    instance=str(request.url.path),
                )
        return await call_next(request)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    log = get_logger("app.lifespan")
    log.info("startup", app=settings.app_name, env=settings.environment)

    # Shared httpx.AsyncClient for extraction (spec 0005 AC-4). One client per
    # process; the fetcher reuses the connection pool for every fetch.
    http_client = httpx.AsyncClient(
        http2=True,
        max_redirects=settings.extraction_http_max_redirects,
    )
    app.state.http_client = http_client

    # Spec 0007 AC-12: `/health/ready` reports `startup: ok` only after this
    # flag flips. Set as the last step before yielding so a probe landing
    # mid startup still reads `fail`.
    mark_startup_complete()

    try:
        yield
    finally:
        await http_client.aclose()
        await dispose_engine()
        log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. Call this from entrypoints (uvicorn, tests)."""
    settings = settings or get_settings()
    assert_required_settings(settings)
    configure_logging(settings)
    # Each `create_app` call represents a fresh process (tests spin many); reset
    # the per worker startup gate so the next `_lifespan` enters it as False.
    reset_for_tests()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url=f"{settings.api_v1_prefix}/docs" if settings.environment == "dev" else None,
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.state.settings = settings

    # Order matters: correlation ID runs first so later middleware/log lines see it.
    # `validator=None` accepts any inbound value so client-supplied non-UUID IDs are preserved.
    app.add_middleware(
        CorrelationIdMiddleware,
        header_name="X-Request-ID",
        validator=None,
    )
    app.add_middleware(RequestBodySizeLimitMiddleware, max_bytes=settings.request_body_max_bytes)
    app.add_middleware(RequestLoggingMiddleware)

    register_exception_handlers(app)
    register_website_handlers(app)
    register_workflow_handlers(app)
    register_extraction_handlers(app)
    register_execution_handlers(app)

    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)

    # Spec 0008 AC-10: SPA mount registered LAST so it never shadows a
    # backend route; no op unless `SERVE_ADMIN_UI` is true and the built
    # SPA is on disk.
    mount_spa_router(app, settings)

    return app


app = create_app()
