"""HTTP router for the workflows domain (spec 0004).

Mounts three REST resources:

- `/websites/{website_id}/workflows` (nested create + list)
- `/workflows/{id}` (get, patch, delete)
- `/workflows/{workflow_id}/versions` (nested create + list) plus
  `/workflows/{workflow_id}/versions/{id}` (get, patch, delete) and the
  action endpoints `.../publish` and `.../archive`.

All error responses are RFC 7807 Problem Details carrying the per domain
`code` and the `correlation_id` extension (AC-13). Domain exceptions in
`app.domains.workflows.errors` are routed through the shared
`PlatformError` handler in `app.core.errors`; the one special case is
`WorkflowValidationError`, which carries a `details` list that we render
through a dedicated handler.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import PROBLEM_CONTENT_TYPE, Problem
from app.domains.workflows.enums import WorkflowStatus, WorkflowVersionStatus
from app.domains.workflows.errors import (
    ImmutableFieldError,
    InvalidPaginationError,
    WorkflowValidationError,
)
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.schemas import (
    PaginatedList,
    WorkflowCreate,
    WorkflowRead,
    WorkflowUpdate,
    WorkflowVersionCreate,
    WorkflowVersionRead,
    WorkflowVersionUpdate,
)
from app.domains.workflows.service import WorkflowService, WorkflowVersionService

router = APIRouter(tags=["workflows"])

_WORKFLOW_STATUS_VALUES = {"active", "inactive", "all"}
_VERSION_STATUS_VALUES = {"draft", "published", "archived", "all"}

_WORKFLOW_PATCHABLE_FIELDS = {"name", "description", "status"}
_VERSION_PATCHABLE_FIELDS = {"config"}


# --- dependency wiring -----------------------------------------------------


def _workflow_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowService:
    return WorkflowService(session, WorkflowRepository(session))


def _version_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowVersionService:
    return WorkflowVersionService(session, WorkflowRepository(session))


def _parse_workflow_status(value: str) -> WorkflowStatus | None:
    """Translate the `?status=` query. Raises `InvalidPaginationError` on an
    unknown value so AC-3 / AC-8 return `workflow.invalid_pagination`.
    """
    if value not in _WORKFLOW_STATUS_VALUES:
        raise InvalidPaginationError(f"status must be one of {sorted(_WORKFLOW_STATUS_VALUES)}")
    if value == "all":
        return None
    return WorkflowStatus(value)


def _parse_version_status(value: str) -> WorkflowVersionStatus | None:
    if value not in _VERSION_STATUS_VALUES:
        raise InvalidPaginationError(f"status must be one of {sorted(_VERSION_STATUS_VALUES)}")
    if value == "all":
        return None
    return WorkflowVersionStatus(value)


def _validate_pagination(page: int, page_size: int) -> None:
    """Pagination bounds per AC-3 / AC-8.

    Raised as a domain exception so the Problem response carries
    `code=workflow.invalid_pagination`.
    """
    if page < 1 or page_size < 1 or page_size > 200:
        raise InvalidPaginationError("page must be >= 1 and page_size must be in 1..200")


def _check_patchable(payload: dict[str, Any], allowed: set[str]) -> None:
    """Raise `ImmutableFieldError` on the first unknown PATCH key."""
    for key in payload:
        if key not in allowed:
            raise ImmutableFieldError(key)


# --- workflows nested under a website --------------------------------------


@router.post(
    "/websites/{website_id}/workflows",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowRead,
)
async def create_workflow(
    website_id: UUID,
    payload: WorkflowCreate,
    service: Annotated[WorkflowService, Depends(_workflow_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowRead:
    """Register a new workflow (AC-1)."""
    workflow = await service.create(
        website_id=website_id,
        name=payload.name,
        description=payload.description,
    )
    await session.commit()
    return WorkflowRead.model_validate(workflow)


@router.get(
    "/websites/{website_id}/workflows",
    response_model=PaginatedList[WorkflowRead],
)
async def list_workflows(
    website_id: UUID,
    service: Annotated[WorkflowService, Depends(_workflow_service)],
    page: Annotated[int, Query()] = 1,
    page_size: Annotated[int, Query()] = 50,
    status_filter: Annotated[str, Query(alias="status")] = "all",
    with_deleted: Annotated[bool, Query()] = False,
) -> PaginatedList[WorkflowRead]:
    """List workflows under a website (AC-3)."""
    _validate_pagination(page, page_size)
    items, total = await service.list_for_website(
        website_id,
        page=page,
        page_size=page_size,
        status_filter=_parse_workflow_status(status_filter),
        with_deleted=with_deleted,
    )
    return PaginatedList[WorkflowRead](
        items=[WorkflowRead.model_validate(w) for w in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# --- workflow by id --------------------------------------------------------


@router.get("/workflows/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(
    workflow_id: UUID,
    service: Annotated[WorkflowService, Depends(_workflow_service)],
) -> WorkflowRead:
    """Fetch one workflow (AC-3)."""
    workflow = await service.get(workflow_id)
    return WorkflowRead.model_validate(workflow)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowRead)
async def patch_workflow(
    workflow_id: UUID,
    payload: WorkflowUpdate,
    service: Annotated[WorkflowService, Depends(_workflow_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowRead:
    """Patch a workflow's mutable fields (AC-4)."""
    extras = payload.model_dump(exclude_unset=True)
    _check_patchable(extras, _WORKFLOW_PATCHABLE_FIELDS)
    workflow = await service.update(
        workflow_id,
        name=payload.name,
        description=payload.description,
        description_set="description" in extras,
        status=payload.status,
    )
    await session.commit()
    return WorkflowRead.model_validate(workflow)


@router.delete(
    "/workflows/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workflow(
    workflow_id: UUID,
    service: Annotated[WorkflowService, Depends(_workflow_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Soft delete a workflow (AC-5, idempotent)."""
    await service.delete(workflow_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- workflow versions -----------------------------------------------------


@router.post(
    "/workflows/{workflow_id}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowVersionRead,
)
async def create_version(
    workflow_id: UUID,
    payload: WorkflowVersionCreate,
    service: Annotated[WorkflowVersionService, Depends(_version_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowVersionRead:
    """Create a draft version (AC-6, AC-7)."""
    version = await service.create_draft(
        workflow_id=workflow_id,
        config_payload=payload.config,
    )
    await session.commit()
    return WorkflowVersionRead.model_validate(version)


@router.get(
    "/workflows/{workflow_id}/versions",
    response_model=PaginatedList[WorkflowVersionRead],
)
async def list_versions(
    workflow_id: UUID,
    service: Annotated[WorkflowVersionService, Depends(_version_service)],
    page: Annotated[int, Query()] = 1,
    page_size: Annotated[int, Query()] = 50,
    status_filter: Annotated[str, Query(alias="status")] = "all",
    with_deleted: Annotated[bool, Query()] = False,
) -> PaginatedList[WorkflowVersionRead]:
    """List versions under a workflow, newest `version_number` first (AC-8)."""
    _validate_pagination(page, page_size)
    items, total = await service.list_for_workflow(
        workflow_id,
        page=page,
        page_size=page_size,
        status_filter=_parse_version_status(status_filter),
        with_deleted=with_deleted,
    )
    return PaginatedList[WorkflowVersionRead](
        items=[WorkflowVersionRead.model_validate(v) for v in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/workflows/{workflow_id}/versions/{version_id}",
    response_model=WorkflowVersionRead,
)
async def get_version(
    workflow_id: UUID,
    version_id: UUID,
    service: Annotated[WorkflowVersionService, Depends(_version_service)],
) -> WorkflowVersionRead:
    """Fetch one version (AC-8)."""
    version = await service.get(workflow_id=workflow_id, version_id=version_id)
    return WorkflowVersionRead.model_validate(version)


@router.patch(
    "/workflows/{workflow_id}/versions/{version_id}",
    response_model=WorkflowVersionRead,
)
async def patch_version(
    workflow_id: UUID,
    version_id: UUID,
    payload: WorkflowVersionUpdate,
    service: Annotated[WorkflowVersionService, Depends(_version_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowVersionRead:
    """Replace a draft's `config` (AC-9).

    Empty body is a no op: returns the current version row unchanged.
    """
    extras = payload.model_dump(exclude_unset=True)
    _check_patchable(extras, _VERSION_PATCHABLE_FIELDS)
    if "config" not in extras:
        version = await service.get(workflow_id=workflow_id, version_id=version_id)
        return WorkflowVersionRead.model_validate(version)
    version = await service.patch_draft(
        workflow_id=workflow_id,
        version_id=version_id,
        config_payload=payload.config,
    )
    await session.commit()
    return WorkflowVersionRead.model_validate(version)


@router.delete(
    "/workflows/{workflow_id}/versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_version(
    workflow_id: UUID,
    version_id: UUID,
    service: Annotated[WorkflowVersionService, Depends(_version_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Hard delete a draft version (AC-10)."""
    await service.delete_draft(workflow_id=workflow_id, version_id=version_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- lifecycle actions -----------------------------------------------------


@router.post(
    "/workflows/{workflow_id}/versions/{version_id}/publish",
    response_model=WorkflowVersionRead,
)
async def publish_version(
    workflow_id: UUID,
    version_id: UUID,
    service: Annotated[WorkflowVersionService, Depends(_version_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowVersionRead:
    """Atomically publish a draft (AC-11)."""
    version = await service.publish(workflow_id=workflow_id, version_id=version_id)
    await session.commit()
    return WorkflowVersionRead.model_validate(version)


@router.post(
    "/workflows/{workflow_id}/versions/{version_id}/archive",
    response_model=WorkflowVersionRead,
)
async def archive_version(
    workflow_id: UUID,
    version_id: UUID,
    service: Annotated[WorkflowVersionService, Depends(_version_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowVersionRead:
    """Archive a published non current version (AC-12)."""
    version = await service.archive(workflow_id=workflow_id, version_id=version_id)
    await session.commit()
    return WorkflowVersionRead.model_validate(version)


# --- 422 Problem Details for WorkflowValidationError (with `details[]`) ----


async def _workflow_validation_handler(
    request: Request,
    exc: WorkflowValidationError,
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


def register_workflow_handlers(app: FastAPI) -> None:
    """Register the one handler that needs `details[]` extension (AC-13)."""
    app.add_exception_handler(
        WorkflowValidationError,
        _workflow_validation_handler,  # type: ignore[arg-type]
    )
