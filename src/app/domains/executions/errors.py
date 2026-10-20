"""Domain errors for the executions domain (spec 0006).

Each exception maps 1:1 to a Problem Details response via the shared
`PlatformError` handler. The `code` strings come from `ExecutionErrorCode`
(or `WorkflowErrorCode` for the reused lookup 404s), so the registry stays
the single source of truth.
"""

from __future__ import annotations

from typing import Any

from fastapi import status

from app.core.errors import PlatformError
from app.core.errors.execution_codes import ExecutionErrorCode, WorkflowErrorCode


class WorkflowNotFoundError(PlatformError):
    """Workflow id is missing or soft deleted (AC-4). Reuses the workflows code."""

    status_code = status.HTTP_404_NOT_FOUND
    code = WorkflowErrorCode.WORKFLOW_NOT_FOUND.value
    title = "Workflow Not Found"


class VersionNotFoundError(PlatformError):
    """Version id is missing, or does not belong to the workflow (AC-2)."""

    status_code = status.HTTP_404_NOT_FOUND
    code = WorkflowErrorCode.VERSION_NOT_FOUND.value
    title = "Version Not Found"


class WorkflowNotRunnableError(PlatformError):
    """Workflow has no current (published) version to run (AC-2)."""

    status_code = status.HTTP_409_CONFLICT
    code = ExecutionErrorCode.WORKFLOW_NOT_RUNNABLE.value
    title = "Workflow Not Runnable"


class VersionNotPublishedError(PlatformError):
    """Explicit `version_id` points at a draft (AC-2)."""

    status_code = status.HTTP_409_CONFLICT
    code = ExecutionErrorCode.VERSION_NOT_PUBLISHED.value
    title = "Version Not Published"


class VersionArchivedError(PlatformError):
    """Explicit `version_id` points at an archived version (AC-2)."""

    status_code = status.HTTP_409_CONFLICT
    code = ExecutionErrorCode.VERSION_ARCHIVED.value
    title = "Version Archived"


class TargetNotRegisteredError(PlatformError):
    """Target id is unknown, soft deleted, or under a different website (AC-3)."""

    status_code = status.HTTP_404_NOT_FOUND
    code = ExecutionErrorCode.TARGET_NOT_REGISTERED.value
    title = "Target Not Registered"


class InvalidExecuteBodyError(PlatformError):
    """Execute request body failed Pydantic validation (AC-1).

    Carries the field path(s) in `details` so operators can tell which key
    was wrong.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = ExecutionErrorCode.INVALID_EXECUTE_BODY.value
    title = "Invalid Execute Body"

    def __init__(
        self,
        detail: str,
        *,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(detail)
        self.details = details or []


class TerminalPersistFailedError(PlatformError):
    """The terminal UPDATE after the run failed to persist (AC-8)."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = ExecutionErrorCode.TERMINAL_PERSIST_FAILED.value
    title = "Terminal Persist Failed"


class ExecutionNotFoundError(PlatformError):
    """`GET /executions/{id}` miss (AC-9)."""

    status_code = status.HTTP_404_NOT_FOUND
    code = ExecutionErrorCode.NOT_FOUND.value
    title = "Execution Not Found"


__all__ = [
    "ExecutionNotFoundError",
    "InvalidExecuteBodyError",
    "TargetNotRegisteredError",
    "TerminalPersistFailedError",
    "VersionArchivedError",
    "VersionNotFoundError",
    "VersionNotPublishedError",
    "WorkflowNotFoundError",
    "WorkflowNotRunnableError",
]
