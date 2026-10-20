"""Preview endpoint for the extraction domain (spec 0005 AC-2, AC-3, AC-16).

`POST /api/v1/workflows/{workflow_id}/versions/{id}/preview`

Reads the version by `(workflow_id, id)` (any status is previewable:
draft, published, archived), resolves `target_url` to a live
`target_urls` row under the same website, then calls
`ExtractionService.run(...)` and returns the `ExtractionResult` as JSON.

Error responses are RFC 7807 Problem Details with the per-domain `code`
and the `correlation_id` extension; the `PreviewInvalidBodyError` carries
an `errors` list naming the Pydantic field path (spec 0007 AC-3).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import ErrorDetail
from app.domains.extraction.dependencies import get_http_fetcher
from app.domains.extraction.errors import (
    PreviewInvalidBodyError,
    TargetNotRegisteredError,
)
from app.domains.extraction.fetcher import HttpFetcher
from app.domains.extraction.repository import ExtractionReadRepository
from app.domains.extraction.schemas import ExtractionResult, PreviewRequest
from app.domains.extraction.service import ExtractionService
from app.domains.websites.value_objects import CanonicalURL, ValidationError
from app.domains.workflows.errors import VersionNotFoundError, WorkflowNotFoundError

router = APIRouter(tags=["extraction"])


def _preview_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ExtractionReadRepository:
    return ExtractionReadRepository(session)


def _extraction_service(
    fetcher: Annotated[HttpFetcher, Depends(get_http_fetcher)],
) -> ExtractionService:
    return ExtractionService(fetcher)


@router.post(
    "/workflows/{workflow_id}/versions/{version_id}/preview",
    response_model=ExtractionResult,
)
async def preview_version(
    workflow_id: UUID,
    version_id: UUID,
    request: Request,
    repo: Annotated[ExtractionReadRepository, Depends(_preview_repo)],
    service: Annotated[ExtractionService, Depends(_extraction_service)],
) -> ExtractionResult:
    """Preview a workflow version against a registered target URL (AC-2, AC-3)."""
    raw = await request.body()
    try:
        payload = PreviewRequest.model_validate_json(raw)
    except PydanticValidationError as exc:
        entries = [
            ErrorDetail(
                code=PreviewInvalidBodyError.code,
                loc=list(err["loc"]),
                message=err["msg"],
                meta={"type": err["type"]},
            )
            for err in exc.errors()
        ]
        raise PreviewInvalidBodyError(
            "preview request body is invalid",
            errors=entries,
        ) from exc
    except ValueError as exc:
        # Malformed JSON (not shape-related). Same code; empty Pydantic path.
        raise PreviewInvalidBodyError(
            "preview request body is not valid JSON",
            errors=[
                ErrorDetail(
                    code=PreviewInvalidBodyError.code,
                    loc=[],
                    message=str(exc),
                )
            ],
        ) from exc

    workflow = await repo.get_live_workflow(workflow_id)
    if workflow is None:
        raise WorkflowNotFoundError(f"workflow {workflow_id} not found")

    version = await repo.get_version(workflow_id=workflow_id, version_id=version_id)
    if version is None:
        raise VersionNotFoundError(f"version {version_id} not found")

    try:
        canonical = CanonicalURL.from_str(payload.target_url)
    except ValidationError as exc:
        raise TargetNotRegisteredError(
            f"target url {payload.target_url!r} did not match any registered target"
        ) from exc

    target = await repo.get_live_target(
        website_id=workflow.website_id,
        canonical_url=canonical.value,
    )
    if target is None:
        raise TargetNotRegisteredError(
            f"target url {canonical.value!r} is not registered under this workflow's website"
        )

    return await service.run(version, canonical.value)


def register_extraction_handlers(app: FastAPI) -> None:
    """No op since spec 0007 (AC-1, AC-3).

    `PreviewInvalidBodyError` carries structured per field entries on
    `self.errors`; the shared `PlatformError` handler renders them. Kept
    as a hook so `app.main` can wire future extraction specific handlers
    without reshaping the registration call list.
    """
    return None


__all__ = ["register_extraction_handlers", "router"]
