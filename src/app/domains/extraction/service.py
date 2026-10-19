"""`ExtractionService` composes fetch, parse, extract, validate (spec 0005 AC-1).

Side effect free: no DB write, no file write, no process-wide state. Feature 7
wraps this call with the persistence shell that writes `executions` and
`execution_results` rows. Every terminal path returns an `ExtractionResult`.

Observability (AC-15): emits `extraction.fetch_started`,
`extraction.fetch_completed`, `extraction.parse_completed`,
`extraction.item_extracted` (debug, per item), `extraction.completed`, and
`extraction.failed`, each carrying `correlation_id`, `workflow_version_id`,
`workflow_id`, `target_url`, and `duration_ms`/`items_count`/`error_code`
when known. The metrics wrapper records one duration sample per phase and
one counter bump per terminal state.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError

from app.core.errors.execution_codes import (
    ExtractionErrorCode,
)
from app.core.logging import get_logger
from app.core.observability.metrics import increment_items, observe_duration
from app.domains.extraction.errors import ExtractionError, FetchError
from app.domains.extraction.extractor import extract
from app.domains.extraction.fetcher import HttpFetcher
from app.domains.extraction.parser import parse_html
from app.domains.extraction.schemas import ExtractionResult
from app.domains.extraction.validator import OutputSchemaValidator
from app.domains.workflows.config import WorkflowConfig
from app.domains.workflows.models import WorkflowVersion

_log = get_logger("app.extraction")


def _elapsed_ms(start_ns: int) -> int:
    return (time.perf_counter_ns() - start_ns) // 1_000_000


def _coerce_config(payload: dict[str, Any]) -> WorkflowConfig:
    """Re-validate the stored `WorkflowConfig` on read (AC-1 value sourcing).

    The service never trusts the raw JSONB blob; feature 5 validates on
    write but reading through the Pydantic model again catches drift from
    out of band DB edits and guarantees the extractor sees a typed shape.
    """
    try:
        return WorkflowConfig.model_validate(payload)
    except PydanticValidationError as exc:
        raise ExtractionError(
            ExtractionErrorCode.OUTPUT_SCHEMA_MISMATCH,
            "stored WorkflowConfig failed re-validation",
            details=[{"message": str(exc)}],
        ) from exc


class ExtractionService:
    """Deterministic HTML extraction (spec 0005)."""

    def __init__(self, fetcher: HttpFetcher) -> None:
        self._fetcher = fetcher

    async def run(
        self,
        workflow_version: WorkflowVersion,
        target_url: str,
    ) -> ExtractionResult:
        """Fetch -> parse -> extract -> validate; return a terminal result.

        `target_url` is the canonical URL resolved by the caller against
        `target_urls`; the service does not do the lookup itself (that
        belongs to the preview router + feature 7's executor).
        """
        workflow_id: UUID = workflow_version.workflow_id
        version_id: UUID = workflow_version.id
        log_ctx: dict[str, Any] = {
            "workflow_version_id": str(version_id),
            "workflow_id": str(workflow_id),
            "target_url": target_url,
        }
        total_start = time.perf_counter_ns()

        try:
            config = _coerce_config(workflow_version.config)
        except ExtractionError as exc:
            return self._fail(exc, log_ctx, total_start)

        if config.pagination is not None:
            pagination_exc = ExtractionError(
                ExtractionErrorCode.PAGINATION_UNSUPPORTED,
                "pagination is configured but not supported by this extractor",
                details=[{"reason": "pagination deferred to a future slice"}],
            )
            return self._fail(pagination_exc, log_ctx, total_start)

        _log.info("extraction.fetch_started", **log_ctx)
        fetch_start = time.perf_counter_ns()
        try:
            fetched = await self._fetcher.fetch(target_url)
        except FetchError as fetch_exc:
            observe_duration("fetch", (time.perf_counter_ns() - fetch_start) / 1e9)
            return self._fail(fetch_exc, log_ctx, total_start)
        fetch_ms = _elapsed_ms(fetch_start)
        observe_duration("fetch", fetch_ms / 1000)
        _log.info(
            "extraction.fetch_completed",
            **log_ctx,
            duration_ms=fetch_ms,
            final_url=fetched.final_url,
        )

        parse_start = time.perf_counter_ns()
        document = parse_html(fetched.body, fetched.charset)
        parse_ms = _elapsed_ms(parse_start)
        observe_duration("parse", parse_ms / 1000)
        _log.info("extraction.parse_completed", **log_ctx, duration_ms=parse_ms)

        try:
            items = extract(document, config, final_url=fetched.final_url)
            for index, item in enumerate(items):
                _log.debug(
                    "extraction.item_extracted",
                    **log_ctx,
                    item_index=index,
                    field_count=len(item),
                )

            validate_start = time.perf_counter_ns()
            OutputSchemaValidator(config.output_schema).validate_all(items)
            observe_duration("validate", (time.perf_counter_ns() - validate_start) / 1e9)
        except ExtractionError as extract_exc:
            return self._fail(extract_exc, log_ctx, total_start)

        duration_ms = _elapsed_ms(total_start)
        observe_duration("total", duration_ms / 1000)
        increment_items("completed")
        _log.info(
            "extraction.completed",
            **log_ctx,
            duration_ms=duration_ms,
            items_count=len(items),
        )

        return ExtractionResult(
            status="completed",
            items=items,
            items_count=len(items),
            duration_ms=duration_ms,
        )

    def _fail(
        self,
        exc: FetchError | ExtractionError,
        log_ctx: dict[str, Any],
        total_start: int,
    ) -> ExtractionResult:
        duration_ms = _elapsed_ms(total_start)
        observe_duration("total", duration_ms / 1000)
        increment_items("failed")
        _log.info(
            "extraction.failed",
            **log_ctx,
            duration_ms=duration_ms,
            error_code=str(exc.code),
            error_message=exc.message,
        )
        return ExtractionResult(
            status="failed",
            items=None,
            items_count=0,
            duration_ms=duration_ms,
            error_code=str(exc.code),
            error_message=exc.message,
            error_details=list(exc.details) if exc.details else None,
        )
