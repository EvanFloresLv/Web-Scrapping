"""Domain errors for the websites domain (spec 0002).

Each exception maps 1:1 to a Problem Details response via the handlers
registered in `app.api.v1.websites`. The stable `code` strings here are the
dotted codes mandated by spec 0007 AC-5:

- `website.duplicate`, `website.target_duplicate` -> 409
- `website.host_mismatch`, `website.inactive`, `website.immutable_field`,
  `website.invalid_pagination` -> 422
- `website.validation_error` is emitted by `CanonicalizationError`; the
  generic Pydantic `RequestValidationError` is handled by
  `_validation_error_handler`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.errors import ErrorDetail, PlatformError
from app.core.errors.lookups import WebsiteNotFoundError


class TargetNotFoundError(PlatformError):
    """A target_url row is missing or soft deleted."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "website.target_not_found"
    title = "Target Not Found"


class DuplicateWebsiteError(PlatformError):
    """Submission collides with an existing live website (same canonical host)."""

    status_code = status.HTTP_409_CONFLICT
    code = "website.duplicate"
    title = "Duplicate Website"

    def __init__(self, *, existing_id: UUID, canonical_host: str) -> None:
        message = f"website with host {canonical_host!r} already exists"
        super().__init__(
            message,
            errors=[
                ErrorDetail(
                    code=self.code,
                    loc=["host"],
                    message=message,
                    meta={
                        "existing_id": str(existing_id),
                        "canonical_host": canonical_host,
                    },
                )
            ],
        )
        self.existing_id = existing_id
        self.canonical_host = canonical_host


class DuplicateTargetError(PlatformError):
    """Submission collides with an existing live target under the same website."""

    status_code = status.HTTP_409_CONFLICT
    code = "website.target_duplicate"
    title = "Duplicate Target"

    def __init__(self, *, existing_id: UUID, canonical_url: str) -> None:
        message = f"target with url {canonical_url!r} already exists for this website"
        super().__init__(
            message,
            errors=[
                ErrorDetail(
                    code=self.code,
                    loc=["url"],
                    message=message,
                    meta={
                        "existing_id": str(existing_id),
                        "canonical_url": canonical_url,
                    },
                )
            ],
        )
        self.existing_id = existing_id
        self.canonical_url = canonical_url


class HostMismatchError(PlatformError):
    """Target URL host does not match the parent website's host (AC-5)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "website.host_mismatch"
    title = "Host Mismatch"

    def __init__(self, *, expected_host: str, actual_host: str) -> None:
        super().__init__(
            f"target host {actual_host!r} does not match parent website host {expected_host!r}"
        )
        self.expected_host = expected_host
        self.actual_host = actual_host


class WebsiteInactiveError(PlatformError):
    """Parent website is inactive; new targets are refused (AC-6)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "website.inactive"
    title = "Website Inactive"


class ImmutableFieldError(PlatformError):
    """A PATCH tried to change an immutable field (`host`, `url`) (AC-10)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "website.immutable_field"
    title = "Immutable Field"

    def __init__(self, field: str) -> None:
        super().__init__(f"field {field!r} is immutable after creation")
        self.field = field


class InvalidPaginationError(PlatformError):
    """Pagination parameters out of range (AC-7)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "website.invalid_pagination"
    title = "Invalid Pagination"


class CanonicalizationError(PlatformError):
    """URL or host could not be canonicalized (AC-3, AC-7)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "website.validation_error"
    title = "Unprocessable Entity"


__all__ = [
    "CanonicalizationError",
    "DuplicateTargetError",
    "DuplicateWebsiteError",
    "HostMismatchError",
    "ImmutableFieldError",
    "InvalidPaginationError",
    "TargetNotFoundError",
    "WebsiteInactiveError",
    "WebsiteNotFoundError",
]
