"""Cross domain read port for the workflows aggregate (spec 0006 AC-14a).

The executions domain cannot import `app.domains.workflows` directly: the
`import-linter` independence contract keeps every `app.domains.*` package
isolated. This module lives in `app.core` so both sides can depend on it: the
executions service imports the Protocol and value objects, and the workflows
domain ships a concrete adapter (`WorkflowReadAdapter`) that implements it.

Only the reads `ExecutionService` needs land here. Writes stay in the
workflows domain. The value objects (`WorkflowSummary`, `VersionSummary`) are
plain Pydantic models carrying the fields the executor reads, so neither side
touches the other's ORM rows.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WorkflowSummary(BaseModel):
    """Minimal workflow view the executor needs (spec 0006 AC-2, AC-3, AC-4)."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    website_id: UUID
    current_version_id: UUID | None
    status: str


class VersionSummary(BaseModel):
    """Minimal version view the executor needs (spec 0006 AC-2)."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    workflow_id: UUID
    status: str
    config: dict[str, Any]


class WorkflowReadPort(Protocol):
    """Narrow read surface for the executor (spec 0006 AC-14a)."""

    async def get_live_workflow(self, workflow_id: UUID) -> WorkflowSummary | None:
        """Return the live workflow by id. `None` when missing or soft deleted."""
        ...

    async def get_version_for_workflow(
        self,
        *,
        workflow_id: UUID,
        version_id: UUID,
    ) -> VersionSummary | None:
        """Return the version only when it belongs to the given workflow."""
        ...

    async def get_workflow_id_for_version(self, version_id: UUID) -> UUID | None:
        """Return the parent `workflow_id` for a version.

        Used by `GET /executions/{id}` to populate the response's
        `execution.workflow_id` without the executions domain importing the
        workflows ORM (spec 0006 AC-7, AC-14a). Returns `None` when the
        version or its parent workflow is soft deleted or missing.
        """
        ...


__all__ = [
    "VersionSummary",
    "WorkflowReadPort",
    "WorkflowSummary",
]
