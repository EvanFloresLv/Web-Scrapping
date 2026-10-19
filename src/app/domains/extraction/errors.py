"""Domain exceptions for the extraction domain (spec 0005).

`FetchError` and `ExtractionError` are the internal signals the service
raises; `ExtractionService.run(...)` catches them and shapes a terminal
`ExtractionResult`. The preview router catches a smaller set
(`TargetNotRegisteredError`, `PreviewInvalidBodyError`) and maps them to
Problem Details via the shared `PlatformError` handler.
"""

from __future__ import annotations

from typing import Any

from fastapi import status

from app.core.errors import PlatformError
from app.core.errors.execution_codes import ExtractionErrorCode, FetchErrorCode


class FetchError(Exception):
    """Fetch pipeline failure (AC-4, AC-5).

    Captures the `FetchErrorCode` plus any human message and structured
    details (status code, redirect count, received content type, etc.).
    """

    def __init__(
        self,
        code: FetchErrorCode,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []


class ExtractionError(Exception):
    """Extractor pipeline failure (AC-6 through AC-11)."""

    def __init__(
        self,
        code: ExtractionErrorCode,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []


class TargetNotRegisteredError(PlatformError):
    """Preview URL does not match a live `target_urls` row (AC-3)."""

    status_code = status.HTTP_404_NOT_FOUND
    code = ExtractionErrorCode.TARGET_NOT_REGISTERED.value
    title = "Target Not Registered"


class PreviewInvalidBodyError(PlatformError):
    """Preview request body failed Pydantic validation (AC-2).

    Raised when the router catches a `RequestValidationError` scoped to the
    preview endpoint; carries the field path(s) in `details` so operators
    can tell which key was wrong.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = ExtractionErrorCode.INVALID_PREVIEW_BODY.value
    title = "Invalid Preview Body"

    def __init__(
        self,
        detail: str,
        *,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(detail)
        self.details = details or []
