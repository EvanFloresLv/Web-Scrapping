"""Pydantic request and response models for `GET /api/v1/metrics/query`.

Spec 0012 AC-6. snake_case fields and ISO-8601 datetimes with trailing `Z`
per the project JSON convention (spec 0001).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MetricPoint(BaseModel):
    """One minute aligned sample for a series."""

    bucket_start: datetime
    count: int
    sum_value: float
    p50_ms: float | None = Field(
        default=None,
        description=(
            "p50 latency in milliseconds, interpolated within the matching histogram "
            "bin. `null` on counter rows (no histogram) and on histogram rows whose "
            "p50 rank falls into the implicit `+Inf` bucket above 5 s."
        ),
    )
    p95_ms: float | None = None
    p99_ms: float | None = None


class MetricSeries(BaseModel):
    """One `(metric_name, labels)` time series."""

    metric: str
    labels: dict[str, Any]
    points: list[MetricPoint]


class MetricQueryResponse(BaseModel):
    """Response envelope for `/api/v1/metrics/query`."""

    series: list[MetricSeries]
