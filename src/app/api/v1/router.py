"""Aggregate all v1 routes into one router mounted at `/api/v1`.

Spec 0008 AC-9: the admin API key dependency is applied at the router
group level, not per endpoint, so no new router can forget it. The two
public exceptions are `/api/v1/_meta/error-codes` (spec 0007 AC-14) and
`/health/*` (operator probes), both mounted without the dependency.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1 import executions, extraction, health, metrics, websites, workflows
from app.api.v1._meta import error_codes as meta_error_codes
from app.core.auth import require_api_key

api_v1_router = APIRouter()

# Public (no auth).
api_v1_router.include_router(health.router)
api_v1_router.include_router(meta_error_codes.router)

# Protected: every endpoint under these routers requires `X-API-Key`.
_protected = [Depends(require_api_key)]
api_v1_router.include_router(websites.router, dependencies=_protected)
api_v1_router.include_router(workflows.router, dependencies=_protected)
api_v1_router.include_router(extraction.router, dependencies=_protected)
api_v1_router.include_router(executions.router, dependencies=_protected)
api_v1_router.include_router(metrics.router, dependencies=_protected)
