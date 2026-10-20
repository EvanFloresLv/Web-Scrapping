"""Request and response schemas for the executions endpoints (spec 0006 AC-1, AC-7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExecuteRequest(BaseModel):
    """POST `/workflows/{id}/execute` body (AC-1).

    `extra='forbid'` so unknown fields surface as `invalid_execute_body`
    instead of being silently dropped.
    """

    model_config = ConfigDict(extra="forbid")

    target_url_id: UUID
    version_id: UUID | None = None


class ExecutionItem(BaseModel):
    """One extracted item in a response (AC-7)."""

    model_config = ConfigDict(frozen=True)

    item_index: int
    payload: dict[str, Any]


class ExecutionBody(BaseModel):
    """The execution record subset returned over the wire (AC-7)."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    target_url_id: UUID
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    items_extracted: int
    error_code: str | None
    error_message: str | None
    correlation_id: str
    created_at: datetime


class ExecutionResponse(BaseModel):
    """Top-level response body for POST and GET (AC-7, AC-9)."""

    model_config = ConfigDict(frozen=True)

    execution: ExecutionBody
    items: list[ExecutionItem] = Field(default_factory=list)


__all__ = [
    "ExecuteRequest",
    "ExecutionBody",
    "ExecutionItem",
    "ExecutionResponse",
]
