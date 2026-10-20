"""Liveness and readiness probes (spec 0007 AC-7 through AC-12).

`GET /health/live` returns 200 as long as the ASGI process is handling
requests. It performs zero I/O.

`GET /health/ready` runs three cheap checks in parallel (DB `SELECT 1`,
Alembic head match, startup gate), each bounded by
`settings.health_ready_check_timeout_s`. All three pass => 200. Any check
fails or times out => 503 with `application/problem+json`
(`code: "health.not_ready"`) and the per check status under the `checks`
first class Problem field.

Neither probe requires authentication (spec 0007 AC-14).
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.alembic_head import ALEMBIC_INI_PATH, EXPECTED_HEAD
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.core.errors import _problem_response
from app.core.startup_state import is_startup_complete

router = APIRouter(tags=["health"])

_DB_CHECK = "database"
_ALEMBIC_CHECK = "alembic"
_STARTUP_CHECK = "startup"


class LivePayload(BaseModel):
    status: str = "ok"


class ReadyPayload(BaseModel):
    status: str
    checks: dict[str, str]


@router.get("/health/live", status_code=status.HTTP_200_OK, response_model=LivePayload)
async def live() -> LivePayload:
    """Liveness probe (AC-7). Returns 200 as long as the process is alive."""
    return LivePayload()


async def _check_database(session: AsyncSession) -> str:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return "fail"
    return "ok"


async def _check_alembic(session: AsyncSession) -> str:
    if EXPECTED_HEAD is None:
        return "fail"
    try:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
        current = result.scalar_one_or_none()
    except Exception:
        return "fail"
    if current is None:
        return "mismatch"
    return "ok" if current == EXPECTED_HEAD else "mismatch"


async def _check_startup() -> str:
    return "ok" if is_startup_complete() else "fail"


async def _run_with_timeout(
    name: str,
    coro: asyncio.Future[str] | asyncio.Task[str],
    timeout_s: float,
) -> tuple[str, str, str | None]:
    """Return `(name, status, failure_detail or None)`."""
    try:
        value = await asyncio.wait_for(coro, timeout=timeout_s)
    except TimeoutError:
        return name, "fail", f"{name} check timed out after {timeout_s}s"
    except Exception as exc:
        return name, "fail", f"{name} check raised {type(exc).__name__}"
    return name, value, None


@router.get("/health/ready")
async def ready(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    """Readiness probe (AC-8, AC-9, AC-10, AC-11, AC-12, AC-14).

    Runs the three checks in parallel, each bounded by
    `health_ready_check_timeout_s`; returns 200 only when every check reports
    `ok`. Otherwise returns 503 Problem Details with the per check status.
    """
    timeout = settings.health_ready_check_timeout_s
    results = await asyncio.gather(
        _run_with_timeout(_DB_CHECK, asyncio.ensure_future(_check_database(session)), timeout),
        _run_with_timeout(_ALEMBIC_CHECK, asyncio.ensure_future(_check_alembic(session)), timeout),
        _run_with_timeout(_STARTUP_CHECK, asyncio.ensure_future(_check_startup()), timeout),
    )

    checks: dict[str, str] = {name: value for name, value, _ in results}
    failures: list[str] = [detail for _, _, detail in results if detail is not None]
    for name, value, _ in results:
        if value != "ok":
            if value == "mismatch" and name == _ALEMBIC_CHECK:
                failures.append(
                    f"alembic head mismatch: expected {EXPECTED_HEAD!r}, "
                    f"found {checks[_ALEMBIC_CHECK]!r}"
                )
            elif value == "fail" and name == _ALEMBIC_CHECK and EXPECTED_HEAD is None:
                failures.append(f"alembic head not resolved (ini unreadable at {ALEMBIC_INI_PATH})")
            elif value == "fail" and name == _STARTUP_CHECK:
                failures.append("startup not complete")
            elif value == "fail" and name == _DB_CHECK and not failures:
                failures.append("database check failed")

    all_ok = all(value == "ok" for value in checks.values())
    if all_ok:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=ReadyPayload(status="ok", checks=checks).model_dump(),
        )

    return _problem_response(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        title="Service Not Ready",
        detail=failures[0] if failures else "one or more readiness checks failed",
        code="health.not_ready",
        instance=str(request.url.path),
        checks=checks,
    )
