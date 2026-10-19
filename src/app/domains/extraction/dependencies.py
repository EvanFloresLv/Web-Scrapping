"""FastAPI dependencies for the extraction domain (spec 0005 AC-4).

Three dependencies:

- `get_http_client(request)` returns the shared `httpx.AsyncClient` built
  by the app lifespan and attached to `app.state.http_client`. Tests
  override it to install `respx` fakes without touching module globals.
- `get_fetcher_limits(request)` reads the six `EXTRACTION_HTTP_*` fields
  off `app.state.settings` into a frozen `FetcherLimits`.
- `get_http_fetcher(client, limits)` composes the two into an `HttpFetcher`.
"""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import Depends, Request

from app.core.config import Settings
from app.domains.extraction.fetcher import FetcherLimits, HttpFetcher


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Return the lifespan-managed shared `httpx.AsyncClient` (AC-4)."""
    client = getattr(request.app.state, "http_client", None)
    if client is None:  # pragma: no cover - lifespan guarantees non-null
        raise RuntimeError("http_client is not initialized on app.state")
    assert isinstance(client, httpx.AsyncClient)
    return client


def get_fetcher_limits(request: Request) -> FetcherLimits:
    """Read the extraction fetch limits from pydantic-settings (AC-4)."""
    settings: Settings = request.app.state.settings
    return FetcherLimits(
        connect_timeout_s=settings.extraction_http_connect_timeout_s,
        read_timeout_s=settings.extraction_http_read_timeout_s,
        total_timeout_s=settings.extraction_http_total_timeout_s,
        max_body_bytes=settings.extraction_http_max_body_bytes,
        max_redirects=settings.extraction_http_max_redirects,
        user_agent=settings.extraction_http_user_agent,
    )


def get_http_fetcher(
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    limits: Annotated[FetcherLimits, Depends(get_fetcher_limits)],
) -> HttpFetcher:
    return HttpFetcher(client=client, limits=limits)
