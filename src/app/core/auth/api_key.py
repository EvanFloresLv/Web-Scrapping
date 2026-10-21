"""API key auth dependency for the admin UI foundation (spec 0008 AC-9).

A stub: a single `ADMIN_API_KEY` from settings compared against the
`X-API-Key` header via `hmac.compare_digest` (constant time, no timing
side channel). Feature 26 replaces the mechanism without touching the
admin UI shell's `authStore` boundary.

The dependency is wired at the router group level in `app.main` so there
is no "forgot to add it" failure mode on new endpoints under `/api/v1`.
Spec 0008 keeps `/api/v1/_meta/error-codes` and `/health/*` public.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, status

from app.core.config import Settings, get_settings
from app.core.errors import PlatformError


class AdminUIUnauthenticated(PlatformError):  # noqa: N818 (spec 0008 AC-9 pins the class name)
    """Raised when a request to the admin UI API lacks a valid API key.

    Rendered by the shared spec 0007 Problem Details handler with
    `code: admin_ui.unauthenticated` and the request's `correlation_id`.
    Never raise a bare `HTTPException` here: that would bypass the shared
    Problem Details shape (spec 0008 AC-9 and Key invariants).
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "admin_ui.unauthenticated"
    title = "Unauthorized"


async def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Reject requests that do not carry a matching `X-API-Key` header.

    Compared with `hmac.compare_digest` so a wrong key cannot be
    distinguished from a right one by response time. The expected key is
    read from `settings.admin_api_key`, which is validated at startup to
    be non blank and at least 16 characters (spec 0008 Security model).
    """
    expected = settings.admin_api_key
    if x_api_key is None or not hmac.compare_digest(x_api_key, expected):
        raise AdminUIUnauthenticated(detail="Missing or invalid X-API-Key header.")
