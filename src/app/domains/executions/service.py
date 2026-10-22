"""Executor service for the sync workflow execution endpoint (spec 0006).

Owns the two commit lifecycle:

1. Insert `executions` row in `running` and commit (durable from the moment
   work begins).
2. Call `ExtractionService.run(...)` outside any DB transaction.
3. UPDATE the terminal status (`completed` or `failed`) and on success INSERT
   the N `execution_results` rows; both land in one commit so a `completed`
   execution and its results are visible atomically.

Pre run validation (unknown workflow / version / target, draft or archived
version, workflow without a current version, target under a different
website) raises typed exceptions that the router maps to Problem Details
(AC-6, AC-8). No `executions` row is persisted for a pre run failure.

Cross domain reads go through the ports in `app.core.workflows` and
`app.core.targets` (AC-14a) so the executions package never imports the
workflows or websites ORM; the ports are injected via FastAPI dependencies
and backed by adapters that live in the owning domain packages.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.extraction import ExtractionPort
from app.core.logging import get_logger
from app.core.observability.metrics import increment_executions, observe_execution_duration
from app.core.targets import TargetReadPort, TargetSummary
from app.core.workflows import VersionSummary, WorkflowReadPort, WorkflowSummary
from app.domains.executions.enums import ExecutionStatus
from app.domains.executions.errors import (
    ExecutionNotFoundError,
    TargetNotRegisteredError,
    TerminalPersistFailedError,
    VersionArchivedError,
    VersionNotFoundError,
    VersionNotPublishedError,
    WorkflowNotFoundError,
    WorkflowNotRunnableError,
)
from app.domains.executions.models import Execution, ExecutionResult
from app.domains.executions.repository import (
    SqlAlchemyExecutionRepository,
    SqlAlchemyExecutionResultRepository,
)

_log = get_logger("app.executions")

_VERSION_STATUS_PUBLISHED = "published"
_VERSION_STATUS_DRAFT = "draft"
_VERSION_STATUS_ARCHIVED = "archived"


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class ExecutionService:
    """Sync executor for the MVP workflow execution endpoint."""

    def __init__(
        self,
        session: AsyncSession,
        execution_repo: SqlAlchemyExecutionRepository,
        result_repo: SqlAlchemyExecutionResultRepository,
        workflow_port: WorkflowReadPort,
        target_port: TargetReadPort,
        extraction: ExtractionPort,
    ) -> None:
        self._session = session
        self._executions = execution_repo
        self._results = result_repo
        self._workflows = workflow_port
        self._targets = target_port
        self._extraction = extraction

    async def execute(
        self,
        *,
        workflow_id: UUID,
        target_url_id: UUID,
        version_id: UUID | None,
        correlation_id: str | None = None,
    ) -> Execution:
        """Run the resolved workflow version against the resolved target (AC-1 - AC-6).

        Spec 0011 AC-4: wraps the body in `structlog.contextvars` so every
        event emitted here (and any nested `extraction.*` events) carries
        `correlation_id` + `execution_id` without per call kwargs. HTTP
        callers always supply a `correlation_id` (the middleware mints one
        if the client omits `X-Request-ID`). A programmatic caller that
        passes none (future worker surface) gets a fresh UUID4.
        """
        bound_correlation_id = correlation_id or str(uuid4())
        with structlog.contextvars.bound_contextvars(
            correlation_id=bound_correlation_id,
        ):
            return await self._execute_bound(
                workflow_id=workflow_id,
                target_url_id=target_url_id,
                version_id=version_id,
                correlation_id=bound_correlation_id,
            )

    async def _execute_bound(
        self,
        *,
        workflow_id: UUID,
        target_url_id: UUID,
        version_id: UUID | None,
        correlation_id: str,
    ) -> Execution:
        # Spec 0012 AC-2: metrics facade reads `workflow_id` from structlog
        # contextvars so instrument labels do not need a per call parameter.
        structlog.contextvars.bind_contextvars(workflow_id=str(workflow_id))
        workflow = await self._workflows.get_live_workflow(workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(f"workflow {workflow_id} not found")

        version = await self._resolve_version(workflow, version_id)
        target = await self._resolve_target(workflow, target_url_id)

        started_at = _utcnow()
        execution = Execution(
            workflow_version_id=version.id,
            target_url_id=target.id,
            status=ExecutionStatus.RUNNING.value,
            started_at=started_at,
            items_extracted=0,
            correlation_id=correlation_id,
        )
        await self._executions.add(execution)
        await self._session.commit()

        with structlog.contextvars.bound_contextvars(execution_id=str(execution.id)):
            _log.info(
                "execution.started",
                workflow_id=str(workflow.id),
                workflow_version_id=str(version.id),
                target_url_id=str(target.id),
            )

            result = await self._extraction.run(version, target.url)

            finished_at = _utcnow()
            execution.status = result.status
            execution.finished_at = finished_at
            execution.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            execution.items_extracted = result.items_count
            execution.error_code = result.error_code
            execution.error_message = result.error_message

            execution_id = execution.id
            try:
                await self._executions.finalise(execution)
                if result.status == "completed" and result.items:
                    rows = [
                        ExecutionResult(
                            execution_id=execution_id,
                            item_index=index,
                            payload=item,
                        )
                        for index, item in enumerate(result.items)
                    ]
                    await self._results.add_many(rows)
                await self._session.commit()
            except Exception as exc:
                await self._session.rollback()
                _log.error(
                    "execution.terminal_persist_failed",
                    workflow_id=str(workflow.id),
                    workflow_version_id=str(version.id),
                    error_type=type(exc).__name__,
                    error_msg=str(exc),
                )
                raise TerminalPersistFailedError(
                    f"failed to persist terminal state for execution {execution_id}"
                ) from exc

            duration_s = (execution.duration_ms or 0) / 1000
            observe_execution_duration(result.status, duration_s)
            increment_executions(result.status)

            log_payload: dict[str, Any] = {
                "workflow_id": str(workflow.id),
                "workflow_version_id": str(version.id),
                "target_url_id": str(target.id),
                "duration_ms": execution.duration_ms,
                "items_extracted": execution.items_extracted,
            }
            if result.status == "completed":
                _log.info("execution.completed", **log_payload)
            else:
                log_payload["error_code"] = result.error_code
                log_payload["error_type"] = (
                    result.error_details[0].get("type") if result.error_details else None
                )
                log_payload["error_msg"] = result.error_message
                _log.info("execution.failed", **log_payload)

            return execution

    async def get(
        self,
        execution_id: UUID,
    ) -> tuple[Execution, UUID]:
        """Return the execution with its results and the owning workflow id (AC-9).

        Raises `ExecutionNotFoundError` when the row is missing or hidden by
        the default soft deleted workflow filter.
        """
        execution = await self._executions.get(execution_id)
        if execution is None:
            raise ExecutionNotFoundError(f"execution {execution_id} not found")
        workflow_id = await self._workflows.get_workflow_id_for_version(
            execution.workflow_version_id
        )
        if workflow_id is None:
            # Parent workflow is gone (should be caught by the repo filter)
            # or the version was never valid. Treat as not found.
            raise ExecutionNotFoundError(f"execution {execution_id} not found")
        return execution, workflow_id

    async def list_page(
        self,
        filters: Any,  # ExecutionListFilters, kept Any to avoid circular import
        *,
        cursor: Any,  # Cursor | None
        page_size: int,
    ) -> tuple[list[Execution], dict[UUID, UUID]]:
        """Return a page of executions + the `{version_id: workflow_id}` map
        to denormalise `workflow_id` onto each row (spec 0010 AC-1).

        The service layer stays the single caller point: the router asks for
        the page here, the service hands back rows plus the resolution map
        in one shot. No per row lookup from the router.
        """
        rows = await self._executions.list_page(filters, cursor=cursor, page_size=page_size)
        version_ids = sorted({r.workflow_version_id for r in rows})
        workflow_ids = await self._workflows.get_workflow_ids_for_versions(
            version_ids,
            with_deleted=filters.with_deleted,
        )
        return rows, workflow_ids

    # ---- helpers --------------------------------------------------------

    async def _resolve_version(
        self,
        workflow: WorkflowSummary,
        version_id: UUID | None,
    ) -> VersionSummary:
        """Apply AC-2: version id resolution + runnability check."""
        if version_id is None:
            if workflow.current_version_id is None:
                raise WorkflowNotRunnableError(
                    f"workflow {workflow.id} has no current published version"
                )
            effective_version_id = workflow.current_version_id
        else:
            effective_version_id = version_id

        version = await self._workflows.get_version_for_workflow(
            workflow_id=workflow.id,
            version_id=effective_version_id,
        )
        if version is None:
            raise VersionNotFoundError(
                f"version {effective_version_id} not found under workflow {workflow.id}"
            )

        if version.status == _VERSION_STATUS_PUBLISHED:
            return version
        if version.status == _VERSION_STATUS_DRAFT:
            raise VersionNotPublishedError(
                f"version {version.id} is a draft; publish it before executing"
            )
        if version.status == _VERSION_STATUS_ARCHIVED:
            raise VersionArchivedError(f"version {version.id} is archived and not runnable")
        # Defensive: unexpected status value stored in DB.
        raise VersionNotPublishedError(
            f"version {version.id} has non runnable status {version.status!r}"
        )

    async def _resolve_target(
        self,
        workflow: WorkflowSummary,
        target_url_id: UUID,
    ) -> TargetSummary:
        """Apply AC-3: target lookup + website scoping."""
        target = await self._targets.get_live_target(target_url_id)
        if target is None:
            raise TargetNotRegisteredError(
                f"target {target_url_id} is not registered under this workflow"
            )
        if target.website_id != workflow.website_id:
            raise TargetNotRegisteredError(
                f"target {target_url_id} is not registered under this workflow"
            )
        return target


__all__ = ["ExecutionService"]
