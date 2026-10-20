"""HTTP router for the websites domain (spec 0002).

Mounts two REST resources: `/websites` and `/websites/{id}/targets` (nested
create + list), plus `/targets/{id}` for single-target reads and mutations.
All error responses are RFC 7807 Problem Details with the per domain `code`
and the `correlation_id` extension; the domain exceptions in
`app.domains.websites.errors` all go through the shared `PlatformError`
handler in `app.core.errors`, which also renders their `self.errors`
entries verbatim (spec 0007 AC-1, AC-3).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.domains.websites.enums import WebsiteStatus
from app.domains.websites.errors import (
    ImmutableFieldError,
    InvalidPaginationError,
)
from app.domains.websites.repository import WebsiteRepository
from app.domains.websites.schemas import (
    PaginatedList,
    TargetCreate,
    TargetRead,
    TargetUpdate,
    WebsiteCreate,
    WebsiteRead,
    WebsiteUpdate,
)
from app.domains.websites.service import TargetService, WebsiteService

router = APIRouter(tags=["websites"])

StatusQuery = Literal["active", "inactive", "all"]


# --- dependency wiring ------------------------------------------------------


def _website_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WebsiteService:
    return WebsiteService(session, WebsiteRepository(session))


def _target_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TargetService:
    return TargetService(session, WebsiteRepository(session))


def _parse_status_filter(value: StatusQuery) -> WebsiteStatus | None:
    """Translate the `?status=` query into the service filter.

    `all` means "no status filter" (soft deleted is still excluded by the
    repository); otherwise narrow to that one status.
    """
    if value == "all":
        return None
    return WebsiteStatus(value)


def _validate_pagination(page: int, page_size: int) -> None:
    """Pagination bounds per spec 0001 + spec 0002 AC-7.

    Raised as a domain exception so the Problem response carries
    `code=website.invalid_pagination`, which `_validation_error_handler` would not.
    """
    if page < 1 or page_size < 1 or page_size > 200:
        raise InvalidPaginationError("page must be >= 1 and page_size must be in 1..200")


# --- websites: create + read -----------------------------------------------


@router.post(
    "/websites",
    status_code=status.HTTP_201_CREATED,
    response_model=WebsiteRead,
)
async def create_website(
    payload: WebsiteCreate,
    service: Annotated[WebsiteService, Depends(_website_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WebsiteRead:
    """Register a new website (AC-1)."""
    website = await service.create(host=payload.host, display_name=payload.display_name)
    await session.commit()
    return WebsiteRead.model_validate(website)


@router.get("/websites", response_model=PaginatedList[WebsiteRead])
async def list_websites(
    service: Annotated[WebsiteService, Depends(_website_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    status_filter: Annotated[StatusQuery, Query(alias="status")] = "active",
) -> PaginatedList[WebsiteRead]:
    """List live websites, paginated (AC-8)."""
    _validate_pagination(page, page_size)
    items, total = await service.list(
        page=page,
        page_size=page_size,
        status_filter=_parse_status_filter(status_filter),
    )
    return PaginatedList[WebsiteRead](
        items=[WebsiteRead.model_validate(w) for w in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/websites/{website_id}", response_model=WebsiteRead)
async def get_website(
    website_id: UUID,
    service: Annotated[WebsiteService, Depends(_website_service)],
) -> WebsiteRead:
    """Fetch one website (AC-9)."""
    website = await service.get(website_id)
    return WebsiteRead.model_validate(website)


@router.patch("/websites/{website_id}", response_model=WebsiteRead)
async def patch_website(
    website_id: UUID,
    payload: WebsiteUpdate,
    service: Annotated[WebsiteService, Depends(_website_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WebsiteRead:
    """Patch a website (AC-10). Immutable `host` raises `website.immutable_field`."""
    extras = payload.model_dump(exclude_unset=True)
    if "host" in extras:
        raise ImmutableFieldError("host")
    website = await service.update(
        website_id,
        display_name=payload.display_name,
        status=payload.status,
    )
    await session.commit()
    return WebsiteRead.model_validate(website)


@router.delete("/websites/{website_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_website(
    website_id: UUID,
    service: Annotated[WebsiteService, Depends(_website_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Soft delete a website; cascades to its targets (AC-11, idempotent)."""
    await service.delete(website_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- targets nested under a website ----------------------------------------


@router.post(
    "/websites/{website_id}/targets",
    status_code=status.HTTP_201_CREATED,
    response_model=TargetRead,
)
async def create_target(
    website_id: UUID,
    payload: TargetCreate,
    service: Annotated[TargetService, Depends(_target_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TargetRead:
    """Register a target under a website (AC-2)."""
    target = await service.create(
        website_id=website_id,
        url=payload.url,
        label=payload.label,
    )
    await session.commit()
    return TargetRead.model_validate(target)


@router.get(
    "/websites/{website_id}/targets",
    response_model=PaginatedList[TargetRead],
)
async def list_targets(
    website_id: UUID,
    service: Annotated[TargetService, Depends(_target_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    status_filter: Annotated[StatusQuery, Query(alias="status")] = "active",
) -> PaginatedList[TargetRead]:
    """List targets under a website (AC-8)."""
    _validate_pagination(page, page_size)
    items, total = await service.list_for_website(
        website_id,
        page=page,
        page_size=page_size,
        status_filter=_parse_status_filter(status_filter),
    )
    return PaginatedList[TargetRead](
        items=[TargetRead.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# --- targets: single resource routes ---------------------------------------


@router.get("/targets/{target_id}", response_model=TargetRead)
async def get_target(
    target_id: UUID,
    service: Annotated[TargetService, Depends(_target_service)],
) -> TargetRead:
    target = await service.get(target_id)
    return TargetRead.model_validate(target)


@router.patch("/targets/{target_id}", response_model=TargetRead)
async def patch_target(
    target_id: UUID,
    payload: TargetUpdate,
    service: Annotated[TargetService, Depends(_target_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TargetRead:
    """Patch a target (AC-10). Immutable `url` raises `website.immutable_field`."""
    extras = payload.model_dump(exclude_unset=True)
    if "url" in extras:
        raise ImmutableFieldError("url")
    target = await service.update(
        target_id,
        label=payload.label,
        status=payload.status,
    )
    await session.commit()
    return TargetRead.model_validate(target)


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    target_id: UUID,
    service: Annotated[TargetService, Depends(_target_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await service.delete(target_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def register_website_handlers(app: FastAPI) -> None:
    """No op since spec 0007 (AC-1, AC-3).

    `DuplicateWebsiteError` and `DuplicateTargetError` carry their
    `existing_id` plus canonical identifier as `meta` on a single
    `self.errors` entry; the shared `PlatformError` handler renders them.
    Kept as a hook so `app.main` can wire future website specific handlers
    without reshaping the registration call list.
    """
    return None
