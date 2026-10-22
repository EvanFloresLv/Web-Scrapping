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

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.executions.cursor import Cursor
from app.domains.executions.enums import ExecutionStatus
from app.domains.executions.models import Execution, ExecutionResult


@dataclass(frozen=True)
class ExecutionListFilters:
    """Filter bundle for the execution browser list (spec 0010 AC-3).

    Every field is optional and independently combinable; `None` means
    "do not filter on this axis". `with_deleted` default is `False`
    (hide executions whose parent workflow is soft deleted, spec 0010 AC-4).
    """

    workflow_id: UUID | None = None
    status: ExecutionStatus | None = None
    target_url_id: UUID | None = None
    website_id: UUID | None = None
    correlation_id: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    with_deleted: bool = False


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

    async def list_page(
        self,
        filters: ExecutionListFilters,
        *,
        cursor: Cursor | None,
        page_size: int,
    ) -> list[Execution]:
        """Return at most `page_size` executions matching every set filter,
        newest first on `(created_at DESC, id DESC)`.

        When `cursor` is set, the keyset predicate `(created_at, id) < (c, i)`
        restricts the result to rows strictly older than the cursor row,
        tie broken by `id` so the sort has a total order.
        """
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


def _apply_workflow_or_website_filter(  # type: ignore[no-untyped-def]
    stmt,
    *,
    workflow_id: UUID | None,
    website_id: UUID | None,
):
    """Scope the executions query by `workflow_id` and/or `website_id`.

    Spec 0010 AC-5: the join path is
    `executions.workflow_version_id -> workflow_versions.workflow_id ->
    scraping_workflows.id -> scraping_workflows.website_id`. We express it
    as a correlated EXISTS so this domain doesn't import workflow ORM
    classes (keeps the `import-linter` boundary intact).
    """
    from sqlalchemy import text as _text

    conditions = ["wv.id = executions.workflow_version_id"]
    params: dict[str, object] = {}
    if workflow_id is not None:
        conditions.append("wv.workflow_id = :__wf_id")
        params["__wf_id"] = workflow_id
    if website_id is not None:
        conditions.append("sw.website_id = :__site_id")
        params["__site_id"] = website_id
    where = " AND ".join(conditions)
    exists_sql = _text(
        "EXISTS (SELECT 1 FROM workflow_versions wv "
        "JOIN scraping_workflows sw ON sw.id = wv.workflow_id "
        f"WHERE {where})"
    ).bindparams(**params)
    return stmt.where(exists_sql)


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

    async def list_page(
        self,
        filters: ExecutionListFilters,
        *,
        cursor: Cursor | None,
        page_size: int,
    ) -> list[Execution]:
        """Spec 0010 AC-1, AC-2, AC-3, AC-4, AC-5, AC-6."""
        stmt = select(Execution).order_by(
            Execution.created_at.desc(),
            Execution.id.desc(),
        )
        if filters.status is not None:
            stmt = stmt.where(Execution.status == filters.status.value)
        if filters.target_url_id is not None:
            stmt = stmt.where(Execution.target_url_id == filters.target_url_id)
        if filters.correlation_id is not None:
            stmt = stmt.where(Execution.correlation_id == filters.correlation_id)
        if filters.created_from is not None:
            stmt = stmt.where(Execution.created_at >= filters.created_from)
        if filters.created_to is not None:
            stmt = stmt.where(Execution.created_at < filters.created_to)
        if filters.workflow_id is not None or filters.website_id is not None:
            stmt = _apply_workflow_or_website_filter(
                stmt,
                workflow_id=filters.workflow_id,
                website_id=filters.website_id,
            )
        if cursor is not None:
            stmt = stmt.where(
                tuple_(Execution.created_at, Execution.id) < (cursor.created_at, cursor.id),
            )
        stmt = _live_workflow_join(stmt, filters.with_deleted)
        stmt = stmt.limit(page_size)
        return list((await self._session.execute(stmt)).scalars().all())

    async def add(self, execution: Execution) -> None:
        """Insert a new execution. The service commits (AC-5 step 1)."""
        self._session.add(execution)
        await self._session.flush()

    async def finalise(self, execution: Execution) -> None:
        """Flush the terminal UPDATE (AC-5 step 3).

        The service mutates `status`, `finished_at`, `duration_ms`,
        `items_extracted`, and (on failure) the error columns on the in
        memory row and then calls finalise to flush the UPDATE in one
        statement. The service commits.
        """
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
    "ExecutionListFilters",
    "ExecutionRepository",
    "ExecutionResultRepository",
    "SqlAlchemyExecutionRepository",
    "SqlAlchemyExecutionResultRepository",
]
