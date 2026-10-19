"""Pydantic schemas for the websites domain (spec 0002).

Wire representations only; the domain model stays in `models.py`. Field
constraints mirror the DB CHECKs (lengths, status enum) so Pydantic rejects
clearly invalid input at the edge before it reaches the service layer.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.websites.enums import TargetStatus, WebsiteStatus


class WebsiteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=253)
    display_name: str = Field(min_length=1, max_length=200)


class WebsiteUpdate(BaseModel):
    """Immutable `host` is deliberately absent; a request with `host` is
    rejected at the router with `immutable_field` (AC-10) rather than being
    silently dropped by `extra='forbid'`."""

    model_config = ConfigDict(extra="allow")

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    status: WebsiteStatus | None = Field(default=None)


class WebsiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    host: str
    display_name: str
    status: WebsiteStatus
    created_at: datetime
    updated_at: datetime


class TargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    label: str = Field(min_length=1, max_length=200)


class TargetUpdate(BaseModel):
    """Immutable `url` is handled the same way as `host` on websites."""

    model_config = ConfigDict(extra="allow")

    label: str | None = Field(default=None, min_length=1, max_length=200)
    status: TargetStatus | None = Field(default=None)


class TargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    website_id: UUID
    url: str
    label: str
    status: TargetStatus
    created_at: datetime
    updated_at: datetime


class PaginatedList[T](BaseModel):
    """Offset-paginated list envelope (spec 0001 + spec 0002 AC-8)."""

    items: list[T]
    total: int
    page: int
    page_size: int
