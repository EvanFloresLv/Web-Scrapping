"""Cross domain extraction port (spec 0006 AC-14a).

`ExtractionService.run(...)` (feature 6) accepts a `WorkflowVersion` ORM
instance. Importing it directly from the executions package would route
`executions -> extraction -> workflows` through the independence contract
and break the module boundary.

The port exposes just the shape the executor needs. The concrete adapter
lives in `app.domains.extraction` and wraps `ExtractionService`; executions
depends only on this Protocol plus the pure `ExtractionResult` value
object from `app.domains.extraction.schemas` (which has no workflows
imports), so the import graph stays clean.
"""

from __future__ import annotations

from typing import Protocol

from app.core.workflows import VersionSummary
from app.domains.extraction.schemas import ExtractionResult


class ExtractionPort(Protocol):
    """Minimal extraction surface the executor calls (spec 0006 AC-14a)."""

    async def run(
        self,
        version: VersionSummary,
        target_url: str,
    ) -> ExtractionResult:
        """Fetch, parse, extract, validate; return a terminal result."""
        ...


__all__ = ["ExtractionPort"]
