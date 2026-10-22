"""Request and response schemas for the executions endpoints (spec 0006 AC-1, AC-7).

Spec 0010 adds the list endpoint's response shape (`ExecutionListItem`,
`ExecutionListResponse`) and the query parameter model
(`ExecutionListQuery`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class ExecutionListItem(BaseModel):
    """Row shape for `GET /api/v1/executions` (spec 0010 AC-1).

    Matches `ExecutionBody` (which already denormalises `workflow_id` onto
    the payload per spec 0006 AC-7); the list endpoint reuses that shape as
    is so a row carries everything the UI needs to render the list without
    a second lookup, and the detail route reuses it without reshaping.
    """

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


class ExecutionListResponse(BaseModel):
    """Top-level response body for the list endpoint (spec 0010 AC-1).

    `total` is intentionally omitted (see spec 0010 Rationale): COUNT(*)
    over an unbounded filterable table pays a tax on every page.
    """

    model_config = ConfigDict(frozen=True)

    items: list[ExecutionListItem] = Field(default_factory=list)
    next_cursor: str | None = None


PageSize = Annotated[int, Field(ge=25, le=100)]
ExecutionStatusLiteral = Literal["pending", "running", "completed", "failed"]


class ExecutionListQuery(BaseModel):
    """Query parameters for `GET /api/v1/executions` (spec 0010 AC-3).

    All fields optional; `None` means "do not filter on this axis".
    Validation errors surface as `422 execution.invalid_list_query`
    with the Pydantic field path in `details[].loc`.
    """

    model_config = ConfigDict(extra="forbid")

    cursor: str | None = None
    page_size: PageSize = 50
    workflow_id: UUID | None = None
    status: ExecutionStatusLiteral | None = None
    target_url_id: UUID | None = None
    website_id: UUID | None = None
    correlation_id: str | None = Field(default=None, min_length=1, max_length=255)
    created_from: datetime | None = None
    created_to: datetime | None = None
    with_deleted: bool = False

    @model_validator(mode="after")
    def _validate_window(self) -> ExecutionListQuery:
        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_from > self.created_to
        ):
            raise ValueError("created_from must be <= created_to")
        return self


__all__ = [
    "ExecuteRequest",
    "ExecutionBody",
    "ExecutionItem",
    "ExecutionListItem",
    "ExecutionListQuery",
    "ExecutionListResponse",
    "ExecutionResponse",
    "ExecutionStatusLiteral",
    "PageSize",
]
