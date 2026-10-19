"""Repository for the websites domain (spec 0002).

One concrete repository class holding the CRUD surface for both aggregates;
the services depend on this interface. Soft deleted rows are filtered out of
every read path by default, so the API only ever sees live rows (AC-8, AC-9).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.websites.enums import WebsiteStatus
from app.domains.websites.models import TargetURL, Website


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class WebsiteRepository:
    """Persistence surface for `Website` + `TargetURL` aggregates (spec 0002)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- websites -------------------------------------------------------

    async def add_website(self, website: Website) -> None:
        self._session.add(website)
        await self._session.flush()

    async def get_website(self, website_id: UUID) -> Website | None:
        """Return a live website by id, or None (AC-9: soft-deleted = 404)."""
        stmt = select(Website).where(
            Website.id == website_id,
            Website.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_website_by_host(self, host: str) -> Website | None:
        """Return a live website by canonical host (duplicate detection)."""
        stmt = select(Website).where(
            Website.host == host,
            Website.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_websites(
        self,
        *,
        status_filter: WebsiteStatus | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Website], int]:
        """List live websites with `(items, total)` for pagination (AC-8).

        `status_filter=None` means "all statuses" (ignore `status`); a value
        narrows to that status only. Soft deleted rows are always excluded.
        """
        base = select(Website).where(Website.deleted_at.is_(None))
        if status_filter is not None:
            base = base.where(Website.status == status_filter.value)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one())

        items_stmt = (
            base.order_by(Website.created_at.desc(), Website.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self._session.execute(items_stmt)).scalars().all())
        return items, total

    async def soft_delete_website(self, website: Website) -> None:
        """Mark a website deleted and cascade-soft-delete its targets (AC-11)."""
        now = _utcnow()
        website.deleted_at = now
        await self._session.execute(
            update(TargetURL)
            .where(
                TargetURL.website_id == website.id,
                TargetURL.deleted_at.is_(None),
            )
            .values(deleted_at=now)
        )
        await self._session.flush()

    # ---- target urls ----------------------------------------------------

    async def add_target(self, target: TargetURL) -> None:
        self._session.add(target)
        await self._session.flush()

    async def get_target(self, target_id: UUID) -> TargetURL | None:
        stmt = select(TargetURL).where(
            TargetURL.id == target_id,
            TargetURL.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_target_by_url(
        self,
        *,
        website_id: UUID,
        url: str,
    ) -> TargetURL | None:
        """Return a live target by (website_id, canonical url) for dedup."""
        stmt = select(TargetURL).where(
            TargetURL.website_id == website_id,
            TargetURL.url == url,
            TargetURL.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_targets_for_website(
        self,
        website_id: UUID,
        *,
        status_filter: WebsiteStatus | None,
        page: int,
        page_size: int,
    ) -> tuple[list[TargetURL], int]:
        """List live targets under a website (AC-8).

        The parent website's `status` does not gate the listing: an inactive
        parent still lists its targets (AC-8); a soft-deleted parent is
        handled at the service layer as a 404.
        """
        base = select(TargetURL).where(
            TargetURL.website_id == website_id,
            TargetURL.deleted_at.is_(None),
        )
        if status_filter is not None:
            base = base.where(TargetURL.status == status_filter.value)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one())

        items_stmt = (
            base.order_by(TargetURL.created_at.desc(), TargetURL.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self._session.execute(items_stmt)).scalars().all())
        return items, total

    async def soft_delete_target(self, target: TargetURL) -> None:
        target.deleted_at = _utcnow()
        await self._session.flush()
