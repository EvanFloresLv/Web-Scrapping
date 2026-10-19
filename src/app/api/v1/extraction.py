"""Preview endpoint for the extraction domain (spec 0005 AC-2, AC-3, AC-16).

`POST /api/v1/workflows/{workflow_id}/versions/{id}/preview`

Reads the version by `(workflow_id, id)` (any status is previewable:
draft, published, archived), resolves `target_url` to a live
`target_urls` row under the same website, then calls
`ExtractionService.run(...)` and returns the `ExtractionResult` as JSON.

Error responses are RFC 7807 Problem Details with the per-domain `code`
and the `correlation_id` extension; the `PreviewInvalidBodyError` carries
a `details` list naming the Pydantic field path.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import PROBLEM_CONTENT_TYPE, Problem
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
        details = [
            {
                "field": ".".join(str(loc) for loc in err["loc"]),
                "message": err["msg"],
            }
            for err in exc.errors()
        ]
        raise PreviewInvalidBodyError(
            "preview request body is invalid",
            details=details,
        ) from exc
    except ValueError as exc:
        # Malformed JSON (not shape-related). Same code; Pydantic path empty.
        raise PreviewInvalidBodyError(
            "preview request body is not valid JSON",
            details=[{"field": "", "message": str(exc)}],
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


# --- 422 Problem Details for PreviewInvalidBodyError (with `details[]`) ----


async def _preview_invalid_body_handler(
    request: Request,
    exc: PreviewInvalidBodyError,
) -> JSONResponse:
    problem = Problem(
        title=exc.title,
        status=exc.status_code,
        detail=str(exc),
        instance=str(request.url.path),
        code=exc.code,
        correlation_id=correlation_id.get(),
    )
    body: dict[str, Any] = problem.model_dump(exclude_none=True)
    body["details"] = exc.details
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        media_type=PROBLEM_CONTENT_TYPE,
    )


def register_extraction_handlers(app: FastAPI) -> None:
    """Register the preview endpoint's `details[]` handler (AC-16)."""
    app.add_exception_handler(
        PreviewInvalidBodyError,
        _preview_invalid_body_handler,  # type: ignore[arg-type]
    )


__all__ = ["register_extraction_handlers", "router"]
