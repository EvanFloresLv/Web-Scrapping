"""Background flusher: snapshot the registry, write per minute deltas to Postgres.

Spec 0012 AC-4 and AC-5. One asyncio task started in the FastAPI lifespan
runs this on a `METRICS_FLUSH_INTERVAL_S` cadence (default 15 s, hard
capped below 60 s so one tick is always inside a single wall clock minute).

`prometheus-client` samples are cumulative counters. To compute what a tick
contributed we snapshot every sample value, diff against the previous
snapshot (zero on the first tick), and attribute the delta to the wall
clock minute of the current tick. The snapshot is kept in memory on this
task; a worker restart loses it and the next successful tick after
restart attributes nothing to the gap (acceptable per spec 0012 ADR
tradeoffs).

Failure safety: on a DB write failure, computed rows are kept in a bounded
FIFO buffer keyed by `(bucket_start, metric_name, labels)`. The next
successful tick drains the backlog. Overflow drops the oldest minute and
emits one `metrics.buffer_overflow` log event per episode. The task never
raises out; a failed tick logs and the next tick retries.

M1 implements the happy path only. The failure safety and `metrics.*` log
events land in M3.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.logging import get_logger
from app.core.observability.registry import (
    HISTOGRAM_BUCKETS_S,
    MetricsRegistry,
    get_registry,
)
from app.core.observability.repository import MetricRow, upsert_rows

_log = get_logger("app.metrics.flusher")

# The six finite bins that back `metric_minute.le_*` columns.
_LE_COLUMNS: tuple[tuple[float, str], ...] = tuple(
    zip(
        HISTOGRAM_BUCKETS_S,
        ("le_50ms", "le_100ms", "le_250ms", "le_500ms", "le_1s", "le_5s"),
        strict=True,
    )
)


@dataclass
class _SampleKey:
    """A `(metric_name, labels_json)` pair identifies one time series."""

    metric_name: str
    labels_json: str

    def labels(self) -> dict[str, Any]:
        return dict(json.loads(self.labels_json)) if self.labels_json else {}


@dataclass
class _Snapshot:
    """Last seen values per sample, used to compute per tick deltas."""

    # count, sum, le_50ms, le_100ms, le_250ms, le_500ms, le_1s, le_5s
    counts: dict[_SampleKey, float] = field(default_factory=dict)
    sums: dict[_SampleKey, float] = field(default_factory=dict)
    bins: dict[_SampleKey, tuple[float, ...]] = field(default_factory=dict)


def _labels_json(labels: dict[str, str]) -> str:
    """Stable JSON encoding of a label dict for use as a map key.

    `prometheus-client` returns label values as strings. The flusher
    writes labels into JSONB; stable key ordering keeps the upsert key
    `(bucket_start, metric_name, labels)` reproducible across ticks.
    """
    return json.dumps(labels, sort_keys=True, separators=(",", ":"))


def _minute_bucket(now: datetime) -> datetime:
    """Floor `now` to the start of its minute, tz aware."""
    return now.replace(second=0, microsecond=0)


def _snapshot_registry(
    registry: MetricsRegistry,
) -> tuple[
    dict[_SampleKey, float],
    dict[_SampleKey, float],
    dict[_SampleKey, tuple[float, ...]],
]:
    """Read every sample out of the registry into three label indexed maps.

    `prometheus-client` exposes samples via `collect()`: each sample has a
    `.name`, `.labels` (dict), and `.value`. Histograms produce one
    `_bucket` sample per bin (plus `_count` and `_sum`); counters produce
    one `_total` sample.
    """
    counts: dict[_SampleKey, float] = {}
    sums: dict[_SampleKey, float] = {}
    bins: dict[_SampleKey, list[float]] = {}

    for metric in registry.registry.collect():
        base_name = metric.name  # e.g. http_request_duration_seconds
        for sample in metric.samples:
            labels = dict(sample.labels)
            if "le" in labels:
                le_label = labels.pop("le")
                key = _SampleKey(base_name, _labels_json(labels))
                bins.setdefault(key, [0.0] * len(HISTOGRAM_BUCKETS_S))
                try:
                    le_value = float(le_label)
                except ValueError:
                    # The `+Inf` bucket is implicit in `count`; skip it here.
                    continue
                for idx, bound in enumerate(HISTOGRAM_BUCKETS_S):
                    if abs(le_value - bound) < 1e-9:
                        bins[key][idx] = sample.value
                        break
            elif sample.name.endswith("_count"):
                key = _SampleKey(base_name, _labels_json(labels))
                counts[key] = sample.value
            elif sample.name.endswith("_sum"):
                key = _SampleKey(base_name, _labels_json(labels))
                sums[key] = sample.value
            elif sample.name.endswith("_total"):
                key = _SampleKey(base_name, _labels_json(labels))
                counts[key] = sample.value
            # `_created` and `_gcount`/`_gsum` samples are ignored.

    frozen_bins: dict[_SampleKey, tuple[float, ...]] = {
        key: tuple(values) for key, values in bins.items()
    }
    return counts, sums, frozen_bins


def _diff_to_rows(
    bucket: datetime,
    current_counts: dict[_SampleKey, float],
    current_sums: dict[_SampleKey, float],
    current_bins: dict[_SampleKey, tuple[float, ...]],
    previous: _Snapshot,
) -> list[MetricRow]:
    """Build per minute delta rows from a current + previous snapshot."""
    rows: list[MetricRow] = []
    for key, count_value in current_counts.items():
        prev_count = previous.counts.get(key, 0.0)
        delta_count = count_value - prev_count
        if delta_count <= 0:
            continue
        prev_sum = previous.sums.get(key, 0.0)
        delta_sum = current_sums.get(key, 0.0) - prev_sum
        bin_values = current_bins.get(key, tuple(0.0 for _ in HISTOGRAM_BUCKETS_S))
        prev_bin_values = previous.bins.get(key, tuple(0.0 for _ in HISTOGRAM_BUCKETS_S))
        bin_deltas = tuple(
            int(max(0.0, cur - prev)) for cur, prev in zip(bin_values, prev_bin_values, strict=True)
        )
        rows.append(
            MetricRow(
                bucket_start=bucket,
                metric_name=key.metric_name,
                labels=key.labels(),
                count=int(delta_count),
                sum_value=float(delta_sum),
                le_50ms=bin_deltas[0],
                le_100ms=bin_deltas[1],
                le_250ms=bin_deltas[2],
                le_500ms=bin_deltas[3],
                le_1s=bin_deltas[4],
                le_5s=bin_deltas[5],
            )
        )
    return rows


class MetricsFlusher:
    """Owns the periodic snapshot + upsert loop.

    One instance per process, created in the FastAPI lifespan.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[Any],
        interval_s: float,
        registry: MetricsRegistry | None = None,
        now: Any = None,
    ) -> None:
        self._session_factory = session_factory
        self._interval_s = interval_s
        self._registry = registry or get_registry()
        self._now = now or (lambda: datetime.now(tz=UTC))
        self._previous = _Snapshot()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def _tick(self) -> int:
        """Snapshot the registry, compute deltas, upsert. Returns rows written."""
        bucket = _minute_bucket(self._now())
        counts, sums, bins = _snapshot_registry(self._registry)
        rows = _diff_to_rows(bucket, counts, sums, bins, self._previous)
        if not rows:
            self._previous = _Snapshot(counts=counts, sums=sums, bins=bins)
            return 0

        started = time.perf_counter_ns()
        async with self._session_factory() as session:
            written = await upsert_rows(session, rows)
        duration_ms = (time.perf_counter_ns() - started) // 1_000_000
        _log.info(
            "metrics.flush_completed",
            rows_written=written,
            duration_ms=duration_ms,
        )
        self._previous = _Snapshot(counts=counts, sums=sums, bins=bins)
        return written

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_s)
            if self._stop_event.is_set():
                break
            try:
                await self._tick()
            except Exception as exc:
                # M1 happy path: log and keep running. M3 adds the FIFO buffer
                # and the `metrics.flush_failed` event.
                _log.warning(
                    "metrics.flush_failed",
                    error_type=type(exc).__name__,
                    error_msg=str(exc),
                )

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("MetricsFlusher is already running.")
        self._task = asyncio.create_task(self._run(), name="metrics-flusher")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        # Drain any outstanding delta on shutdown so a graceful stop does
        # not silently lose the last partial minute of samples.
        try:
            await self._tick()
        except Exception as exc:
            _log.warning(
                "metrics.flush_failed",
                error_type=type(exc).__name__,
                error_msg=str(exc),
            )
        try:
            await asyncio.wait_for(self._task, timeout=self._interval_s + 2.0)
        except TimeoutError:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None


__all__ = ["MetricsFlusher", "_diff_to_rows", "_minute_bucket", "_snapshot_registry"]
