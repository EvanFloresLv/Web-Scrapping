"""Concrete `WorkflowReadPort` adapter for the executions domain (spec 0006 AC-14a).

Lives in the workflows package because it reads the workflows ORM. The port
itself is declared in `app.core.workflows` so the executions domain can import
it without crossing the `import-linter` independence boundary.

The adapter maps ORM rows (`ScrapingWorkflow`, `WorkflowVersion`) into the
small value objects the executor needs (`WorkflowSummary`, `VersionSummary`).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workflows import VersionSummary, WorkflowReadPort, WorkflowSummary
from app.domains.workflows.models import ScrapingWorkflow, WorkflowVersion


class WorkflowReadAdapter(WorkflowReadPort):
    """Read workflows + versions through the request-scoped session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_live_workflow(self, workflow_id: UUID) -> WorkflowSummary | None:
        stmt = select(ScrapingWorkflow).where(
            ScrapingWorkflow.id == workflow_id,
            ScrapingWorkflow.deleted_at.is_(None),
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return WorkflowSummary(
            id=row.id,
            website_id=row.website_id,
            current_version_id=row.current_version_id,
            status=row.status,
        )

    async def get_version_for_workflow(
        self,
        *,
        workflow_id: UUID,
        version_id: UUID,
    ) -> VersionSummary | None:
        stmt = (
            select(WorkflowVersion)
            .join(
                ScrapingWorkflow,
                ScrapingWorkflow.id == WorkflowVersion.workflow_id,
            )
            .where(
                WorkflowVersion.id == version_id,
                WorkflowVersion.workflow_id == workflow_id,
                ScrapingWorkflow.deleted_at.is_(None),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return VersionSummary(
            id=row.id,
            workflow_id=row.workflow_id,
            status=row.status,
            config=row.config,
        )

    async def get_workflow_id_for_version(self, version_id: UUID) -> UUID | None:
        stmt = (
            select(WorkflowVersion.workflow_id)
            .join(
                ScrapingWorkflow,
                ScrapingWorkflow.id == WorkflowVersion.workflow_id,
            )
            .where(
                WorkflowVersion.id == version_id,
                ScrapingWorkflow.deleted_at.is_(None),
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_workflow_ids_for_versions(
        self,
        version_ids: list[UUID],
        *,
        with_deleted: bool = False,
    ) -> dict[UUID, UUID]:
        """Spec 0010 AC-1: one query, one round trip, N rows."""
        if not version_ids:
            return {}
        stmt = (
            select(WorkflowVersion.id, WorkflowVersion.workflow_id)
            .join(
                ScrapingWorkflow,
                ScrapingWorkflow.id == WorkflowVersion.workflow_id,
            )
            .where(WorkflowVersion.id.in_(version_ids))
        )
        if not with_deleted:
            stmt = stmt.where(ScrapingWorkflow.deleted_at.is_(None))
        rows = (await self._session.execute(stmt)).all()
        return dict(rows)


__all__ = ["WorkflowReadAdapter"]
