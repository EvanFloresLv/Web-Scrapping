"""`WorkflowConfig` Pydantic validator for `workflow_versions.config` (AC-5).

Every write to `workflow_versions.config` passes through this model. The shape
is versioned by this file (and the spec that pins it), not by a `config_version`
column; evolution is additive only (new optional fields) until a superseding
spec defines a `config_version` column plus a backfill plan.

`extra='allow'` keeps old rows readable when a new optional field lands later
(a legacy row simply has no key for the new field; a future row with extra
provider specific keys loads without raising). Required fields are the four
spec 0003 pins: `container_selector`, `fields`, `output_schema`, and the
optional `pagination`.

Validator usage: the workflow service calls `WorkflowConfig.model_validate`
on the request payload before every insert or (draft only) update. A rejected
payload surfaces as HTTP 422 via the Problem Details handler in
`app.core.errors`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FieldSpec(BaseModel):
    """One extracted field inside a container element (AC-5).

    `required` (spec 0005 AC-13) is additive: historical configs without the
    key read as `required=True` by default, keeping the extractor strict.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=200)
    selector: str = Field(min_length=1)
    transforms: list[str] = Field(default_factory=list)
    type: str = Field(min_length=1)
    required: bool = True


class PaginationSpec(BaseModel):
    """Optional pagination hint for workflows that walk list pages (AC-5)."""

    model_config = ConfigDict(extra="allow")

    next_selector: str = Field(min_length=1)
    max_pages: int = Field(ge=1)


class WorkflowConfig(BaseModel):
    """Atomic JSONB document validated at write time for `workflow_versions.config`.

    Spec 0003, AC-5. Evolve by adding optional fields; do not remove or rename
    without a superseding spec and a backfill plan.
    """

    model_config = ConfigDict(extra="allow")

    container_selector: str = Field(min_length=1)
    fields: list[FieldSpec] = Field(min_length=1)
    output_schema: dict[str, Any]
    pagination: PaginationSpec | None = None
