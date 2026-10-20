"""Domain errors for the workflows domain (spec 0004).

Each exception maps 1:1 to a Problem Details response via the shared
`PlatformError` handler in `app.core.errors`. The `code` strings come from
`WorkflowErrorCode` so the registry is the single source of truth.
"""

from __future__ import annotations

from fastapi import status

from app.core.errors import ErrorDetail, PlatformError
from app.core.errors.execution_codes import WorkflowErrorCode
from app.core.errors.lookups import (
    VersionNotFoundError,
    WebsiteNotFoundError,
    WorkflowNotFoundError,
)


class WorkflowNameConflictError(PlatformError):
    """A live workflow with the same `(website_id, name)` already exists (AC-2, AC-4)."""

    status_code = status.HTTP_409_CONFLICT
    code = WorkflowErrorCode.NAME_CONFLICT.value
    title = "Workflow Name Conflict"


class VersionConflictError(PlatformError):
    """Lost race on `(workflow_id, version_number)` or on publish (AC-6, AC-11)."""

    status_code = status.HTTP_409_CONFLICT
    code = WorkflowErrorCode.VERSION_CONFLICT.value
    title = "Workflow Version Conflict"


class VersionNotDraftError(PlatformError):
    """Edit, delete, or publish attempted on a non-draft version (AC-9, AC-10, AC-11)."""

    status_code = status.HTTP_409_CONFLICT
    code = WorkflowErrorCode.VERSION_NOT_DRAFT.value
    title = "Workflow Version Not Draft"


class VersionNotPublishedError(PlatformError):
    """Archive attempted on a non-published version (AC-12)."""

    status_code = status.HTTP_409_CONFLICT
    code = WorkflowErrorCode.VERSION_NOT_PUBLISHED.value
    title = "Workflow Version Not Published"


class VersionIsCurrentError(PlatformError):
    """Archive attempted on the current published version (AC-12)."""

    status_code = status.HTTP_409_CONFLICT
    code = WorkflowErrorCode.VERSION_IS_CURRENT.value
    title = "Workflow Version Is Current"


class HasInFlightExecutionsError(PlatformError):
    """Soft delete refused: at least one pending or running execution exists (AC-5)."""

    status_code = status.HTTP_409_CONFLICT
    code = WorkflowErrorCode.HAS_IN_FLIGHT_EXECUTIONS.value
    title = "Workflow Has In Flight Executions"


class WorkflowInactiveError(PlatformError):
    """Create or edit refused: parent workflow is inactive (AC-6, AC-9, AC-11)."""

    status_code = status.HTTP_409_CONFLICT
    code = WorkflowErrorCode.INACTIVE.value
    title = "Workflow Inactive"


class WorkflowValidationError(PlatformError):
    """`WorkflowConfig` shape or coherence check failed (AC-7).

    Carries the structured per field entries in `self.errors`; the shared
    `_platform_error_handler` copies them onto the Problem body under the
    `errors` key (spec 0007 AC-3).
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = WorkflowErrorCode.VALIDATION_ERROR.value
    title = "Workflow Validation Error"

    def __init__(
        self,
        detail: str,
        *,
        errors: list[ErrorDetail] | None = None,
    ) -> None:
        super().__init__(detail, errors=errors)


class ImmutableFieldError(PlatformError):
    """PATCH body carried a field that is not in the allow list (AC-4, AC-9)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = WorkflowErrorCode.IMMUTABLE_FIELD.value
    title = "Immutable Field"

    def __init__(self, field: str) -> None:
        super().__init__(f"field {field!r} is not patchable on this resource")
        self.field = field


class InvalidPaginationError(PlatformError):
    """Pagination parameters out of allowed range (AC-3, AC-8)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = WorkflowErrorCode.INVALID_PAGINATION.value
    title = "Invalid Pagination"


__all__ = [
    "HasInFlightExecutionsError",
    "ImmutableFieldError",
    "InvalidPaginationError",
    "VersionConflictError",
    "VersionIsCurrentError",
    "VersionNotDraftError",
    "VersionNotFoundError",
    "VersionNotPublishedError",
    "WebsiteNotFoundError",
    "WorkflowInactiveError",
    "WorkflowNameConflictError",
    "WorkflowNotFoundError",
    "WorkflowValidationError",
]
