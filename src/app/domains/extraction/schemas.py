"""Value objects + wire schemas for the extraction domain (spec 0005)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ExtractionResult(BaseModel):
    """Terminal result returned by `ExtractionService.run(...)` (AC-1).

    Immutable value object; feature 7 maps `completed` to an executions row
    plus N execution_results, and `failed` to a failed executions row.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["completed", "failed"]
    items: list[dict[str, Any]] | None = None
    items_count: int = 0
    duration_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
    error_details: list[dict[str, Any]] | None = None


class PreviewRequest(BaseModel):
    """Body for `POST .../preview` (AC-2)."""

    model_config = ConfigDict(extra="forbid")

    target_url: str = Field(min_length=1)


class FetchOutcome(BaseModel):
    """Internal fetch success envelope (not an HTTP body)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    body: bytes
    charset: str | None
    final_url: str
