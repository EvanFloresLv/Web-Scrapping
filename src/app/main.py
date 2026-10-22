"""FastAPI application factory.

Wires: config, logging, correlation IDs, Problem Details, request size limits, v1 router.
Startup/shutdown: lifespan context handles the DB engine lifecycle.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
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
from app.core.database import dispose_engine, get_session_factory
from app.core.errors import _problem_response, register_exception_handlers
from app.core.logging import configure_logging, get_logger, redact_headers
from app.core.observability.flusher import MetricsFlusher
from app.core.observability.registry import get_registry
from app.core.observability.retention import MetricsRetention
from app.core.startup_state import (
    assert_required_settings,
    mark_startup_complete,
    reset_for_tests,
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Emit a `request.completed` structlog event per request (spec 0011 AC-8).

    Headers are redacted via `SENSITIVE_REQUEST_HEADERS` at the edge (spec
    0008 AC-18); the `redact_sensitive_keys` processor is defence in depth
    (spec 0011 AC-6). The event carries `method`, `path`, `status`, and
    `duration_ms`; no request or response body is ever logged (AC-7). The
    `correlation_id` comes from the `CorrelationIdMiddleware`'s contextvar
    binding; this handler never passes it as a kwarg.
    """

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._log = get_logger("app.request")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        safe_headers = redact_headers(dict(request.headers))
        start_ns = time.perf_counter_ns()
        response = await call_next(request)
        elapsed_ns = time.perf_counter_ns() - start_ns
        duration_ms = elapsed_ns // 1_000_000
        duration_s = elapsed_ns / 1_000_000_000

        # Spec 0011 AC-3: bridge asgi-correlation-id into structlog
        # contextvars so this event carries the id without a per call
        # kwarg. `BaseHTTPMiddleware` runs `call_next` in a child task, so
        # the asgi-correlation-id `ContextVar` set inside is not visible
        # here; the middleware writes the id onto the response as
        # `X-Request-ID`, which is the source of truth we can read.
        structlog.contextvars.clear_contextvars()
        cid = response.headers.get("x-request-id") or "-"
        structlog.contextvars.bind_contextvars(correlation_id=cid)

        # Spec 0012 AC-1 / AC-2: observe the HTTP histogram + bump the counter.
        # `route` must be the FastAPI path template, never the raw path, to
        # keep label cardinality bounded. Starlette records the matched
        # route under `request.scope["route"]` after routing resolves; it is
        # missing for unmatched 404s, which we group under the literal
        # "unmatched" bucket so a scan does not blow up cardinality on
        # random paths. The scope key for a matched endpoint is
        # `route.path` (templated), e.g. `/api/v1/executions/{execution_id}`.
        matched_route: str
        route_obj = request.scope.get("route")
        if route_obj is not None and hasattr(route_obj, "path"):
            matched_route = str(route_obj.path)
        else:
            matched_route = "unmatched"
        status_class = f"{response.status_code // 100}xx"
        registry = get_registry()
        registry.http_request_duration_seconds.labels(
            method=request.method,
            route=matched_route,
            status_class=status_class,
        ).observe(duration_s)
        registry.http_requests_total.labels(
            method=request.method,
            route=matched_route,
            status_class=status_class,
        ).inc()

        self._log.info(
            "request.completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
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
    log.info(
        "app.startup_completed",
        app=settings.app_name,
        env=settings.environment,
    )

    # Shared httpx.AsyncClient for extraction (spec 0005 AC-4). One client per
    # process; the fetcher reuses the connection pool for every fetch.
    http_client = httpx.AsyncClient(
        http2=True,
        max_redirects=settings.extraction_http_max_redirects,
    )
    app.state.http_client = http_client

    # Spec 0012 AC-4: periodic flusher that snapshots the prometheus registry
    # and upserts per minute deltas into `metric_minute`. Always on in every
    # environment per AC-12 (no feature flag).
    flusher = MetricsFlusher(
        session_factory=get_session_factory(),
        interval_s=float(settings.metrics_flush_interval_s),
        buffer_cap_minutes=settings.metrics_buffer_cap_minutes,
        registry=get_registry(),
    )
    flusher.start()
    app.state.metrics_flusher = flusher

    # Spec 0012 AC-4: daily retention sweep.
    retention = MetricsRetention(
        session_factory=get_session_factory(),
        retention_days=settings.metrics_retention_days,
    )
    retention.start()
    app.state.metrics_retention = retention

    # Spec 0007 AC-12: `/health/ready` reports `startup: ok` only after this
    # flag flips. Set as the last step before yielding so a probe landing
    # mid startup still reads `fail`.
    mark_startup_complete()

    try:
        yield
    finally:
        await retention.stop()
        await flusher.stop()
        await http_client.aclose()
        await dispose_engine()
        log.info("app.shutdown_started")


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
