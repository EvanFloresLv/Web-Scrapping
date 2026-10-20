"""Repository Protocols and concrete implementations for the executions domain.

Protocols (spec 0003): define the CRUD and lifecycle surface each slice
feature uses. Concrete classes (spec 0006 AC-14): `SqlAlchemyExecutionRepository`
and `SqlAlchemyExecutionResultRepository` back the sync executor.

Both tables are append only. `Execution` rows get one lifecycle update when
they reach a terminal status (`finished_at`, `duration_ms`, `items_extracted`,
and on failure `error_code` + `error_message` set in the same UPDATE), then
are immutable (spec 0003 AC-13). `ExecutionResult` rows are never updated.

Default read filter (spec 0003 AC-20): every `list` and `get` hides rows
whose root workflow is soft deleted (joined through
`workflow_versions -> scraping_workflows`), unless `with_deleted=True`.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.executions.enums import ExecutionStatus
from app.domains.executions.models import Execution, ExecutionResult


class ExecutionRepository(Protocol):
    """Persistence surface for `Execution` rows (spec 0003 AC-6)."""

    async def get(
        self,
        execution_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> Execution | None:
        """Fetch one execution. Hidden when the workflow is soft deleted unless opted in."""
        ...

    async def list_for_workflow_version(
        self,
        workflow_version_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> list[Execution]:
        """List executions for one version, newest first."""
        ...

    async def list_for_target_url(
        self,
        target_url_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> list[Execution]:
        """List executions for one target URL, newest first."""
        ...

    async def list_by_status(
        self,
        status: ExecutionStatus,
        *,
        with_deleted: bool = False,
    ) -> list[Execution]:
        """List executions in a given status, newest first."""
        ...

    async def add(self, execution: Execution) -> None:
        """Insert a new execution row in `pending` or `running`."""
        ...

    async def finalise(self, execution: Execution) -> None:
        """One shot UPDATE that moves `pending`/`running` to a terminal status."""
        ...


class ExecutionResultRepository(Protocol):
    """Persistence surface for `ExecutionResult` rows (spec 0003 AC-7)."""

    async def list_for_execution(
        self,
        execution_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> list[ExecutionResult]:
        """Return every result for an execution ordered by `item_index`."""
        ...

    async def add_many(self, results: list[ExecutionResult]) -> None:
        """Insert the extracted items for a successful run in one round trip."""
        ...


# ---------------------------------------------------------------------------
# Concrete implementations (spec 0006 AC-14)
# ---------------------------------------------------------------------------


def _live_workflow_join(stmt, with_deleted: bool):  # type: ignore[no-untyped-def]
    """Join `executions -> workflow_versions -> scraping_workflows` with the
    default `scraping_workflows.deleted_at IS NULL` filter.

    Workflows and executions sit in independent domains per `import-linter`,
    so we cannot import `ScrapingWorkflow` here. The join is expressed through
    raw table names using SQLAlchemy's text-aware `join` clause via a
    subquery on `workflow_versions`. Both tables are already registered on
    the shared `Base.metadata` by the time the session runs.
    """
    from sqlalchemy import and_, text

    if with_deleted:
        return stmt
    # Correlated EXISTS against the two parent tables keeps us from importing
    # the workflows ORM classes while still filtering soft deleted workflows.
    live_parent = text(
        "EXISTS (SELECT 1 FROM workflow_versions wv "
        "JOIN scraping_workflows sw ON sw.id = wv.workflow_id "
        "WHERE wv.id = executions.workflow_version_id "
        "AND sw.deleted_at IS NULL)"
    )
    return stmt.where(and_(live_parent))


class SqlAlchemyExecutionRepository:
    """Concrete `ExecutionRepository` using the request-scoped `AsyncSession`
    (spec 0006 AC-14).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        execution_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> Execution | None:
        """Load an execution with its results eager loaded (AC-14)."""
        stmt = (
            select(Execution)
            .where(Execution.id == execution_id)
            .options(selectinload(Execution.results))
        )
        stmt = _live_workflow_join(stmt, with_deleted)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_workflow_version(
        self,
        workflow_version_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> list[Execution]:
        stmt = (
            select(Execution)
            .where(Execution.workflow_version_id == workflow_version_id)
            .order_by(Execution.created_at.desc())
        )
        stmt = _live_workflow_join(stmt, with_deleted)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_target_url(
        self,
        target_url_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> list[Execution]:
        stmt = (
            select(Execution)
            .where(Execution.target_url_id == target_url_id)
            .order_by(Execution.created_at.desc())
        )
        stmt = _live_workflow_join(stmt, with_deleted)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_by_status(
        self,
        status: ExecutionStatus,
        *,
        with_deleted: bool = False,
    ) -> list[Execution]:
        stmt = (
            select(Execution)
            .where(Execution.status == status.value)
            .order_by(Execution.created_at.desc())
        )
        stmt = _live_workflow_join(stmt, with_deleted)
        return list((await self._session.execute(stmt)).scalars().all())

    async def add(self, execution: Execution) -> None:
        """Insert a new execution. The service commits (AC-5 step 1)."""
        self._session.add(execution)
        await self._session.flush()

    async def finalise(self, execution: Execution) -> None:
        """Flush the terminal UPDATE (AC-5 step 3).

        Refuses to run on a row already in a terminal state (defensive
        assertion against double finalise). The service commits.
        """
        if execution.status not in {
            ExecutionStatus.PENDING.value,
            ExecutionStatus.RUNNING.value,
        }:
            raise RuntimeError(
                f"finalise called on execution {execution.id} already in terminal status "
                f"{execution.status!r}"
            )
        await self._session.flush()


class SqlAlchemyExecutionResultRepository:
    """Concrete `ExecutionResultRepository` (spec 0006 AC-14)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_execution(
        self,
        execution_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> list[ExecutionResult]:
        stmt = (
            select(ExecutionResult)
            .where(ExecutionResult.execution_id == execution_id)
            .order_by(ExecutionResult.item_index.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_many(self, results: list[ExecutionResult]) -> None:
        """Insert many results. The service commits (AC-5 step 3)."""
        if not results:
            return
        self._session.add_all(results)
        await self._session.flush()


__all__ = [
    "ExecutionRepository",
    "ExecutionResultRepository",
    "SqlAlchemyExecutionRepository",
    "SqlAlchemyExecutionResultRepository",
]
