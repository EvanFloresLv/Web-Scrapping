"""Thin facade over the shared `prometheus-client` registry.

Spec 0012 M2 promotes the four helpers from DEBUG log stubs to real
`prometheus-client` observations against `get_registry()`. Signatures are
unchanged so callers in `ExtractionService` and `ExecutionService` keep
their shape; the `workflow_id` label is read from structlog contextvars,
which both services already bind (`workflow_id=str(workflow.id)` for the
execution lifespan, same for extraction's `_run_bound`). When the context
is missing (unit tests, direct calls) the label falls back to `unknown`
so cardinality stays bounded.

Instruments (see `app.core.observability.registry`):

- `extraction_duration_seconds` (histogram, labels `workflow_id`, `status`,
  `phase`): one sample per phase of an extraction (`fetch`, `parse`,
  `validate`, `total`).
- `extraction_runs_total` (counter, labels `workflow_id`, `status`, `phase`):
  one bump per extraction run (phase="total").
- `executions_total` (counter, labels `workflow_id`, `status`): one bump
  per executor terminal (spec 0006 AC-13).
- `execution_duration_seconds` (histogram, labels `workflow_id`, `status`):
  one sample per executor terminal (spec 0006 AC-13).
"""

from __future__ import annotations

from typing import Literal

import structlog

from app.core.observability.registry import get_registry

Phase = Literal["fetch", "parse", "validate", "total"]
_Status = Literal["completed", "failed"]


def _workflow_id_from_context() -> str:
    """Read the currently bound `workflow_id` from structlog contextvars.

    Both `ExtractionService._run_bound` and `ExecutionService.execute`
    bind this value for the duration of a run (spec 0011 AC-4). Missing
    bindings fall back to `unknown`.
    """
    bound = structlog.contextvars.get_contextvars()
    workflow_id = bound.get("workflow_id")
    if isinstance(workflow_id, str) and workflow_id:
        return workflow_id
    return "unknown"


def observe_duration(phase: Phase, duration_s: float) -> None:
    """Record a duration sample for one phase of an extraction run."""
    workflow_id = _workflow_id_from_context()
    # Mid run phases observe with status="completed" (the phase itself did
    # not raise). The terminal phase ("total") observes with the eventual
    # terminal status via a separate call site that also bumps the counter.
    get_registry().extraction_duration_seconds.labels(
        workflow_id=workflow_id,
        status="completed",
        phase=phase,
    ).observe(duration_s)


def increment_items(status: _Status) -> None:
    """Record one terminal run of the extractor."""
    workflow_id = _workflow_id_from_context()
    get_registry().extraction_runs_total.labels(
        workflow_id=workflow_id,
        status=status,
        phase="total",
    ).inc()


def observe_execution_duration(status: _Status, duration_s: float) -> None:
    """Record one executor duration sample (spec 0006 AC-13)."""
    workflow_id = _workflow_id_from_context()
    get_registry().execution_duration_seconds.labels(
        workflow_id=workflow_id,
        status=status,
    ).observe(duration_s)


def increment_executions(status: _Status) -> None:
    """Record one executor terminal (spec 0006 AC-13)."""
    workflow_id = _workflow_id_from_context()
    get_registry().executions_total.labels(
        workflow_id=workflow_id,
        status=status,
    ).inc()
