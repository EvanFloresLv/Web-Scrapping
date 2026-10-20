"""Service layer for the websites domain (spec 0002).

Enforces the business invariants the DB cannot express cleanly:

- Canonicalization (AC-3) is applied before every write.
- Dedup (AC-4) is checked via the repository then via a race-safe
  `IntegrityError` catch on the partial unique index.
- Host match (AC-5) compares `CanonicalURL.host` with the parent website's
  `host`.
- Parent state (AC-6): a soft-deleted website is a 404; an inactive website
  refuses new targets with `website.inactive`.
- Immutable fields (AC-10): `host` on `Website` and `url` on `TargetURL`
  cannot be patched.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.websites.enums import TargetStatus, WebsiteStatus
from app.domains.websites.errors import (
    CanonicalizationError,
    DuplicateTargetError,
    DuplicateWebsiteError,
    HostMismatchError,
    TargetNotFoundError,
    WebsiteInactiveError,
    WebsiteNotFoundError,
)
from app.domains.websites.models import TargetURL, Website
from app.domains.websites.repository import WebsiteRepository
from app.domains.websites.value_objects import (
    CanonicalHost,
    CanonicalURL,
    ValidationError,
)


class WebsiteService:
    """Use cases that mutate or read a `Website` aggregate (spec 0002)."""

    def __init__(self, session: AsyncSession, repository: WebsiteRepository) -> None:
        self._session = session
        self._repo = repository

    async def create(self, *, host: str, display_name: str) -> Website:
        """Create a new website (AC-1, AC-3, AC-4)."""
        try:
            canonical = CanonicalHost.from_str(host)
        except ValidationError as exc:
            raise CanonicalizationError(str(exc)) from exc

        existing = await self._repo.get_website_by_host(canonical.value)
        if existing is not None:
            raise DuplicateWebsiteError(
                existing_id=existing.id,
                canonical_host=existing.host,
            )

        website = Website(host=canonical.value, display_name=display_name)
        try:
            await self._repo.add_website(website)
        except IntegrityError as exc:
            # Race lost against another concurrent writer; re-read and 409.
            await self._session.rollback()
            existing = await self._repo.get_website_by_host(canonical.value)
            if existing is None:
                raise
            raise DuplicateWebsiteError(
                existing_id=existing.id,
                canonical_host=existing.host,
            ) from exc
        return website

    async def get(self, website_id: UUID) -> Website:
        website = await self._repo.get_website(website_id)
        if website is None:
            raise WebsiteNotFoundError(f"website {website_id} not found")
        return website

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        status_filter: WebsiteStatus | None,
    ) -> tuple[list[Website], int]:
        return await self._repo.list_websites(
            status_filter=status_filter,
            page=page,
            page_size=page_size,
        )

    async def update(
        self,
        website_id: UUID,
        *,
        display_name: str | None,
        status: WebsiteStatus | None,
    ) -> Website:
        """Patch mutable fields on a website (AC-10)."""
        website = await self.get(website_id)
        if display_name is not None:
            website.display_name = display_name
        if status is not None:
            website.status = status.value
        await self._session.flush()
        # `updated_at` carries `onupdate=func.now()`; refresh so the Python-side
        # value matches what Postgres computed, before the session is closed.
        await self._session.refresh(website)
        return website

    async def delete(self, website_id: UUID) -> None:
        """Soft delete the website and cascade-soft-delete its targets (AC-11).

        Idempotent: a request for an already-deleted (or never-existed) id
        returns `None`, mapped to `204 No Content` by the router.
        """
        website = await self._repo.get_website(website_id)
        if website is None:
            return
        await self._repo.soft_delete_website(website)


class TargetService:
    """Use cases that mutate or read a `TargetURL` under a `Website`."""

    def __init__(
        self,
        session: AsyncSession,
        repository: WebsiteRepository,
    ) -> None:
        self._session = session
        self._repo = repository

    async def create(
        self,
        *,
        website_id: UUID,
        url: str,
        label: str,
    ) -> TargetURL:
        """Create a target under a website (AC-2, AC-3, AC-4, AC-5, AC-6)."""
        website = await self._repo.get_website(website_id)
        if website is None:
            raise WebsiteNotFoundError(f"website {website_id} not found")
        if website.status != WebsiteStatus.ACTIVE.value:
            raise WebsiteInactiveError(f"website {website_id} is inactive; targets cannot be added")

        try:
            canonical = CanonicalURL.from_str(url)
        except ValidationError as exc:
            raise CanonicalizationError(str(exc)) from exc

        if canonical.host != website.host:
            raise HostMismatchError(
                expected_host=website.host,
                actual_host=canonical.host,
            )

        existing = await self._repo.get_target_by_url(
            website_id=website_id,
            url=canonical.value,
        )
        if existing is not None:
            raise DuplicateTargetError(
                existing_id=existing.id,
                canonical_url=existing.url,
            )

        target = TargetURL(
            website_id=website_id,
            url=canonical.value,
            label=label,
        )
        try:
            await self._repo.add_target(target)
        except IntegrityError as exc:
            await self._session.rollback()
            existing = await self._repo.get_target_by_url(
                website_id=website_id,
                url=canonical.value,
            )
            if existing is None:
                raise
            raise DuplicateTargetError(
                existing_id=existing.id,
                canonical_url=existing.url,
            ) from exc
        return target

    async def get(self, target_id: UUID) -> TargetURL:
        target = await self._repo.get_target(target_id)
        if target is None:
            raise TargetNotFoundError(f"target {target_id} not found")
        return target

    async def list_for_website(
        self,
        website_id: UUID,
        *,
        page: int,
        page_size: int,
        status_filter: WebsiteStatus | None,
    ) -> tuple[list[TargetURL], int]:
        """List targets under a website (AC-8: inactive parent still lists)."""
        website = await self._repo.get_website(website_id)
        if website is None:
            raise WebsiteNotFoundError(f"website {website_id} not found")
        return await self._repo.list_targets_for_website(
            website_id,
            status_filter=status_filter,
            page=page,
            page_size=page_size,
        )

    async def update(
        self,
        target_id: UUID,
        *,
        label: str | None,
        status: TargetStatus | None,
    ) -> TargetURL:
        target = await self.get(target_id)
        if label is not None:
            target.label = label
        if status is not None:
            target.status = status.value
        await self._session.flush()
        await self._session.refresh(target)
        return target

    async def delete(self, target_id: UUID) -> None:
        target = await self._repo.get_target(target_id)
        if target is None:
            return
        await self._repo.soft_delete_target(target)
