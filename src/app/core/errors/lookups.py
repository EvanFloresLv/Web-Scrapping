"""Shared cross domain lookup errors (spec 0007 Key invariants).

Several domains raise 404s for the same missing resource: both the workflows
and websites domains yield `website.not_found`, both the workflows and
executions domains yield `workflow.not_found` and `workflow.version_not_found`.
Each shared code must map to one class so the registry endpoint and the
uniqueness invariant stay honest. These classes live in `app.core` so every
domain can import them without violating the module boundary contract.
"""

from __future__ import annotations

from fastapi import status

from app.core.errors import PlatformError
from app.core.errors.execution_codes import WorkflowErrorCode


class WebsiteNotFoundError(PlatformError):
    """Website id (or parent website) is missing or soft deleted."""

    status_code = status.HTTP_404_NOT_FOUND
    code = WorkflowErrorCode.WEBSITE_NOT_FOUND.value
    title = "Website Not Found"


class WorkflowNotFoundError(PlatformError):
    """Workflow id is missing or soft deleted."""

    status_code = status.HTTP_404_NOT_FOUND
    code = WorkflowErrorCode.WORKFLOW_NOT_FOUND.value
    title = "Workflow Not Found"


class VersionNotFoundError(PlatformError):
    """Workflow version id is missing, or does not belong to the workflow."""

    status_code = status.HTTP_404_NOT_FOUND
    code = WorkflowErrorCode.VERSION_NOT_FOUND.value
    title = "Workflow Version Not Found"


__all__ = [
    "VersionNotFoundError",
    "WebsiteNotFoundError",
    "WorkflowNotFoundError",
]
