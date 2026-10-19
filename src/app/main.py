"""FastAPI application factory.

Wires: config, logging, correlation IDs, Problem Details, request size limits, v1 router.
Startup/shutdown: lifespan context handles the DB engine lifecycle.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.api.v1.router import api_v1_router
from app.api.v1.websites import register_website_handlers
from app.core.config import Settings, get_settings
from app.core.database import dispose_engine
from app.core.errors import PROBLEM_CONTENT_TYPE, Problem, register_exception_handlers
from app.core.logging import configure_logging, get_logger


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
                problem = Problem(
                    title="Payload Too Large",
                    status=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"Request body exceeds {self.max_bytes} bytes.",
                    code="http.413",
                    instance=str(request.url.path),
                )
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content=problem.model_dump(exclude_none=True),
                    media_type=PROBLEM_CONTENT_TYPE,
                )
        return await call_next(request)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    log = get_logger("app.lifespan")
    log.info("startup", app=settings.app_name, env=settings.environment)
    try:
        yield
    finally:
        await dispose_engine()
        log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. Call this from entrypoints (uvicorn, tests)."""
    settings = settings or get_settings()
    configure_logging(settings)

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

    register_exception_handlers(app)
    register_website_handlers(app)

    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
