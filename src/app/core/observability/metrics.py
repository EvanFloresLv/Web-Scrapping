"""Thin metrics wrapper (spec 0005 AC-15, spec 0006 AC-13).

The MVP writes samples through a Python logger so the shape is validated
end to end without pulling in Prometheus or OpenTelemetry. Feature 13
swaps the backend behind the same interface.

Instruments:

- `extraction_duration_seconds` (histogram shaped, label `phase`): one
  sample per phase of an extraction (`fetch`, `parse`, `validate`, `total`).
- `extraction_items_total` (counter, label `status`): one bump per
  extraction run.
- `executions_total` (counter, label `status`): one bump per executor
  terminal (spec 0006 AC-13).
- `execution_duration_seconds` (histogram shaped, label `status`): one
  sample per executor terminal (spec 0006 AC-13).
"""

from __future__ import annotations

from typing import Literal

from app.core.logging import get_logger

Phase = Literal["fetch", "parse", "validate", "total"]
_Status = Literal["completed", "failed"]

_metrics_log = get_logger("app.metrics")


def observe_duration(phase: Phase, duration_s: float) -> None:
    """Record a duration sample for one phase of a run (spec 0005 AC-15)."""
    _metrics_log.debug(
        "metrics.observe_duration",
        name="extraction_duration_seconds",
        phase=phase,
        value=duration_s,
    )


def increment_items(status: _Status) -> None:
    """Record one terminal run of the extractor (spec 0005 AC-15)."""
    _metrics_log.debug(
        "metrics.increment_items",
        name="extraction_items_total",
        status=status,
    )


def observe_execution_duration(status: _Status, duration_s: float) -> None:
    """Record one executor duration sample (spec 0006 AC-13)."""
    _metrics_log.debug(
        "metrics.observe_duration",
        name="execution_duration_seconds",
        status=status,
        value=duration_s,
    )


def increment_executions(status: _Status) -> None:
    """Record one executor terminal (spec 0006 AC-13)."""
    _metrics_log.debug(
        "metrics.increment_items",
        name="executions_total",
        status=status,
    )
