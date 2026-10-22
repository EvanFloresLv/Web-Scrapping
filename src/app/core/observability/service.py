"""Query service: load `metric_minute` rows, group into series, compute percentiles.

Spec 0012 AC-6. Percentiles use linear interpolation inside the matching
histogram bin. A bucket with zero observations returns `null` for every
percentile. A percentile whose rank falls into the implicit `+Inf` bucket
(above 5 s) also returns `null` rather than a fabricated value.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability.registry import HISTOGRAM_BUCKETS_S, KNOWN_METRIC_NAMES
from app.core.observability.repository import query_rows
from app.core.observability.schemas import MetricPoint, MetricSeries


class UnknownMetricError(ValueError):
    """Raised when the query names a metric the registry does not know."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Unknown metric name: {name!r}.")
        self.name = name


# `metric_minute.le_*` columns in the same order as `HISTOGRAM_BUCKETS_S`.
_LE_COLUMN_ORDER: tuple[str, ...] = (
    "le_50ms",
    "le_100ms",
    "le_250ms",
    "le_500ms",
    "le_1s",
    "le_5s",
)


def _labels_key(labels: dict[str, Any]) -> str:
    """Stable JSON key for grouping rows into series (matches the flusher)."""
    return json.dumps(labels, sort_keys=True, separators=(",", ":"))


def _percentile_ms(
    rank: float,
    count: int,
    bins: tuple[int, int, int, int, int, int],
) -> float | None:
    """Linear interpolation within the matching bin, result in milliseconds.

    `rank` is a fraction between 0 and 1 (0.5 for p50). The histogram
    columns are cumulative, matching the Prometheus convention. The
    implicit `+Inf` tail is `count - last_bin`; a rank falling into it
    returns `None`.
    """
    if count <= 0:
        return None
    target = rank * count
    previous_cumulative = 0.0
    previous_bound_s = 0.0
    for cumulative, bound_s in zip(bins, HISTOGRAM_BUCKETS_S, strict=True):
        if target <= cumulative:
            bin_count = cumulative - previous_cumulative
            if bin_count <= 0:
                # Zero width in this bin; conventionally return the upper
                # bound so the series is monotonic.
                return bound_s * 1000.0
            fraction = (target - previous_cumulative) / bin_count
            value_s = previous_bound_s + fraction * (bound_s - previous_bound_s)
            return value_s * 1000.0
        previous_cumulative = cumulative
        previous_bound_s = bound_s
    # Falls above the last finite bin, into the implicit `+Inf` bucket.
    return None


async def query_series(
    session: AsyncSession,
    *,
    metric_names: list[str],
    time_from: datetime,
    time_to: datetime,
    labels_filter: dict[str, Any] | None,
) -> list[MetricSeries]:
    """Return one `MetricSeries` per distinct `(metric_name, labels)` in the window.

    Raises `UnknownMetricError` on the first metric name the registry does
    not know; the router maps this to HTTP 400.
    """
    for name in metric_names:
        if name not in KNOWN_METRIC_NAMES:
            raise UnknownMetricError(name)

    rows = await query_rows(
        session,
        metric_names=metric_names,
        time_from=time_from,
        time_to=time_to,
        labels_filter=labels_filter,
    )

    grouped: dict[tuple[str, str], MetricSeries] = {}
    for row in rows:
        key = (row.metric_name, _labels_key(row.labels))
        series = grouped.get(key)
        if series is None:
            series = MetricSeries(metric=row.metric_name, labels=dict(row.labels), points=[])
            grouped[key] = series

        bins: tuple[int, int, int, int, int, int] = (
            int(row.le_50ms),
            int(row.le_100ms),
            int(row.le_250ms),
            int(row.le_500ms),
            int(row.le_1s),
            int(row.le_5s),
        )
        count_int = int(row.count)
        series.points.append(
            MetricPoint(
                bucket_start=row.bucket_start,
                count=count_int,
                sum_value=float(row.sum_value),
                p50_ms=_percentile_ms(0.50, count_int, bins),
                p95_ms=_percentile_ms(0.95, count_int, bins),
                p99_ms=_percentile_ms(0.99, count_int, bins),
            )
        )

    # Sort series by (metric, labels_key) for a deterministic response.
    return [grouped[key] for key in sorted(grouped.keys())]


__all__ = ["UnknownMetricError", "query_series"]
