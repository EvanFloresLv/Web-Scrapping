"""Read-only repository seams for the preview endpoint (spec 0005 AC-3).

Only two lookups: fetch a live `WorkflowVersion` by `(workflow_id,
version_id)` and resolve a `(website_id, canonical_url)` pair against
`target_urls`. The service layer uses these to translate 404 paths before
`ExtractionService.run(...)` ever touches HTTP.

Keeps the extraction domain layered over workflows + websites without
duplicating their repositories.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.websites.models import TargetURL
from app.domains.workflows.models import ScrapingWorkflow, WorkflowVersion


class ExtractionReadRepository:
    """Narrow read-only surface for the preview endpoint (AC-3)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_live_workflow(self, workflow_id: UUID) -> ScrapingWorkflow | None:
        stmt = select(ScrapingWorkflow).where(
            ScrapingWorkflow.id == workflow_id,
            ScrapingWorkflow.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_version(
        self,
        *,
        workflow_id: UUID,
        version_id: UUID,
    ) -> WorkflowVersion | None:
        """Return the version only when its parent workflow is live and matches."""
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
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_live_target(
        self,
        *,
        website_id: UUID,
        canonical_url: str,
    ) -> TargetURL | None:
        """Resolve a target by `(website_id, canonical_url)` filtered to live rows (AC-3)."""
        stmt = select(TargetURL).where(
            TargetURL.website_id == website_id,
            TargetURL.url == canonical_url,
            TargetURL.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
