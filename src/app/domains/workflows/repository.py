"""Repository protocols for the workflows domain (spec 0003).

Shapes the CRUD and lifecycle surface each slice feature will implement
against. Concrete implementations land with the slice that owns them:

- Feature 5 (workflow configuration & versioning) implements `WorkflowRepository`
  and `WorkflowVersionRepository` on top of `AsyncSession` using the patterns
  pinned in [0001](../../../docs/specs/0001-stack-and-architecture/index.md).

Default read filter (AC-20): every `list` and `get` filters out logically
deleted parents (`WHERE scraping_workflows.deleted_at IS NULL` applied through
the join chain). An explicit `with_deleted=True` keyword opts into history
reads; feature 18 (products & provenance) and future retention jobs are the
only callers that pass it.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domains.workflows.models import ScrapingWorkflow, WorkflowVersion


class WorkflowRepository(Protocol):
    """Persistence surface for `ScrapingWorkflow` aggregates (AC-2)."""

    async def get(
        self,
        workflow_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> ScrapingWorkflow | None:
        """Fetch a workflow by id. Soft deleted parents are hidden unless `with_deleted=True`."""
        ...

    async def list_for_website(
        self,
        website_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> list[ScrapingWorkflow]:
        """List workflows under a website, newest first."""
        ...

    async def add(self, workflow: ScrapingWorkflow) -> None:
        """Insert a new workflow aggregate."""
        ...

    async def soft_delete(self, workflow_id: UUID) -> None:
        """Mark a workflow deleted (AC-11). Refused if in-flight executions exist (AC-18)."""
        ...

    async def set_current_version(
        self,
        workflow_id: UUID,
        version_id: UUID,
    ) -> None:
        """Swap `current_version_id` to the newly published version (AC-4, atomic update)."""
        ...


class WorkflowVersionRepository(Protocol):
    """Persistence surface for `WorkflowVersion` rows (AC-2, AC-13)."""

    async def get(
        self,
        version_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> WorkflowVersion | None:
        """Fetch one version. Hidden when its parent is soft deleted unless `with_deleted=True`."""
        ...

    async def list_for_workflow(
        self,
        workflow_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> list[WorkflowVersion]:
        """List versions under a workflow, newest `version_number` first."""
        ...

    async def add_draft(self, version: WorkflowVersion) -> None:
        """Insert a new draft version. Caller holds the parent row lock (AC-16)."""
        ...

    async def update_draft(self, version: WorkflowVersion) -> None:
        """Replace the editable columns on a draft row; raises if `status != 'draft'`."""
        ...

    async def publish(self, version_id: UUID) -> None:
        """Transition a draft to published and auto archive the previous published row (AC-16)."""
        ...

    async def archive(self, version_id: UUID) -> None:
        """Transition a published row to archived (AC-12). Not permitted from `draft`."""
        ...
