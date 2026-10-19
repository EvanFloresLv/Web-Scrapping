"""Aggregate all v1 routes into one router mounted at `/api/v1`."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health

api_v1_router = APIRouter()
api_v1_router.include_router(health.router)
