"""Cross domain read port for registered targets (spec 0006 AC-3, AC-14a).

The executions domain cannot import `app.domains.websites` directly: the
`import-linter` independence contract keeps every `app.domains.*` package
isolated. This module mirrors `app.core.workflows`: it declares the narrow
read surface the executor needs and the small value object it works with.
The concrete adapter lives in the websites domain.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TargetSummary(BaseModel):
    """Minimal target view the executor needs (spec 0006 AC-3)."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    website_id: UUID
    url: str


class TargetReadPort(Protocol):
    """Narrow read surface for the executor (spec 0006 AC-14a)."""

    async def get_live_target(self, target_id: UUID) -> TargetSummary | None:
        """Return the live target by id. `None` when missing or soft deleted."""
        ...


__all__ = ["TargetReadPort", "TargetSummary"]
