"""Concrete `ExtractionPort` adapter (spec 0006 AC-14a).

Bridges `app.core.extraction.ExtractionPort` to the real
`ExtractionService`. Lives in the extraction package so it can import the
workflows ORM to build the `WorkflowVersion` the service expects.

The adapter is a thin shim: it builds a transient (unsaved) `WorkflowVersion`
from a `VersionSummary`'s fields and hands it to `ExtractionService.run(...)`.
The service only reads `.id`, `.workflow_id`, and `.config`, so the stand in
is enough.
"""

from __future__ import annotations

from app.core.extraction import ExtractionPort
from app.core.workflows import VersionSummary
from app.domains.extraction.schemas import ExtractionResult
from app.domains.extraction.service import ExtractionService
from app.domains.workflows.models import WorkflowVersion


class ExtractionPortAdapter(ExtractionPort):
    """Wrap `ExtractionService.run(...)` behind the executor's port."""

    def __init__(self, service: ExtractionService) -> None:
        self._service = service

    async def run(
        self,
        version: VersionSummary,
        target_url: str,
    ) -> ExtractionResult:
        workflow_version = WorkflowVersion(
            id=version.id,
            workflow_id=version.workflow_id,
            config=version.config,
        )
        return await self._service.run(workflow_version, target_url)


__all__ = ["ExtractionPortAdapter"]
