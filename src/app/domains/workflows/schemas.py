"""Pydantic request/response schemas for the workflows domain (spec 0004).

Wire shapes only; the domain model stays in `models.py`. PATCH models use
`extra='allow'` so the router can detect unknown fields and raise
`immutable_field` with the field name, mirroring the websites domain.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.workflows.config import WorkflowConfig
from app.domains.workflows.enums import WorkflowStatus, WorkflowVersionStatus


class WorkflowCreate(BaseModel):
    """Payload for POST `/websites/{website_id}/workflows` (AC-1)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class WorkflowUpdate(BaseModel):
    """Payload for PATCH `/workflows/{id}` (AC-4).

    `extra='allow'` lets the router detect unknown fields and raise
    `workflow.immutable_field` with the offending key.
    """

    model_config = ConfigDict(extra="allow")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: WorkflowStatus | None = Field(default=None)


class WorkflowRead(BaseModel):
    """Response shape for workflow endpoints (spec 0004 `## Response schemas`)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    website_id: UUID
    name: str
    description: str | None
    status: WorkflowStatus
    current_version_id: UUID | None
    created_at: datetime
    updated_at: datetime


class WorkflowVersionCreate(BaseModel):
    """Payload for POST `/workflows/{workflow_id}/versions` (AC-6)."""

    model_config = ConfigDict(extra="forbid")

    config: WorkflowConfig


class WorkflowVersionUpdate(BaseModel):
    """Payload for PATCH `/workflows/{workflow_id}/versions/{id}` (AC-9)."""

    model_config = ConfigDict(extra="allow")

    config: WorkflowConfig | None = Field(default=None)


class WorkflowVersionRead(BaseModel):
    """Response shape for workflow version endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    version_number: int
    status: WorkflowVersionStatus
    config: dict[str, Any]
    published_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PaginatedList[T](BaseModel):
    """Offset paginated envelope (spec 0001)."""

    items: list[T]
    total: int
    page: int
    page_size: int
