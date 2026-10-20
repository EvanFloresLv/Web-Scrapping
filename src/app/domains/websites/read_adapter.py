"""Concrete `TargetReadPort` adapter for the executions domain (spec 0006 AC-3, AC-14a).

Lives in the websites package because it reads the websites ORM. The port
itself is declared in `app.core.targets` so the executions domain can import
it without crossing the `import-linter` independence boundary.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.targets import TargetReadPort, TargetSummary
from app.domains.websites.models import TargetURL


class TargetReadAdapter(TargetReadPort):
    """Read live targets by id through the request-scoped session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_live_target(self, target_id: UUID) -> TargetSummary | None:
        stmt = select(TargetURL).where(
            TargetURL.id == target_id,
            TargetURL.deleted_at.is_(None),
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return TargetSummary(id=row.id, website_id=row.website_id, url=row.url)


__all__ = ["TargetReadAdapter"]
