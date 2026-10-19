"""Lifecycle enums for the workflows domain (spec 0003, AC-12).

Mirrored by the DB CHECK constraints on `scraping_workflows.status` and
`workflow_versions.status`. Service and repository code uses these enums
instead of raw strings so an unknown state is a type error, not a runtime
surprise.
"""

from __future__ import annotations

from enum import StrEnum


class WorkflowStatus(StrEnum):
    """`scraping_workflows.status` values. Soft delete lives on `deleted_at`."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class WorkflowVersionStatus(StrEnum):
    """`workflow_versions.status` values. One way flow: draft -> published -> archived."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"
