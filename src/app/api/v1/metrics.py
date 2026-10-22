"""`GET /api/v1/metrics/query`: minute bucket time series read for the dashboard.

Spec 0012 AC-6. Multi metric, multi series response. `labels` query param is
a JSON encoded dict applied via `labels @> :filter`; omitted → returns one
series per distinct `labels` seen in the window.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import PlatformError
from app.core.observability.schemas import MetricQueryResponse
from app.core.observability.service import UnknownMetricError, query_series

router = APIRouter(prefix="/metrics", tags=["metrics"])


class MetricsBadRequestError(PlatformError):
    """400: a well formed request named a metric the registry does not know."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "metrics.unknown"
    title = "Bad Request"


class MetricsInvalidQueryError(PlatformError):
    """422: labels JSON, time range, or bucket value is malformed."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "metrics.invalid_query"
    title = "Unprocessable Entity"


def _parse_labels(raw: str | None) -> dict[str, Any] | None:
    """Decode the `labels` query param. 422 on bad JSON or non object."""
    if raw is None or raw == "":
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MetricsInvalidQueryError(
            detail=f"labels is not valid JSON: {exc.msg}",
            code="metrics.labels_invalid",
        ) from exc
    if not isinstance(parsed, dict):
        raise MetricsInvalidQueryError(
            detail="labels must be a JSON object.",
            code="metrics.labels_invalid",
        )
    return parsed


def _resolve_window(
    time_from: datetime | None,
    time_to: datetime | None,
) -> tuple[datetime, datetime]:
    """Default `to` → now, `from` → now - 1h. Both coerced to UTC."""
    now = datetime.now(tz=UTC)
    to_val = time_to if time_to is not None else now
    from_val = time_from if time_from is not None else to_val - timedelta(hours=1)
    if to_val.tzinfo is None:
        to_val = to_val.replace(tzinfo=UTC)
    if from_val.tzinfo is None:
        from_val = from_val.replace(tzinfo=UTC)
    if from_val >= to_val:
        raise MetricsInvalidQueryError(
            detail="`from` must be strictly earlier than `to`.",
            code="metrics.time_range_invalid",
        )
    return from_val, to_val


@router.get("/query", response_model=MetricQueryResponse)
async def query(
    session: Annotated[AsyncSession, Depends(get_session)],
    metric: Annotated[
        list[str],
        Query(
            min_length=1,
            description="One or more metric names (repeated query param).",
        ),
    ],
    time_from: Annotated[datetime | None, Query(alias="from")] = None,
    time_to: Annotated[datetime | None, Query(alias="to")] = None,
    bucket: Annotated[str, Query()] = "1m",
    labels: Annotated[str | None, Query()] = None,
) -> MetricQueryResponse:
    """Return minute aligned time series for the requested metrics.

    - `metric` is repeated: `?metric=a&metric=b`.
    - `from` / `to` default to `now - 1h` / `now`.
    - `bucket` is reserved for `5m`/`1h` roll ups later; M1 only serves `1m`.
    - `labels` is a JSON encoded dict applied as an equality filter via
      `labels @> ...`.
    """
    if bucket != "1m":
        raise MetricsInvalidQueryError(
            detail=f"bucket={bucket!r} is reserved; only `1m` ships in M1.",
            code="metrics.bucket_unsupported",
        )

    labels_filter = _parse_labels(labels)
    from_val, to_val = _resolve_window(time_from, time_to)

    try:
        series = await query_series(
            session,
            metric_names=metric,
            time_from=from_val,
            time_to=to_val,
            labels_filter=labels_filter,
        )
    except UnknownMetricError as exc:
        raise MetricsBadRequestError(
            detail=str(exc),
            code="metrics.unknown",
        ) from exc

    return MetricQueryResponse(series=series)
