"""Daily retention sweep for `metric_minute`.

Spec 0012 AC-4. One asyncio task runs once per day, deleting every row
with `bucket_start < NOW() - make_interval(days => METRICS_RETENTION_DAYS)`.
Short delay before the first run so a bare startup does not block on an
immediate retention sweep.

A single `DELETE` is cheap enough that this task does not touch the
flusher's backlog or compete with it; the two tasks share the session
factory but not the transaction.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.logging import get_logger
from app.core.observability.repository import delete_older_than

_log = get_logger("app.metrics.retention")

_RETENTION_INTERVAL_S = 24 * 60 * 60  # 24 hours.
_FIRST_RUN_DELAY_S = 60  # Let the app settle before the first sweep.


class MetricsRetention:
    """Owns the daily `metric_minute` cleanup task."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[Any],
        retention_days: int,
        interval_s: float = _RETENTION_INTERVAL_S,
        first_run_delay_s: float = _FIRST_RUN_DELAY_S,
        now: Any = None,
    ) -> None:
        self._session_factory = session_factory
        self._retention_days = retention_days
        self._interval_s = interval_s
        self._first_run_delay_s = first_run_delay_s
        self._now = now or (lambda: datetime.now(tz=UTC))
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def _sweep(self) -> int:
        cutoff = self._now() - timedelta(days=self._retention_days)
        started = time.perf_counter_ns()
        async with self._session_factory() as session:
            deleted = await delete_older_than(session, cutoff)
        duration_ms = (time.perf_counter_ns() - started) // 1_000_000
        _log.info(
            "metrics.retention_completed",
            rows_deleted=deleted,
            cutoff=cutoff.isoformat(),
            duration_ms=duration_ms,
        )
        return deleted

    async def _run(self) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=self._first_run_delay_s)
        if self._stop_event.is_set():
            return
        while not self._stop_event.is_set():
            try:
                await self._sweep()
            except Exception as exc:
                _log.warning(
                    "metrics.retention_failed",
                    error_type=type(exc).__name__,
                    error_msg=str(exc),
                )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_s)

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("MetricsRetention is already running.")
        self._task = asyncio.create_task(self._run(), name="metrics-retention")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except TimeoutError:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None
