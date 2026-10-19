"""Repository protocols for the executions domain (spec 0003).

Shapes the CRUD and lifecycle surface each slice feature will implement. The
concrete implementation lands with feature 7 (workflow execution endpoint)
using `AsyncSession` and the patterns pinned in spec 0001.

Both tables are append only. `Execution` rows get one lifecycle update when
they reach a terminal status (`finished_at`, `duration_ms`, `items_extracted`,
and on failure `error_code` + `error_message` set in the same `UPDATE`), then
are immutable (AC-13). `ExecutionResult` rows are never updated.

Default read filter (AC-20): every `list` and `get` hides rows whose root
workflow is soft deleted (joined through `workflow_versions ->
scraping_workflows`), unless `with_deleted=True`. Feature 18 (products &
provenance) and the retention job are the only callers that pass it.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domains.executions.enums import ExecutionStatus
from app.domains.executions.models import Execution, ExecutionResult


class ExecutionRepository(Protocol):
    """Persistence surface for `Execution` rows (AC-6)."""

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
        """List executions for one version, newest first (uses the composite index, AC-14)."""
        ...

    async def list_for_target_url(
        self,
        target_url_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> list[Execution]:
        """List executions for one target URL, newest first (AC-14)."""
        ...

    async def list_by_status(
        self,
        status: ExecutionStatus,
        *,
        with_deleted: bool = False,
    ) -> list[Execution]:
        """List executions in a given status, newest first (AC-14)."""
        ...

    async def add(self, execution: Execution) -> None:
        """Insert a new execution row in `pending` or `running` (AC-6)."""
        ...

    async def finalise(self, execution: Execution) -> None:
        """One shot UPDATE that moves `pending`/`running` to a terminal status (AC-13)."""
        ...


class ExecutionResultRepository(Protocol):
    """Persistence surface for `ExecutionResult` rows (AC-7)."""

    async def list_for_execution(
        self,
        execution_id: UUID,
        *,
        with_deleted: bool = False,
    ) -> list[ExecutionResult]:
        """Return every result for an execution ordered by `item_index` (AC-14 unique index covers it)."""
        ...

    async def add_many(self, results: list[ExecutionResult]) -> None:
        """Insert the extracted items for a successful run in one round trip."""
        ...
