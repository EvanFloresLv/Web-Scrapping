"""`ExtractionService` composes fetch, parse, extract, validate (spec 0005 AC-1).

Side effect free: no DB write, no file write, no process-wide state. Feature 7
wraps this call with the persistence shell that writes `executions` and
`execution_results` rows. Every terminal path returns an `ExtractionResult`.

Observability (spec 0011 canonical catalogue): emits
`extraction.fetch_started`, `extraction.fetch_completed`,
`extraction.parse_completed`, `extraction.item_extracted` (debug, per item),
`extraction.extract_completed`, `extraction.validate_completed`, and
`extraction.failed`. `correlation_id` is carried via structlog contextvars
(bound by the HTTP middleware or `ExecutionService.execute`, spec 0011
AC-3/AC-4); when the executor also binds `execution_id` that field flows
through automatically too. Workflow identifiers are bound for the duration
of `run(...)` so every nested event carries them without per call kwargs.
Metrics stay unchanged.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import structlog
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

        Binds `workflow_id`, `workflow_version_id`, and `target_url` into
        structlog contextvars for the duration of the run (spec 0011
        catalogue) so every nested event carries them without per call
        kwargs. `correlation_id` and (when running inside the executor)
        `execution_id` are already bound by the caller.
        """
        workflow_id: UUID = workflow_version.workflow_id
        version_id: UUID = workflow_version.id
        with structlog.contextvars.bound_contextvars(
            workflow_id=str(workflow_id),
            workflow_version_id=str(version_id),
            target_url=target_url,
        ):
            return await self._run_bound(workflow_version, target_url)

    async def _run_bound(
        self,
        workflow_version: WorkflowVersion,
        target_url: str,
    ) -> ExtractionResult:
        total_start = time.perf_counter_ns()

        try:
            config = _coerce_config(workflow_version.config)
        except ExtractionError as exc:
            return self._fail(exc, total_start)

        if config.pagination is not None:
            pagination_exc = ExtractionError(
                ExtractionErrorCode.PAGINATION_UNSUPPORTED,
                "pagination is configured but not supported by this extractor",
                details=[{"reason": "pagination deferred to a future slice"}],
            )
            return self._fail(pagination_exc, total_start)

        _log.info("extraction.fetch_started", url=target_url, method="GET")
        fetch_start = time.perf_counter_ns()
        try:
            fetched = await self._fetcher.fetch(target_url)
        except FetchError as fetch_exc:
            observe_duration("fetch", (time.perf_counter_ns() - fetch_start) / 1e9)
            return self._fail(fetch_exc, total_start)
        fetch_ms = _elapsed_ms(fetch_start)
        observe_duration("fetch", fetch_ms / 1000)
        _log.info(
            "extraction.fetch_completed",
            url=target_url,
            final_url=fetched.final_url,
            duration_ms=fetch_ms,
        )

        parse_start = time.perf_counter_ns()
        document = parse_html(fetched.body, fetched.charset)
        parse_ms = _elapsed_ms(parse_start)
        observe_duration("parse", parse_ms / 1000)
        _log.info("extraction.parse_completed", duration_ms=parse_ms)

        try:
            extract_start = time.perf_counter_ns()
            items = extract(document, config, final_url=fetched.final_url)
            extract_ms = _elapsed_ms(extract_start)
            for index, item in enumerate(items):
                _log.debug(
                    "extraction.item_extracted",
                    item_index=index,
                    field_count=len(item),
                )
            _log.info(
                "extraction.extract_completed",
                duration_ms=extract_ms,
                items_extracted=len(items),
            )

            validate_start = time.perf_counter_ns()
            OutputSchemaValidator(config.output_schema).validate_all(items)
            validate_ms = _elapsed_ms(validate_start)
            observe_duration("validate", validate_ms / 1000)
            _log.info(
                "extraction.validate_completed",
                duration_ms=validate_ms,
                valid=True,
            )
        except ExtractionError as extract_exc:
            return self._fail(extract_exc, total_start)

        duration_ms = _elapsed_ms(total_start)
        observe_duration("total", duration_ms / 1000)
        increment_items("completed")

        return ExtractionResult(
            status="completed",
            items=items,
            items_count=len(items),
            duration_ms=duration_ms,
        )

    def _fail(
        self,
        exc: FetchError | ExtractionError,
        total_start: int,
    ) -> ExtractionResult:
        duration_ms = _elapsed_ms(total_start)
        observe_duration("total", duration_ms / 1000)
        increment_items("failed")
        _log.info(
            "extraction.failed",
            duration_ms=duration_ms,
            error_code=str(exc.code),
            error_type=type(exc).__name__,
            error_msg=exc.message,
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
