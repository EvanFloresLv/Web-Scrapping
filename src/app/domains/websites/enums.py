"""Lifecycle enums for the websites domain (spec 0002).

Mirrored by the DB CHECK constraints on `websites.status` and
`target_urls.status`. Keeps the service, router, and DB in agreement on the
one allowed set of values.
"""

from __future__ import annotations

from enum import StrEnum


class WebsiteStatus(StrEnum):
    """`websites.status` values. Soft delete lives on `deleted_at`."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class TargetStatus(StrEnum):
    """`target_urls.status` values. Soft delete lives on `deleted_at`."""

    ACTIVE = "active"
    INACTIVE = "inactive"
