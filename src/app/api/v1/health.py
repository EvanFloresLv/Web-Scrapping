"""Health and readiness endpoints.

Live = process is up. Ready = can serve traffic (DB reachable).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session, ping

router = APIRouter(tags=["health"])


class LivePayload(BaseModel):
    status: str = "ok"


class ReadyPayload(BaseModel):
    status: str
    database: bool


@router.get("/health/live", status_code=status.HTTP_200_OK, response_model=LivePayload)
async def live() -> LivePayload:
    """Liveness probe. Returns 200 as long as the process is handling requests."""
    return LivePayload()


@router.get("/health/ready", response_model=ReadyPayload)
async def ready(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReadyPayload:
    """Readiness probe. 200 only when the primary DB answers `SELECT 1`."""
    try:
        db_ok = await ping(session)
    except Exception:
        db_ok = False
    return ReadyPayload(status="ok" if db_ok else "degraded", database=db_ok)
