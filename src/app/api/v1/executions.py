"""HTTP router for the sync workflow execution endpoint (spec 0006).

`POST /api/v1/workflows/{workflow_id}/execute` runs a published workflow
version against a registered target URL and returns the structured items in
one response. `GET /api/v1/executions/{id}` reads the stored row back.

Pre run validation failures (unknown workflow / version / target, draft or
archived version, workflow without a current version, target under a
different website) return 4xx with Problem Details and persist no row.
Failures discovered after extraction has started persist a `failed` row and
return 200 with the failed body (per AC-8).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import ErrorDetail
from app.core.extraction import ExtractionPort
from app.core.targets import TargetReadPort
from app.core.workflows import WorkflowReadPort
from app.domains.executions.cursor import decode_cursor, encode_cursor
from app.domains.executions.enums import ExecutionStatus
from app.domains.executions.errors import (
    InvalidExecuteBodyError,
    InvalidListQueryError,
)
from app.domains.executions.models import Execution
from app.domains.executions.repository import (
    ExecutionListFilters,
    SqlAlchemyExecutionRepository,
    SqlAlchemyExecutionResultRepository,
)
from app.domains.executions.schemas import (
    ExecuteRequest,
    ExecutionBody,
    ExecutionItem,
    ExecutionListItem,
    ExecutionListQuery,
    ExecutionListResponse,
    ExecutionResponse,
)
from app.domains.executions.service import ExecutionService
from app.domains.extraction.adapter import ExtractionPortAdapter
from app.domains.extraction.dependencies import get_http_fetcher
from app.domains.extraction.fetcher import HttpFetcher
from app.domains.extraction.service import ExtractionService
from app.domains.websites.read_adapter import TargetReadAdapter
from app.domains.workflows.read_adapter import WorkflowReadAdapter

router = APIRouter(tags=["executions"])


# --- dependency wiring -----------------------------------------------------


def _workflow_read_port(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowReadPort:
    return WorkflowReadAdapter(session)


def _target_read_port(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TargetReadPort:
    return TargetReadAdapter(session)


def _extraction_port(
    fetcher: Annotated[HttpFetcher, Depends(get_http_fetcher)],
) -> ExtractionPort:
    return ExtractionPortAdapter(ExtractionService(fetcher))


def _execution_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    workflow_port: Annotated[WorkflowReadPort, Depends(_workflow_read_port)],
    target_port: Annotated[TargetReadPort, Depends(_target_read_port)],
    extraction: Annotated[ExtractionPort, Depends(_extraction_port)],
) -> ExecutionService:
    return ExecutionService(
        session=session,
        execution_repo=SqlAlchemyExecutionRepository(session),
        result_repo=SqlAlchemyExecutionResultRepository(session),
        workflow_port=workflow_port,
        target_port=target_port,
        extraction=extraction,
    )


# --- response assembly -----------------------------------------------------


def _build_response(execution: Execution, workflow_id: UUID) -> ExecutionResponse:
    """Shape the Execution + results into the AC-7 response body."""
    try:
        results = list(execution.results)
    except Exception:
        results = []
    items = [
        ExecutionItem(item_index=row.item_index, payload=row.payload)
        for row in sorted(results, key=lambda r: r.item_index)
    ]
    body = ExecutionBody(
        id=execution.id,
        workflow_id=workflow_id,
        workflow_version_id=execution.workflow_version_id,
        target_url_id=execution.target_url_id,
        status=execution.status,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        duration_ms=execution.duration_ms,
        items_extracted=execution.items_extracted,
        error_code=execution.error_code,
        error_message=execution.error_message,
        correlation_id=execution.correlation_id,
        created_at=execution.created_at,
    )
    return ExecutionResponse(execution=body, items=items)


# --- endpoints -------------------------------------------------------------


@router.post(
    "/workflows/{workflow_id}/execute",
    response_model=ExecutionResponse,
)
async def execute_workflow(
    workflow_id: UUID,
    request: Request,
    service: Annotated[ExecutionService, Depends(_execution_service)],
) -> ExecutionResponse:
    """Run a workflow against a registered target URL (AC-1)."""
    raw = await request.body()
    try:
        payload = ExecuteRequest.model_validate_json(raw)
    except PydanticValidationError as exc:
        entries = [
            ErrorDetail(
                code=InvalidExecuteBodyError.code,
                loc=list(err["loc"]),
                message=err["msg"],
                meta={"type": err["type"]},
            )
            for err in exc.errors()
        ]
        raise InvalidExecuteBodyError(
            "execute request body is invalid",
            errors=entries,
        ) from exc
    except ValueError as exc:
        raise InvalidExecuteBodyError(
            "execute request body is not valid JSON",
            errors=[
                ErrorDetail(
                    code=InvalidExecuteBodyError.code,
                    loc=[],
                    message=str(exc),
                )
            ],
        ) from exc

    cid = correlation_id.get() or ""
    execution = await service.execute(
        workflow_id=workflow_id,
        target_url_id=payload.target_url_id,
        version_id=payload.version_id,
        correlation_id=cid,
    )
    _, resolved_workflow_id = await service.get(execution.id)
    return _build_response(execution, resolved_workflow_id)


@router.get(
    "/executions",
    response_model=ExecutionListResponse,
)
async def list_executions(
    request: Request,
    service: Annotated[ExecutionService, Depends(_execution_service)],
) -> ExecutionListResponse:
    """List executions matching the given filters (spec 0010 AC-1..AC-6).

    Query parsing is done by hand (not FastAPI's `Depends`) so a validation
    failure surfaces as our Problem Details `execution.invalid_list_query`
    with the Pydantic field path in `details[].loc`, matching the house
    error contract (spec 0007 AC-3).
    """
    raw = dict(request.query_params)
    try:
        query = ExecutionListQuery.model_validate(raw)
    except PydanticValidationError as exc:
        entries = [
            ErrorDetail(
                code=InvalidListQueryError.code,
                loc=["query", *(str(part) for part in err["loc"])],
                message=err["msg"],
                meta={"type": err["type"]},
            )
            for err in exc.errors()
        ]
        raise InvalidListQueryError(
            "execution list query is invalid",
            errors=entries,
        ) from exc

    cursor = decode_cursor(query.cursor) if query.cursor else None
    filters = ExecutionListFilters(
        workflow_id=query.workflow_id,
        status=ExecutionStatus(query.status) if query.status else None,
        target_url_id=query.target_url_id,
        website_id=query.website_id,
        correlation_id=query.correlation_id,
        created_from=query.created_from,
        created_to=query.created_to,
        with_deleted=query.with_deleted,
    )
    rows, workflow_ids = await service.list_page(
        filters,
        cursor=cursor,
        page_size=query.page_size,
    )
    items = [
        ExecutionListItem(
            id=row.id,
            workflow_id=workflow_ids[row.workflow_version_id],
            workflow_version_id=row.workflow_version_id,
            target_url_id=row.target_url_id,
            status=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            duration_ms=row.duration_ms,
            items_extracted=row.items_extracted,
            error_code=row.error_code,
            error_message=row.error_message,
            correlation_id=row.correlation_id,
            created_at=row.created_at,
        )
        for row in rows
        # Skip rows whose workflow was soft deleted mid flight: with_deleted
        # was false AND the workflow has since been removed. The repo filter
        # catches the common case; this is a belt and braces skip so the
        # response never has a KeyError for `workflow_ids[version_id]`.
        if row.workflow_version_id in workflow_ids
    ]
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if len(items) == query.page_size else None
    )
    return ExecutionListResponse(items=items, next_cursor=next_cursor)


@router.get(
    "/executions/{execution_id}",
    response_model=ExecutionResponse,
)
async def get_execution(
    execution_id: UUID,
    service: Annotated[ExecutionService, Depends(_execution_service)],
) -> ExecutionResponse:
    """Fetch one execution with its results (AC-9)."""
    execution, workflow_id = await service.get(execution_id)
    return _build_response(execution, workflow_id)


def register_execution_handlers(app: FastAPI) -> None:
    """No op since spec 0007 (AC-1, AC-3).

    `InvalidExecuteBodyError` carries its structured per field entries on
    `self.errors` now, and the shared `PlatformError` handler renders them.
    Kept as a hook so `app.main` can wire future execution specific
    handlers without reshaping the registration call list.
    """
    return None


__all__ = ["register_execution_handlers", "router"]
