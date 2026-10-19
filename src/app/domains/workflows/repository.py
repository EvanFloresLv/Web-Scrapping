"""Repository for the workflows domain (spec 0004).

One concrete repository class holding the CRUD surface for the two
aggregates: `ScrapingWorkflow` and `WorkflowVersion`. The services depend
on this interface. Soft deleted workflows are filtered out of every read
path by default (AC-16); an explicit `with_deleted=True` opts into history
reads, including versions whose parent workflow is soft deleted.

The transactional lifecycle actions (`publish_atomic`) live here too, so
the lock scope (one `SELECT ... FOR UPDATE` on the parent row) is pinned in
one place and the service layer stays policy only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import exists, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.executions.enums import ExecutionStatus
from app.domains.executions.models import Execution
from app.domains.websites.models import Website
from app.domains.workflows.enums import WorkflowStatus, WorkflowVersionStatus
from app.domains.workflows.models import ScrapingWorkflow, WorkflowVersion


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class WorkflowRepository:
    """Persistence surface for `ScrapingWorkflow` + `WorkflowVersion` (spec 0004)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- parent website lookup (for 404 mapping) ------------------------

    async def get_live_website(self, website_id: UUID) -> Website | None:
        stmt = select(Website).where(
            Website.id == website_id,
            Website.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # ---- scraping_workflows ---------------------------------------------

    async def add_workflow(self, workflow: ScrapingWorkflow) -> None:
        self._session.add(workflow)
        await self._session.flush()

    async def get_workflow(
        self,
        workflow_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> ScrapingWorkflow | None:
        """Return a workflow by id. Hides soft deleted rows by default (AC-16)."""
        stmt = select(ScrapingWorkflow).where(ScrapingWorkflow.id == workflow_id)
        if not with_deleted:
            stmt = stmt.where(ScrapingWorkflow.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_workflow_for_update(
        self,
        workflow_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> ScrapingWorkflow | None:
        """Fetch the workflow row with `FOR UPDATE` (AC-6, AC-11)."""
        stmt = select(ScrapingWorkflow).where(ScrapingWorkflow.id == workflow_id).with_for_update()
        if not with_deleted:
            stmt = stmt.where(ScrapingWorkflow.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_workflow_by_name(
        self,
        *,
        website_id: UUID,
        name: str,
    ) -> ScrapingWorkflow | None:
        """Return a live workflow by `(website_id, name)` for dedup (AC-2, AC-4)."""
        stmt = select(ScrapingWorkflow).where(
            ScrapingWorkflow.website_id == website_id,
            ScrapingWorkflow.name == name,
            ScrapingWorkflow.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_workflows_for_website(
        self,
        website_id: UUID,
        *,
        status_filter: WorkflowStatus | None,
        page: int,
        page_size: int,
        with_deleted: bool = False,
    ) -> tuple[list[ScrapingWorkflow], int]:
        """List workflows under a website with `(items, total)` (AC-3, AC-16)."""
        base = select(ScrapingWorkflow).where(ScrapingWorkflow.website_id == website_id)
        if not with_deleted:
            base = base.where(ScrapingWorkflow.deleted_at.is_(None))
        if status_filter is not None:
            base = base.where(ScrapingWorkflow.status == status_filter.value)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one())

        items_stmt = (
            base.order_by(ScrapingWorkflow.created_at.desc(), ScrapingWorkflow.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self._session.execute(items_stmt)).scalars().all())
        return items, total

    async def soft_delete_workflow(self, workflow: ScrapingWorkflow) -> None:
        """Mark a workflow deleted (AC-5). Versions are hidden through the join filter."""
        workflow.deleted_at = _utcnow()
        await self._session.flush()

    async def has_in_flight_executions(self, workflow_id: UUID) -> bool:
        """True if any execution of this workflow's versions is pending or running (AC-5).

        Short circuits when the `executions` table does not yet exist (feature
        7 ships the migration): no table means no in flight executions, which
        is what spec 0004 AC-5 reasons about ("empty table") expressed in a
        pre migration world. Once feature 7 lands, `to_regclass` returns a
        non null oid and the real query runs.

        Deliberately does NOT filter `workflow_versions.deleted_at`: versions
        are not soft deletable (spec 0003 AC-9), and the gate must see every
        live or hypothetically live execution.
        """
        exists_stmt = select(text("to_regclass('public.executions') IS NOT NULL"))
        table_exists = bool((await self._session.execute(exists_stmt)).scalar_one())
        if not table_exists:
            return False

        subq = (
            select(WorkflowVersion.id).where(WorkflowVersion.workflow_id == workflow_id).subquery()
        )
        stmt = select(
            exists().where(
                Execution.workflow_version_id.in_(select(subq.c.id)),
                Execution.status.in_(
                    [ExecutionStatus.PENDING.value, ExecutionStatus.RUNNING.value]
                ),
            )
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    # ---- workflow_versions ----------------------------------------------

    async def add_version(self, version: WorkflowVersion) -> None:
        self._session.add(version)
        await self._session.flush()

    async def next_version_number(self, workflow_id: UUID) -> int:
        """Return `MAX(version_number) + 1` for the workflow (AC-6).

        Caller must already hold `SELECT ... FOR UPDATE` on the parent row so
        two concurrent inserts serialize.
        """
        stmt = select(func.max(WorkflowVersion.version_number)).where(
            WorkflowVersion.workflow_id == workflow_id,
        )
        current = (await self._session.execute(stmt)).scalar_one_or_none()
        return int(current or 0) + 1

    async def get_version(
        self,
        version_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> WorkflowVersion | None:
        """Return a version by id. Hidden when its parent is soft deleted unless `with_deleted=True` (AC-16)."""
        stmt = (
            select(WorkflowVersion)
            .join(
                ScrapingWorkflow,
                ScrapingWorkflow.id == WorkflowVersion.workflow_id,
            )
            .where(WorkflowVersion.id == version_id)
        )
        if not with_deleted:
            stmt = stmt.where(ScrapingWorkflow.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_version_for_update(self, version_id: UUID) -> WorkflowVersion | None:
        """Re-read a version row inside the parent lock (AC-11)."""
        stmt = select(WorkflowVersion).where(WorkflowVersion.id == version_id).with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_versions_for_workflow(
        self,
        workflow_id: UUID,
        *,
        status_filter: WorkflowVersionStatus | None,
        page: int,
        page_size: int,
        with_deleted: bool = False,
    ) -> tuple[list[WorkflowVersion], int]:
        """List versions under a workflow, newest `version_number` first (AC-8, AC-16)."""
        base = (
            select(WorkflowVersion)
            .join(
                ScrapingWorkflow,
                ScrapingWorkflow.id == WorkflowVersion.workflow_id,
            )
            .where(WorkflowVersion.workflow_id == workflow_id)
        )
        if not with_deleted:
            base = base.where(ScrapingWorkflow.deleted_at.is_(None))
        if status_filter is not None:
            base = base.where(WorkflowVersion.status == status_filter.value)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one())

        items_stmt = (
            base.order_by(WorkflowVersion.version_number.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self._session.execute(items_stmt)).scalars().all())
        return items, total

    async def hard_delete_version(self, version: WorkflowVersion) -> None:
        """Remove a draft version from the table (AC-10)."""
        await self._session.delete(version)
        await self._session.flush()

    async def archive_version(self, version: WorkflowVersion) -> None:
        """Set `status='archived'` and `archived_at` on a published version (AC-12)."""
        version.status = WorkflowVersionStatus.ARCHIVED.value
        version.archived_at = _utcnow()
        await self._session.flush()

    async def publish_atomic(
        self,
        *,
        workflow: ScrapingWorkflow,
        draft: WorkflowVersion,
    ) -> None:
        """Atomically promote `draft` to `published` and archive the previous current version (AC-11).

        Caller must have taken `SELECT ... FOR UPDATE` on `workflow` and
        re-read `draft` inside that lock. This method issues the UPDATEs that
        archive the current published row (if any), promote the draft, and
        swap `scraping_workflows.current_version_id`. All three UPDATEs run on
        the same session and commit together.
        """
        now = _utcnow()

        if workflow.current_version_id is not None:
            await self._session.execute(
                update(WorkflowVersion)
                .where(
                    WorkflowVersion.id == workflow.current_version_id,
                    WorkflowVersion.status == WorkflowVersionStatus.PUBLISHED.value,
                )
                .values(
                    status=WorkflowVersionStatus.ARCHIVED.value,
                    archived_at=now,
                )
            )

        draft.status = WorkflowVersionStatus.PUBLISHED.value
        draft.published_at = now
        workflow.current_version_id = draft.id
        await self._session.flush()
