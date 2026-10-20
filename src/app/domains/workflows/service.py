"""Service layer for the workflows domain (spec 0004).

Policy only: lifecycle gates, coherence checks, and the publish race live
here; raw SQL belongs in the repository. Two services carve the surface:

- `WorkflowService` owns the `scraping_workflows` aggregate.
- `WorkflowVersionService` owns the `workflow_versions` child, including
  the atomic publish and the one shot retry on `(workflow_id, version_number)`
  races.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.workflows.config import WorkflowConfig
from app.domains.workflows.enums import WorkflowStatus, WorkflowVersionStatus
from app.domains.workflows.errors import (
    HasInFlightExecutionsError,
    VersionConflictError,
    VersionIsCurrentError,
    VersionNotDraftError,
    VersionNotFoundError,
    VersionNotPublishedError,
    WebsiteNotFoundError,
    WorkflowInactiveError,
    WorkflowNameConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from app.domains.workflows.models import ScrapingWorkflow, WorkflowVersion
from app.domains.workflows.repository import WorkflowRepository


def _coerce_config(payload: Any) -> WorkflowConfig:
    """Validate shape + coherence of a `WorkflowConfig` payload (AC-7).

    Returns the validated model so callers can store a canonical form. Raises
    `WorkflowValidationError` with a `details` list naming each bad field.
    """
    # Pydantic may hand us either a dict (API path) or an already-validated
    # `WorkflowConfig` (service callers).
    if isinstance(payload, WorkflowConfig):
        config = payload
    else:
        try:
            config = WorkflowConfig.model_validate(payload)
        except PydanticValidationError as exc:
            details = [
                {
                    "field": ".".join(str(loc) for loc in err["loc"]),
                    "message": err["msg"],
                }
                for err in exc.errors()
            ]
            raise WorkflowValidationError(
                "WorkflowConfig validation failed",
                details=details,
            ) from exc

    # Coherence check (a): field name uniqueness.
    names = [field.name for field in config.fields]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise WorkflowValidationError(
            "duplicate field names",
            details=[
                {"field": f"fields.{name}", "message": "duplicate field name"}
                for name in duplicates
            ],
        )

    # Coherence check (b): every field name is a key in `output_schema`.
    missing = sorted(name for name in names if name not in config.output_schema)
    if missing:
        raise WorkflowValidationError(
            "output_schema does not cover every field",
            details=[
                {
                    "field": f"output_schema.{name}",
                    "message": "missing key for declared field",
                }
                for name in missing
            ],
        )

    return config


class WorkflowService:
    """Use cases that mutate or read a `ScrapingWorkflow` aggregate."""

    def __init__(self, session: AsyncSession, repository: WorkflowRepository) -> None:
        self._session = session
        self._repo = repository

    async def create(
        self,
        *,
        website_id: UUID,
        name: str,
        description: str | None,
    ) -> ScrapingWorkflow:
        """Create a workflow under a website (AC-1, AC-2)."""
        website = await self._repo.get_live_website(website_id)
        if website is None:
            raise WebsiteNotFoundError(f"website {website_id} not found")

        existing = await self._repo.get_workflow_by_name(
            website_id=website_id,
            name=name,
        )
        if existing is not None:
            raise WorkflowNameConflictError(
                f"workflow {name!r} already exists under website {website_id}"
            )

        workflow = ScrapingWorkflow(
            website_id=website_id,
            name=name,
            description=description,
        )
        try:
            await self._repo.add_workflow(workflow)
        except IntegrityError as exc:
            await self._session.rollback()
            existing = await self._repo.get_workflow_by_name(
                website_id=website_id,
                name=name,
            )
            if existing is None:
                raise
            raise WorkflowNameConflictError(
                f"workflow {name!r} already exists under website {website_id}"
            ) from exc
        return workflow

    async def get(self, workflow_id: UUID) -> ScrapingWorkflow:
        workflow = await self._repo.get_workflow(workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(f"workflow {workflow_id} not found")
        return workflow

    async def list_for_website(
        self,
        website_id: UUID,
        *,
        page: int,
        page_size: int,
        status_filter: WorkflowStatus | None,
        with_deleted: bool,
    ) -> tuple[list[ScrapingWorkflow], int]:
        website = await self._repo.get_live_website(website_id)
        if website is None:
            raise WebsiteNotFoundError(f"website {website_id} not found")
        return await self._repo.list_workflows_for_website(
            website_id,
            status_filter=status_filter,
            page=page,
            page_size=page_size,
            with_deleted=with_deleted,
        )

    async def update(
        self,
        workflow_id: UUID,
        *,
        name: str | None,
        description: str | None,
        description_set: bool,
        status: WorkflowStatus | None,
    ) -> ScrapingWorkflow:
        """Patch mutable fields on a workflow (AC-4).

        `description_set=True` means the caller sent `description` in the
        payload (and wants it applied, even if `null`); `False` means leave
        the column untouched.
        """
        workflow = await self.get(workflow_id)

        if name is not None and name != workflow.name:
            existing = await self._repo.get_workflow_by_name(
                website_id=workflow.website_id,
                name=name,
            )
            if existing is not None and existing.id != workflow.id:
                raise WorkflowNameConflictError(
                    f"workflow {name!r} already exists under website {workflow.website_id}"
                )
            workflow.name = name

        if description_set:
            workflow.description = description

        if status is not None:
            workflow.status = status.value

        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise WorkflowNameConflictError(
                f"workflow {name!r} already exists under website {workflow.website_id}"
            ) from exc
        await self._session.refresh(workflow)
        return workflow

    async def delete(self, workflow_id: UUID) -> None:
        """Soft delete a workflow (AC-5).

        Idempotent: already deleted or missing returns `None` and the router
        maps that to `204`. Refused with `409 has_in_flight_executions` if any
        execution of this workflow's versions is pending or running.
        """
        workflow = await self._repo.get_workflow(workflow_id)
        if workflow is None:
            return
        if await self._repo.has_in_flight_executions(workflow_id):
            raise HasInFlightExecutionsError(
                f"workflow {workflow_id} has pending or running executions"
            )
        await self._repo.soft_delete_workflow(workflow)


class WorkflowVersionService:
    """Use cases that mutate or read a `WorkflowVersion` under a workflow."""

    def __init__(self, session: AsyncSession, repository: WorkflowRepository) -> None:
        self._session = session
        self._repo = repository

    async def _load_live_workflow(self, workflow_id: UUID) -> ScrapingWorkflow:
        workflow = await self._repo.get_workflow(workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(f"workflow {workflow_id} not found")
        return workflow

    async def _load_version(
        self,
        *,
        workflow_id: UUID,
        version_id: UUID,
    ) -> WorkflowVersion:
        """Load a version checking the `(workflow_id, version_id)` pair (AC-8)."""
        version = await self._repo.get_version(version_id)
        if version is None or version.workflow_id != workflow_id:
            raise VersionNotFoundError(f"version {version_id} not found")
        return version

    async def create_draft(
        self,
        *,
        workflow_id: UUID,
        config_payload: Any,
    ) -> WorkflowVersion:
        """Create a draft version under a workflow (AC-6, AC-7).

        One retry on `IntegrityError`: a lost race on
        `(workflow_id, version_number)` gets a fresh `MAX(version_number)+1`
        under a re-acquired parent lock; a second violation returns
        `409 workflow.version_conflict`.
        """
        config = _coerce_config(config_payload)

        for attempt in range(2):
            workflow = await self._repo.get_workflow_for_update(workflow_id)
            if workflow is None:
                raise WorkflowNotFoundError(f"workflow {workflow_id} not found")
            if workflow.status != WorkflowStatus.ACTIVE.value:
                raise WorkflowInactiveError(
                    f"workflow {workflow_id} is inactive; cannot add a version"
                )

            next_number = await self._repo.next_version_number(workflow_id)
            version = WorkflowVersion(
                workflow_id=workflow_id,
                version_number=next_number,
                config=config.model_dump(),
            )
            try:
                await self._repo.add_version(version)
            except IntegrityError as exc:
                await self._session.rollback()
                if attempt == 1:
                    raise VersionConflictError(
                        f"could not assign a version number for workflow {workflow_id}"
                    ) from exc
                continue
            return version

        raise VersionConflictError(f"could not assign a version number for workflow {workflow_id}")

    async def get(
        self,
        *,
        workflow_id: UUID,
        version_id: UUID,
    ) -> WorkflowVersion:
        return await self._load_version(workflow_id=workflow_id, version_id=version_id)

    async def list_for_workflow(
        self,
        workflow_id: UUID,
        *,
        page: int,
        page_size: int,
        status_filter: WorkflowVersionStatus | None,
        with_deleted: bool,
    ) -> tuple[list[WorkflowVersion], int]:
        if not with_deleted:
            await self._load_live_workflow(workflow_id)
        return await self._repo.list_versions_for_workflow(
            workflow_id,
            status_filter=status_filter,
            page=page,
            page_size=page_size,
            with_deleted=with_deleted,
        )

    async def patch_draft(
        self,
        *,
        workflow_id: UUID,
        version_id: UUID,
        config_payload: Any,
    ) -> WorkflowVersion:
        """Replace the `config` of a draft version (AC-9).

        Parent `inactive` or soft deleted → `409 inactive` or `404 workflow.not_found`.
        Non draft target → `409 version_not_draft`.
        """
        workflow = await self._load_live_workflow(workflow_id)
        if workflow.status != WorkflowStatus.ACTIVE.value:
            raise WorkflowInactiveError(f"workflow {workflow_id} is inactive; cannot edit versions")

        version = await self._load_version(
            workflow_id=workflow_id,
            version_id=version_id,
        )
        if version.status != WorkflowVersionStatus.DRAFT.value:
            raise VersionNotDraftError(f"version {version_id} is not a draft")

        config = _coerce_config(config_payload)
        version.config = config.model_dump()
        await self._session.flush()
        await self._session.refresh(version)
        return version

    async def delete_draft(
        self,
        *,
        workflow_id: UUID,
        version_id: UUID,
    ) -> None:
        """Hard delete a draft version (AC-10)."""
        version = await self._load_version(
            workflow_id=workflow_id,
            version_id=version_id,
        )
        if version.status != WorkflowVersionStatus.DRAFT.value:
            raise VersionNotDraftError(f"version {version_id} is not a draft")
        await self._repo.hard_delete_version(version)

    async def publish(
        self,
        *,
        workflow_id: UUID,
        version_id: UUID,
    ) -> WorkflowVersion:
        """Atomically publish a draft (AC-11)."""
        workflow = await self._repo.get_workflow_for_update(workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(f"workflow {workflow_id} not found")
        if workflow.status != WorkflowStatus.ACTIVE.value:
            raise WorkflowInactiveError(f"workflow {workflow_id} is inactive; cannot publish")

        draft = await self._repo.get_version_for_update(version_id)
        if draft is None or draft.workflow_id != workflow_id:
            raise VersionNotFoundError(f"version {version_id} not found")
        if draft.status != WorkflowVersionStatus.DRAFT.value:
            raise VersionConflictError(f"version {version_id} is not a draft at publish time")

        await self._repo.publish_atomic(workflow=workflow, draft=draft)
        await self._session.refresh(draft)
        return draft

    async def archive(
        self,
        *,
        workflow_id: UUID,
        version_id: UUID,
    ) -> WorkflowVersion:
        """Archive a published non current version (AC-12)."""
        workflow = await self._load_live_workflow(workflow_id)
        version = await self._load_version(
            workflow_id=workflow_id,
            version_id=version_id,
        )
        if version.status != WorkflowVersionStatus.PUBLISHED.value:
            raise VersionNotPublishedError(f"version {version_id} is not published")
        if workflow.current_version_id == version.id:
            raise VersionIsCurrentError(f"version {version_id} is the current published version")
        await self._repo.archive_version(version)
        await self._session.refresh(version)
        return version
