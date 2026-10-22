"""Shared `prometheus-client` registry and instrument factories.

Spec 0012 AC-1 and AC-2. One `CollectorRegistry` per process holds every
Histogram and Counter the app observes. Instrument names, label sets, and
histogram bins are declared here so the flusher, the query API, and tests
all read from one source of truth.

The HTTP histograms use six finite bins (0.05, 0.1, 0.25, 0.5, 1, 5 s) plus
the implicit `+Inf` bucket. The `metric_minute` table stores the six finite
bins; the open ended tail is derivable from `count - le_5s` at query time.
"""

from __future__ import annotations

from typing import Final

from prometheus_client import CollectorRegistry, Counter, Histogram

# Six finite histogram bins used by every duration histogram in the project.
# Chosen to cover the common operator latency reads (sub 100 ms, sub 1 s,
# sub 5 s) without over resolving a long tail that the operator dashboard
# cannot usefully distinguish. Match the `le_*` columns on `metric_minute`.
HISTOGRAM_BUCKETS_S: Final[tuple[float, ...]] = (0.05, 0.1, 0.25, 0.5, 1.0, 5.0)

# The closed set of metric names the registry declares. The query endpoint
# rejects any `metric` not in this set before touching the database.
HTTP_REQUEST_DURATION_SECONDS: Final[str] = "http_request_duration_seconds"
HTTP_REQUESTS_TOTAL: Final[str] = "http_requests_total"
EXTRACTION_DURATION_SECONDS: Final[str] = "extraction_duration_seconds"
EXTRACTION_RUNS_TOTAL: Final[str] = "extraction_runs_total"
EXECUTION_DURATION_SECONDS: Final[str] = "execution_duration_seconds"
EXECUTIONS_TOTAL: Final[str] = "executions_total"
THROTTLE_EVENTS_TOTAL: Final[str] = "throttle_events_total"

KNOWN_METRIC_NAMES: Final[frozenset[str]] = frozenset(
    {
        HTTP_REQUEST_DURATION_SECONDS,
        HTTP_REQUESTS_TOTAL,
        EXTRACTION_DURATION_SECONDS,
        EXTRACTION_RUNS_TOTAL,
        EXECUTION_DURATION_SECONDS,
        EXECUTIONS_TOTAL,
        THROTTLE_EVENTS_TOTAL,
    }
)


class MetricsRegistry:
    """Container for the process wide registry and every instrument.

    Lives as a singleton via `get_registry()`. Kept as a class so tests
    can build a fresh one in isolation without poking module globals.
    """

    def __init__(self) -> None:
        self.registry: CollectorRegistry = CollectorRegistry()

        self.http_request_duration_seconds: Histogram = Histogram(
            HTTP_REQUEST_DURATION_SECONDS,
            "HTTP request latency, labelled by method, FastAPI route template, and status class.",
            labelnames=("method", "route", "status_class"),
            buckets=HISTOGRAM_BUCKETS_S,
            registry=self.registry,
        )
        self.http_requests_total: Counter = Counter(
            HTTP_REQUESTS_TOTAL,
            "HTTP request count, labelled by method, FastAPI route template, and status class.",
            labelnames=("method", "route", "status_class"),
            registry=self.registry,
        )

        self.extraction_duration_seconds: Histogram = Histogram(
            EXTRACTION_DURATION_SECONDS,
            "Extraction phase duration, labelled by workflow id, status, and phase.",
            labelnames=("workflow_id", "status", "phase"),
            buckets=HISTOGRAM_BUCKETS_S,
            registry=self.registry,
        )
        self.extraction_runs_total: Counter = Counter(
            EXTRACTION_RUNS_TOTAL,
            "Extraction run count, labelled by workflow id, status, and phase.",
            labelnames=("workflow_id", "status", "phase"),
            registry=self.registry,
        )

        self.execution_duration_seconds: Histogram = Histogram(
            EXECUTION_DURATION_SECONDS,
            "Execution duration, labelled by workflow id and status.",
            labelnames=("workflow_id", "status"),
            buckets=HISTOGRAM_BUCKETS_S,
            registry=self.registry,
        )
        self.executions_total: Counter = Counter(
            EXECUTIONS_TOTAL,
            "Execution count, labelled by workflow id and status.",
            labelnames=("workflow_id", "status"),
            registry=self.registry,
        )

        self.throttle_events_total: Counter = Counter(
            THROTTLE_EVENTS_TOTAL,
            "Per host throttle events (scaffolded for a future throttle feature).",
            labelnames=("website_host",),
            registry=self.registry,
        )


_registry: MetricsRegistry | None = None


def get_registry() -> MetricsRegistry:
    """Return the process wide `MetricsRegistry` singleton."""
    global _registry
    if _registry is None:
        _registry = MetricsRegistry()
    return _registry


def reset_registry_for_tests() -> None:
    """Drop the registry so the next `get_registry()` builds a fresh one.

    Only call from test setup. Reusing the same `CollectorRegistry` across
    tests leaks counter values and double registers the same instrument
    name on a second `MetricsRegistry()` construction.
    """
    global _registry
    _registry = None
