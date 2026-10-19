"""Central registry for `executions.error_code` values (spec 0003, AC-17).

Error codes stored on `executions.error_code` are domain prefixed dotted strings.
The column stays plain `text` (no DB CHECK), so adding a code is a code change,
not a migration. This file is the single source of truth every writer imports
from.

Prefixes and their owning slice features:

- `fetch.*`     : HTTP fetch failures (feature 6, deterministic HTML extraction).
- `extraction.*`: deterministic extractor failures (feature 6).
- `execution.*` : executor service failures (feature 7, execution endpoint).
- `agent.*`     : LLM assisted path failures (feature 15 and beyond).

Each slice feature extends its own prefix by adding members to the enum below;
no slice invents a new prefix without updating this docstring. The `StrEnum`
shape lets both the writer (service layer) and the reader (admin UI) share one
contract, and keeps every code sortable, grep friendly, and stable across runs.

This spec (0003) deliberately ships the empty shells. The slice features that
produce the errors populate them.
"""

from __future__ import annotations

from enum import StrEnum


class FetchErrorCode(StrEnum):
    """HTTP fetch failures. Populated by feature 6."""


class ExtractionErrorCode(StrEnum):
    """Deterministic extractor failures. Populated by feature 6."""


class ExecutionErrorCode(StrEnum):
    """Executor service failures. Populated by feature 7."""


class AgentErrorCode(StrEnum):
    """LLM assisted path failures. Populated by feature 15 and beyond."""


class WorkflowErrorCode(StrEnum):
    """Workflow configuration and versioning failures (spec 0004, AC-15).

    The MVP set covers lookups (404), lifecycle refusals (409), and
    validation failures (422). Codes stay stable across runs so the admin
    UI and clients can switch on them.
    """

    # 404 lookups
    WEBSITE_NOT_FOUND = "website_not_found"
    WORKFLOW_NOT_FOUND = "workflow_not_found"
    VERSION_NOT_FOUND = "version_not_found"

    # 409 conflicts
    NAME_CONFLICT = "workflow.name_conflict"
    VERSION_CONFLICT = "workflow.version_conflict"
    VERSION_NOT_DRAFT = "workflow.version_not_draft"
    VERSION_NOT_PUBLISHED = "workflow.version_not_published"
    VERSION_IS_CURRENT = "workflow.version_is_current"
    HAS_IN_FLIGHT_EXECUTIONS = "workflow.has_in_flight_executions"
    INACTIVE = "workflow.inactive"

    # 422 validation
    VALIDATION_ERROR = "workflow.validation_error"
    IMMUTABLE_FIELD = "workflow.immutable_field"
    INVALID_PAGINATION = "workflow.invalid_pagination"


# Convenience union used by writer-side type hints once concrete codes land.
ExecutionErrorCodeValue = FetchErrorCode | ExtractionErrorCode | ExecutionErrorCode | AgentErrorCode

__all__ = [
    "AgentErrorCode",
    "ExecutionErrorCode",
    "ExecutionErrorCodeValue",
    "ExtractionErrorCode",
    "FetchErrorCode",
    "WorkflowErrorCode",
]
