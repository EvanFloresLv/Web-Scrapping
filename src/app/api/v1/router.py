"""Aggregate all v1 routes into one router mounted at `/api/v1`."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import executions, extraction, health, websites, workflows
from app.api.v1._meta import error_codes as meta_error_codes

api_v1_router = APIRouter()
api_v1_router.include_router(health.router)
api_v1_router.include_router(meta_error_codes.router)
api_v1_router.include_router(websites.router)
api_v1_router.include_router(workflows.router)
api_v1_router.include_router(extraction.router)
api_v1_router.include_router(executions.router)
