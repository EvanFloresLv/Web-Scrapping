"""Error code registry endpoint (spec 0007 AC-13, AC-14).

`GET /api/v1/_meta/error-codes` returns the full catalogue of error codes the
API can emit, built once at module import time by reflecting the five enums
in `app.core.errors.execution_codes` and every registered `PlatformError`
subclass. The payload is sorted by `code` and contains no duplicates (the
startup uniqueness assertion in `register_exception_handlers` guarantees
one code to one subclass).

Response shape: `list[{code, domain, http_status, title}]`.

The endpoint is unauthenticated (AC-14); see the follow up in spec 0007 for
revisiting that once admin UI auth lands.
"""

from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.core.errors import PlatformError, _all_platform_error_subclasses
from app.core.errors.execution_codes import (
    AgentErrorCode,
    ExecutionErrorCode,
    ExtractionErrorCode,
    FetchErrorCode,
    WorkflowErrorCode,
)

router = APIRouter(tags=["meta"])


class ErrorCodeEntry(BaseModel):
    code: str
    domain: str
    http_status: int
    title: str


def _default_status_for(code: str) -> int:
    """Convention based status when no subclass registers this code (AC-13)."""
    suffix = code.rsplit(".", 1)[-1]
    if suffix == "not_found":
        return status.HTTP_404_NOT_FOUND
    if suffix in {"conflict", "inactive", "immutable_field"}:
        return status.HTTP_409_CONFLICT
    return status.HTTP_422_UNPROCESSABLE_ENTITY


def _title_fallback(code: str) -> str:
    """Title case code segments when no subclass registers this code."""
    _, _, slug = code.partition(".")
    return slug.replace("_", " ").replace(".", " ").title() if slug else code.title()


def _collect_entries() -> list[ErrorCodeEntry]:
    enums: tuple[type[Enum], ...] = (
        FetchErrorCode,
        ExtractionErrorCode,
        ExecutionErrorCode,
        WorkflowErrorCode,
        AgentErrorCode,
    )
    subclass_by_code: dict[str, type[PlatformError]] = {
        cls.code: cls for cls in _all_platform_error_subclasses()
    }

    seen: dict[str, ErrorCodeEntry] = {}

    def _add(code: str) -> None:
        if code in seen:
            return
        domain = code.split(".", 1)[0]
        cls = subclass_by_code.get(code)
        if cls is not None:
            entry = ErrorCodeEntry(
                code=code,
                domain=domain,
                http_status=cls.status_code,
                title=cls.title,
            )
        else:
            entry = ErrorCodeEntry(
                code=code,
                domain=domain,
                http_status=_default_status_for(code),
                title=_title_fallback(code),
            )
        seen[code] = entry

    for enum_cls in enums:
        for member in enum_cls:
            _add(str(member.value))

    for code in subclass_by_code:
        _add(code)

    return sorted(seen.values(), key=lambda e: e.code)


# Cached once at import; reflects the enum + subclass tree at app startup.
_REGISTRY: list[ErrorCodeEntry] = _collect_entries()


@router.get("/_meta/error-codes", response_model=list[ErrorCodeEntry])
async def list_error_codes() -> list[ErrorCodeEntry]:
    """Return the full error code catalogue (AC-13)."""
    return _REGISTRY


__all__ = ["ErrorCodeEntry", "router"]
