"""Async SQL helpers for the `metric_minute` table.

Three use cases:

- `upsert_rows`: the flusher's hot path. Multi row insert with
  `ON CONFLICT (bucket_start, metric_name, labels) DO UPDATE` summing the
  new deltas into the existing row (spec 0012 AC-4).
- `query_series`: the dashboard's read path. Pulls every row whose
  `metric_name` matches one of the requested metrics in the time window,
  optionally filtered with `labels @> :filter`, then groups by labels on
  the Python side so the SQL stays flat (spec 0012 AC-6).
- `delete_older_than`: the retention task. One `DELETE` of every row
  older than `retention_days` (spec 0012 AC-4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability.models import MetricMinute


@dataclass(frozen=True)
class MetricRow:
    """A per minute delta to upsert.

    `labels` is a plain dict; `MetricMinute.labels` is JSONB and Postgres
    matches on the serialized value, so stable key ordering matters at
    insert time. The flusher produces label dicts via `sorted(items)` to
    keep the key `(bucket_start, metric_name, labels)` deterministic.
    """

    bucket_start: datetime
    metric_name: str
    labels: dict[str, Any]
    count: int
    sum_value: float
    le_50ms: int = 0
    le_100ms: int = 0
    le_250ms: int = 0
    le_500ms: int = 0
    le_1s: int = 0
    le_5s: int = 0


async def upsert_rows(session: AsyncSession, rows: Sequence[MetricRow]) -> int:
    """Upsert a batch of per minute deltas. Returns the number of rows written.

    Each row adds its counts to any existing row for the same
    `(bucket_start, metric_name, labels)` triple. A row with zero
    observations is a no op; the flusher skips those upstream so this
    layer never sees them.
    """
    if not rows:
        return 0

    values = [
        {
            "bucket_start": row.bucket_start,
            "metric_name": row.metric_name,
            "labels": row.labels,
            "count": row.count,
            "sum_value": row.sum_value,
            "le_50ms": row.le_50ms,
            "le_100ms": row.le_100ms,
            "le_250ms": row.le_250ms,
            "le_500ms": row.le_500ms,
            "le_1s": row.le_1s,
            "le_5s": row.le_5s,
        }
        for row in rows
    ]

    stmt = pg_insert(MetricMinute).values(values)
    stmt = stmt.on_conflict_do_update(
        constraint="pk_metric_minute",
        set_={
            "count": MetricMinute.__table__.c.count + stmt.excluded.count,
            "sum_value": MetricMinute.__table__.c.sum_value + stmt.excluded.sum_value,
            "le_50ms": MetricMinute.__table__.c.le_50ms + stmt.excluded.le_50ms,
            "le_100ms": MetricMinute.__table__.c.le_100ms + stmt.excluded.le_100ms,
            "le_250ms": MetricMinute.__table__.c.le_250ms + stmt.excluded.le_250ms,
            "le_500ms": MetricMinute.__table__.c.le_500ms + stmt.excluded.le_500ms,
            "le_1s": MetricMinute.__table__.c.le_1s + stmt.excluded.le_1s,
            "le_5s": MetricMinute.__table__.c.le_5s + stmt.excluded.le_5s,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return len(values)


async def query_rows(
    session: AsyncSession,
    *,
    metric_names: Sequence[str],
    time_from: datetime,
    time_to: datetime,
    labels_filter: dict[str, Any] | None,
) -> list[MetricMinute]:
    """Load every row whose metric name + window + label filter matches.

    Grouping into series happens in the service layer; this helper stays
    a thin SQL wrapper so the caller can decide the shape it wants.
    """
    stmt = select(MetricMinute).where(
        and_(
            MetricMinute.metric_name.in_(list(metric_names)),
            MetricMinute.bucket_start >= time_from,
            MetricMinute.bucket_start < time_to,
        )
    )
    if labels_filter:
        stmt = stmt.where(MetricMinute.labels.cast(JSONB).contains(labels_filter))
    stmt = stmt.order_by(MetricMinute.bucket_start.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_older_than(session: AsyncSession, cutoff: datetime) -> int:
    """Delete every row with `bucket_start < cutoff`. Returns row count."""
    stmt = delete(MetricMinute).where(MetricMinute.bucket_start < cutoff)
    result = await session.execute(stmt)
    await session.commit()
    # rowcount is a CursorResult attribute; Result typing hides it on the async wrapper.
    row_count: int = result.rowcount or 0  # type: ignore[attr-defined]
    return row_count
