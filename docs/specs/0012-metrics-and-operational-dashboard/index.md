# 0012 — Metrics & operational dashboard

**Status**: Proposed
**Date**: 2026-10-22
**Mode**: FEATURE
**Scope feature**: 13 (Slice 3: Observability)
**Builds on**: [0001 Stack & architecture](../0001-stack-and-architecture/index.md), [0008 Admin UI foundation](../0008-admin-ui-foundation/index.md), [0010 Execution browser](../0010-execution-browser.md), [0011 Structured logging & correlation](../0011-structured-logging-and-correlation/index.md)
**Rationale**: see [rationale.md](./rationale.md)

## Summary

Collect four families of operational metrics in-process (request rate + latency, HTTP error rate, extraction success/failure + duration, executions throughput + duration, per-domain throttling counters), flush them every 15 seconds into a Postgres `metric_minute` table keyed by minute bucket + metric + labels, and render them in a new `/metrics` tab in the admin SPA with four Recharts panels. One JSON admin API serves the dashboard; a scrape endpoint is deferred. The metrics subsystem is always on, admin-key gated, resilient to Postgres blips (bounded in-memory buffer), and emits its own health events through spec 0011's catalogue. A run-detail page link opens the dashboard pre-filtered to a workflow.

## Requirements

Acceptance criteria the build plan satisfies and `/check verify` checks.

- **AC-1 Metric families collected**: the collection layer exposes four prometheus-client instruments: `http_request_duration_seconds` (Histogram, bins at 0.05/0.1/0.25/0.5/1/5 s), `http_requests_total` (Counter), `extraction_duration_seconds` (Histogram, same bins), `extraction_runs_total` (Counter), `execution_duration_seconds` (Histogram, same bins), `executions_total` (Counter), and `throttle_events_total` (Counter, scaffolded for a future throttle feature). Every mutation that already emits a log event (per spec 0011) also updates the matching instrument.
- **AC-2 Labels**: HTTP instruments carry `method`, `route` (the FastAPI path template, never the raw path), `status_class` (closed set `{2xx, 3xx, 4xx, 5xx}`); execution and extraction instruments carry `workflow_id` and `status` (closed set `{completed, failed}`, matching `_Status` in `app.core.observability.metrics` today and spec 0006 AC-13); extraction instruments additionally carry `phase` (closed set `{fetch, parse, validate, total}`, matching the phases the extraction service emits today in `src/app/domains/extraction/service.py`); throttling counter carries `website_host`. No instrument carries a user-supplied free-form string (keeps cardinality bounded).
- **AC-3 Storage schema**: a `metric_minute` table in the primary database with columns `bucket_start TIMESTAMPTZ NOT NULL`, `metric_name VARCHAR(64) NOT NULL`, `labels JSONB NOT NULL DEFAULT '{}'::jsonb`, `count BIGINT NOT NULL DEFAULT 0`, `sum_value DOUBLE PRECISION NOT NULL DEFAULT 0`, and six bucket count columns `le_50ms`, `le_100ms`, `le_250ms`, `le_500ms`, `le_1s`, `le_5s` (`BIGINT NOT NULL DEFAULT 0`). Primary key `(bucket_start, metric_name, labels)`; secondary index on `(bucket_start DESC)` for time-range scans. Minute-aligned timestamps.
- **AC-4 Flusher cadence**: an asyncio background task started in the FastAPI lifespan reads the in-process prometheus-client registry every `METRICS_FLUSH_INTERVAL_S` seconds (default 15, constrained `>= 1` and `<= 59` so one tick is always strictly inside one minute). Each tick computes the delta since its own last snapshot (prometheus-client samples carry no observation timestamp, so the flusher is the clock), and attributes the delta to the minute of the tick's wall clock. The result is upserted into `metric_minute` (`ON CONFLICT (bucket_start, metric_name, labels) DO UPDATE` summing the deltas). A separate task runs once per day and deletes rows older than `METRICS_RETENTION_DAYS` (default 7). Attribution error from a tick that straddles a minute boundary is bounded to one bucket by the `< 60 s` constraint.
- **AC-5 Flusher failure safety**: on an upsert failure the flusher keeps the *computed per-minute delta rows* (what would have been upserted on this tick) in an in-memory FIFO buffer, keyed by `(bucket_start, metric_name, labels)` so a retry can merge with later deltas for the same minute. The next successful tick drains the backlog. The buffer caps at `METRICS_BUFFER_CAP_MINUTES` minutes of pending data (default 15); minutes older than the cap are dropped and a single `metrics.buffer_overflow` log event is emitted per overflow episode. Raw prometheus-client samples are NOT buffered (the registry is cumulative, buffering raw samples would double count on recovery). The flusher never raises out of its task; the app continues serving requests through a Postgres incident.
- **AC-6 Query API**: `GET /api/v1/metrics/query` accepts `metric` (**repeated** query param, at least one required: `?metric=a&metric=b`), `from` (ISO-8601, default `now - 1h`), `to` (default `now`), `bucket` (default `1m`, future values `5m`/`1h` reserved but AC-6 ships only `1m`), and `labels` (JSON-encoded dict of equality filters applied via `labels @> ...`). When `labels` is omitted the endpoint returns **one series per distinct `labels` value** seen in the window (not one aggregated series); the dashboard panels rely on this to group by `route`, `status_class`, `phase`, and `workflow_id`. Returns `{"series": [{"metric": "...", "labels": {...}, "points": [{"bucket_start": "...", "count": N, "sum_value": X, "p50_ms": X, "p95_ms": X, "p99_ms": X}, ...]}, ...]}`. Percentiles are computed from the six bin counts by linear interpolation inside the matching bin; a bucket with zero observations returns `null` for every percentile; a percentile whose rank falls into the open-ended `+Inf` bucket (above 5 s) also returns `null` rather than a fabricated value. Response fields follow the project JSON convention (snake_case, ISO-8601 with trailing `Z`).
- **AC-7 Dashboard route**: a new `/metrics` top-nav tab is added to the admin SPA alongside Websites / Workflows / Executions. It renders four Recharts panels: (1) **Request rate + latency**: line chart of requests per minute + p50 and p95 latency, grouped by `route`, capped at the **top 10 routes by total request count in the window** so a 20-route service does not render 60 lines (the panel surfaces "N routes hidden" if the cap trips); (2) **HTTP error rate**: stacked area of **raw counts** per `status_class` (visual share is the operator's read, no server side rate math); (3) **Extraction**: stacked bar of completed vs failed counts + a p95 duration line, grouped by `phase`, **aggregated across workflows by default**, narrowed when the toolbar workflow filter is set; (4) **Executions**: line chart of throughput + a p95 duration line, **aggregated across workflows by default**, narrowed by the filter. A toolbar carries the time-window selector (fixed at last 60 minutes for the MVP) and a workflow filter (ties to AC-9).
- **AC-8 Empty state**: each panel checks whether its series set is empty for the selected window and renders a `"No data in the last hour"` placeholder with the panel title still visible; charts are not drawn as flat zero lines (that implies activity).
- **AC-9 Run-detail deep link**: the run-detail page (spec 0010) gains a `"View metrics"` link that routes to `/metrics?workflow_id=<id>`. The dashboard reads the `workflow_id` query param on mount, applies it to the execution and extraction panels (HTTP panels are unaffected, no workflow dimension), and surfaces the current filter visibly in the toolbar so the operator can clear it. The toolbar workflow input is a **free text UUID input** for the MVP (keeps the dashboard self-contained; a dropdown of known workflows is a later polish once the workflows list is paginated into a shared store).
- **AC-10 Authorization**: the JSON API and the SPA route are behind the existing `X-API-Key` gate (spec 0008 AC-9); no new scope, role, or key type is introduced. The dashboard route is a child of the admin SPA shell, so unauthenticated access redirects the same way every other admin page does.
- **AC-11 Self-observability**: the flusher emits `metrics.flush_completed` (fields `rows_written`, `duration_ms`) on success and `metrics.flush_failed` (fields `error_code`, `error_type`, `error_msg`, `pending_minutes`) on error; the buffer overflow path emits `metrics.buffer_overflow` (`dropped_minutes`). All three events are added to spec 0011's canonical catalogue in the same build (see Follow-up).
- **AC-12 Configuration**: three new env vars read via `pydantic-settings`: `METRICS_FLUSH_INTERVAL_S` (int, 1 to 59 inclusive, default 15 — the `<60` upper bound keeps a flush tick inside one minute per AC-4), `METRICS_RETENTION_DAYS` (int, 1 to 90, default 7), `METRICS_BUFFER_CAP_MINUTES` (int, 1 to 120, default 15). All validated at startup per spec 0001's "validate at startup, fail fast" rule. The subsystem is always on in every environment; no `METRICS_ENABLED` flag.

## Decision

**Chosen approach**: pre-aggregated minute buckets in Postgres, in-process collection via `prometheus-client`, admin JSON query API, Recharts dashboard.

**Implementation skills**: `fastapi` (`fastapi/fastapi`, `.claude/skills/fastapi/`) · `sqlalchemy-alembic-expert-best-practices-code-review` (`wispbit-ai/skills`, `.claude/skills/sqlalchemy-alembic-expert-best-practices-code-review/`) · `python-testing-patterns` (`wshobson/agents`, `.claude/skills/python-testing-patterns/`) · `uv-package-manager` (`wshobson/agents`, `.claude/skills/uv-package-manager/`)

**Key choices (one line each)**:

- Collection library: `prometheus-client` in-process registry (histograms + counters), no scrape endpoint yet.
- Shared registry location: `src/app/core/observability/registry.py` (new module; the existing `metrics.py` keeps its public function surface and becomes a thin facade over the registry).
- Storage: Postgres `metric_minute` table with 6 histogram bins + count + sum; upsert on `(bucket_start, metric_name, labels)` with summing increments.
- Flusher: single asyncio task started in the FastAPI lifespan; one DB round-trip per flush tick with multi-row upsert.
- Retention: separate asyncio task on a daily cadence; a single `DELETE … WHERE bucket_start < NOW() - INTERVAL`.
- Percentile math: linear interpolation inside the matching histogram bin (standard Prometheus-style approximation on 6 bins is good enough for operator dashboards).
- Query API: one `GET /api/v1/metrics/query` endpoint; multi-metric, multi-series response.
- Dashboard: new TanStack Router route `/metrics` using `openapi-fetch` (auto-regenerated from the FastAPI OpenAPI) + TanStack Query + Recharts.
- Run-detail link: deep link via `/metrics?workflow_id=<id>` URL param (dashboard reads it on mount).
- No feature flag: metrics are always on in dev, test, staging, prod.

## Feature design

**Data model sketch**:

```
Table metric_minute
  bucket_start  TIMESTAMPTZ   NOT NULL                   -- minute aligned, UTC
  metric_name   VARCHAR(64)   NOT NULL                   -- e.g. http_request_duration_seconds
  labels        JSONB         NOT NULL DEFAULT '{}'::jsonb
  count         BIGINT        NOT NULL DEFAULT 0         -- total observations in the bucket
  sum_value     DOUBLE PREC.  NOT NULL DEFAULT 0         -- sum of observed values (seconds for histograms, 1-per-event for counters)
  le_50ms       BIGINT        NOT NULL DEFAULT 0         -- cumulative: observations <= 0.05 s
  le_100ms      BIGINT        NOT NULL DEFAULT 0         --                           <= 0.1 s
  le_250ms      BIGINT        NOT NULL DEFAULT 0         --                           <= 0.25 s
  le_500ms      BIGINT        NOT NULL DEFAULT 0         --                           <= 0.5 s
  le_1s         BIGINT        NOT NULL DEFAULT 0         --                           <= 1 s
  le_5s         BIGINT        NOT NULL DEFAULT 0         --                           <= 5 s
  PRIMARY KEY (bucket_start, metric_name, labels)
  INDEX ix_metric_minute_bucket_start_desc ON (bucket_start DESC)
```

Counters (e.g. `http_requests_total`) use `count` as the running increment and leave the `le_*` columns at 0.
Histograms (e.g. `http_request_duration_seconds`) populate `sum_value` and the six cumulative bin columns; the implicit `+Inf` bucket is `count` itself.

**State transitions**: not applicable (metrics are append-only time series).

**API surface**:

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/api/v1/metrics/query` | GET | `metric` (one or more, required), `from` (ISO, default `now-1h`), `to` (ISO, default `now`), `bucket` (default `1m`), `labels` (JSON object) | `{series: [{metric, labels, points: [{bucket_start, count, sum_value, p50_ms, p95_ms, p99_ms}, ...]}, ...]}` | `X-API-Key` | 400 unknown metric name, 422 invalid time range or labels JSON |

**Value sourcing**:

| Action | Value produced / displayed | Source |
|---|---|---|
| GET `/metrics/query` | `bucket_start` on each point | `metric_minute.bucket_start` |
| GET `/metrics/query` | `count`, `sum_value` on each point | `metric_minute` columns of the same name |
| GET `/metrics/query` | `p50_ms`, `p95_ms`, `p99_ms` | derived at query time from the six `le_*` bin counts via linear interpolation within the matching bin |
| GET `/metrics/query` | `labels` on each series | `metric_minute.labels` (JSONB), filtered by the `labels` query param via `labels @> ...` |
| HTTP middleware | `method` label | `request.method` |
| HTTP middleware | `route` label | `request.scope["route"].path` (the FastAPI path template, never `request.url.path`) |
| HTTP middleware | `status_class` label | `str(response.status_code // 100) + "xx"` |
| HTTP middleware | request duration | elapsed `time.perf_counter_ns()` between dispatch start and `call_next` return |
| Execution instrumentation | `workflow_id`, `status` labels | the `Execution.workflow_id` resolution already performed in `ExecutionService.execute` + `result.status` |
| Extraction instrumentation | `phase` label | the current phase in `ExtractionService._run_bound` (`fetch` / `parse` / `extract` / `validate`) |
| Flusher | `rows_written` on `metrics.flush_completed` | the count returned from the multi-row upsert |
| Dashboard | `workflow_id` filter | `useSearch()` on the TanStack Router route; absent → no label filter sent |
| Dashboard panel | p50/p95 series values | `points[*].p50_ms` / `p95_ms` from the query response |
| Run detail "View metrics" link target | `workflow_id` in the href | the current page's `workflow_id` route param |

**Key invariants**:

- One row in `metric_minute` per `(bucket_start, metric_name, labels)` triple; upserts never duplicate.
- `le_50ms <= le_100ms <= le_250ms <= le_500ms <= le_1s <= le_5s <= count` always (cumulative histogram shape).
- `metric_name` is drawn from a closed set declared in the registry module; unknown names are rejected at the query endpoint with HTTP 400 before any DB query runs.
- `labels` JSONB only ever carries the keys named in AC-2 for the matching instrument, and label values are drawn from the closed sets AC-2 names (status `{completed, failed}`, status_class `{2xx, 3xx, 4xx, 5xx}`, phase `{fetch, parse, validate, total}`), keeping cardinality bounded.
- The flusher never raises out of its asyncio task; a failing tick logs and retries, and the app keeps serving requests.
- One flusher tick is always strictly inside one wall-clock minute (`METRICS_FLUSH_INTERVAL_S < 60`), so a tick's delta is attributable to a single `bucket_start`.
- The data store is append-only: no row is updated after its minute window closes except by the retention task (`DELETE`).

**Security model**:

- All metrics endpoints and the dashboard route are gated by the same `X-API-Key` middleware as every other admin surface (spec 0008 AC-9); no additional scopes.
- Labels never carry PII or free-form user input; `workflow_id` and `website_host` are the only identifiers and both are server-owned.
- The query endpoint rejects unknown metric names before touching the database, bounding the SQL surface.
- No data retention beyond `METRICS_RETENTION_DAYS` (default 7). Operators can tune it down for stricter environments.

**Configuration required**:
- `METRICS_FLUSH_INTERVAL_S` (int, 1 to 59, default 15): how often the flusher writes bucket snapshots; capped below 60 s so one tick is always inside one minute (AC-4).
- `METRICS_RETENTION_DAYS` (int, 1 to 90, default 7): how long rows stay in `metric_minute`.
- `METRICS_BUFFER_CAP_MINUTES` (int, 1 to 120, default 15): how much pending data the flusher holds through a Postgres outage before dropping the oldest minute.

**Critical test scenarios** (each maps to an acceptance criterion in `## Requirements`):

- Happy path: send 100 requests across two routes, wait one flush tick, query `/metrics/query?metric=http_request_duration_seconds`, assert both routes appear as series with non-null `p50_ms`/`p95_ms` and counts summing to 100. Verifies **AC-1, AC-2, AC-3, AC-4, AC-6**.
- Dashboard happy path: load `/metrics` with seed data, assert all four panels render, each with at least one series and no `"No data"` placeholder. Verifies **AC-7**.
- Dashboard empty state: load `/metrics` against an empty `metric_minute`, assert every panel renders the `"No data in the last hour"` placeholder and no chart axis. Verifies **AC-8**.
- Deep link: from the run-detail page, click `"View metrics"`, assert the URL becomes `/metrics?workflow_id=<id>`, and that the execution + extraction panels filter to that workflow while the HTTP panels do not. Verifies **AC-9**.
- Auth: request `/api/v1/metrics/query` without `X-API-Key` → 401 Problem Details. Verifies **AC-10**.
- Flusher failure safety: with Postgres temporarily unavailable (patch the engine to raise), drive 5 minutes of traffic, assert the app continues serving 200s, assert one `metrics.flush_failed` per failed tick and no `metrics.buffer_overflow` while within the cap; restore Postgres, assert the next successful tick writes a `metrics.flush_completed` with the backlog's cumulative counts. Verifies **AC-5, AC-11**.
- Retention: insert rows with `bucket_start = now() - interval '8 days'`, run the retention task once, assert they are gone. Verifies **AC-4**.
- Config validation: boot with `METRICS_FLUSH_INTERVAL_S=0` or `METRICS_RETENTION_DAYS=1000`, assert the app refuses to start. Verifies **AC-12**.

## Build plan

Four Skateboard slices. The thinnest-usable-whole first (HTTP latency end-to-end), then widen, then harden, then wire the run-detail link.

**Slice M1: HTTP latency end-to-end (the skateboard).** Prove the full pipeline with one metric family.

1. Add `METRICS_FLUSH_INTERVAL_S`, `METRICS_RETENTION_DAYS`, `METRICS_BUFFER_CAP_MINUTES` to `Settings` with range validators (satisfies **AC-12**).
2. Add `prometheus-client` to the project via `uv add prometheus-client`; create `src/app/core/observability/registry.py` with a module-level `CollectorRegistry` and declare the four Histograms + three Counters named in AC-1 (satisfies **AC-1** scaffolding).
3. Migration `YYYYMMDDHHMM_metric_minute.py` creates the `metric_minute` table + PK + the time-range index (satisfies **AC-3**).
4. Instrument `RequestLoggingMiddleware` to observe `http_request_duration_seconds` + bump `http_requests_total` with `(method, route, status_class)` labels (satisfies **AC-1 HTTP**, **AC-2 HTTP**).
5. Create `src/app/core/observability/flusher.py`: an asyncio task that reads samples from the registry every `METRICS_FLUSH_INTERVAL_S`, rolls them into minute buckets, and upserts `metric_minute` with `ON CONFLICT … DO UPDATE SET … = EXCLUDED + metric_minute.*` (satisfies **AC-4** flush side).
6. Lifespan wiring in `src/app/main.py`: start the flusher task in `_lifespan`, cancel + await it on shutdown (satisfies **AC-4**).
7. Query API: `src/app/api/v1/metrics.py` with `GET /api/v1/metrics/query`, pydantic request + response models, label filtering via `labels @> :filter`, percentile computation helper, `X-API-Key` dependency (satisfies **AC-6**, **AC-10**).
8. Admin SPA: add `recharts` dep via `pnpm add recharts`; create `src/routes/metrics.tsx` with a `/metrics` TanStack Router route; render only the Request-latency panel for M1 (line chart of requests/min + p50/p95), using `openapi-fetch` + TanStack Query (satisfies **AC-7** partial, **AC-10**).

**Slice M2: Widen to extraction + execution.**

9. Replace the four debug `_metrics_log.debug(...)` calls in `src/app/core/observability/metrics.py` with real `prometheus-client` observations against the shared registry; keep the public helper function signatures stable so call sites in `ExecutionService` and `ExtractionService` don't change (satisfies **AC-1 execution/extraction**, **AC-2 execution/extraction**).
10. Add the remaining three Recharts panels to `/metrics` (HTTP error rate stacked area, Extraction stacked bar + line, Executions line); add the toolbar skeleton (window selector fixed at `1h` for the MVP, workflow filter input) (satisfies **AC-7**).

**Slice M3: Operational hardening.**

11. Flusher failure safety: wrap the DB write in a try/except, keep the un-flushed snapshot in memory up to `METRICS_BUFFER_CAP_MINUTES`, drop the oldest minute on overflow with one `metrics.buffer_overflow` event per episode (satisfies **AC-5**).
12. Retention task: a second asyncio task on a daily cadence running `DELETE FROM metric_minute WHERE bucket_start < NOW() - make_interval(days => :days)` (satisfies **AC-4**).
13. Self-observability events: emit `metrics.flush_completed`, `metrics.flush_failed`, `metrics.buffer_overflow` with the fields in AC-11; extend spec 0011's canonical catalogue with the three new rows (satisfies **AC-11**).
14. Dashboard empty-state wiring: each panel checks `series.length === 0` (or every series' points sum to zero) and renders the `"No data in the last hour"` placeholder (satisfies **AC-8**).

**Slice M4: Deep link.**

15. Dashboard URL state: the `/metrics` route reads `workflow_id` via `useSearch()`, applies it to the execution + extraction query clients, and surfaces the active filter in the toolbar with a clear-filter button (satisfies **AC-9**).
16. Run-detail link: in the execution-detail page (spec 0010), add a `"View metrics"` link to `/metrics?workflow_id=<the row's workflow_id>` (satisfies **AC-9**).

Backend tests ride each slice (per the project `Beta` tier: `/develop` → `/check verify` → `/test`). The `caplog_structlog` fixture from spec 0011 covers the self-observability events in M3; respx + testcontainers Postgres cover M1 and M2; dashboard tests (vitest + Playwright per spec 0010 conventions) cover M2/M3/M4.

## Consequences

**Positive**:
- One place to see system health in the admin UI, no external Prometheus/Grafana stack to run.
- Postgres is already the primary store, no new infrastructure.
- `prometheus-client` keeps the door open to a `/metrics` scrape endpoint later with zero re-instrumentation (feature 23 workers inherit the same registry pattern once they land).
- Dashboard panels are typed end-to-end: the FastAPI OpenAPI feeds `openapi-fetch`, which feeds TanStack Query, which feeds Recharts.
- Pre-aggregated bucket rows stay bounded in size: ~24h × 60 × (metric families × avg label combinations) is well under a million rows for the MVP scale.

**Negative / tradeoffs**:
- Six-bin histograms give approximate percentiles. For a load test at the 99.9th percentile the number is a sketch, not a true value. Operators can tune the bins if traffic skews outside the default ranges.
- The flusher is per-process. On a horizontally scaled deployment every worker upserts into the same rows; the sum semantics make this correct but concurrent upserts can produce brief write amplification.
- A worker crash during a Postgres outage loses whatever is in that worker's in-memory delta buffer AND resets its last-seen counter snapshot, so the next flush after restart sees a cold registry and attributes nothing to the gap. Acceptable at MVP; a fleet needing durable per-worker state is a feature-23 concern.
- The retention task is a plain asyncio tick, not a durable scheduler. Fine for a single-process deployment, less so for a fleet; feature 23 (job queue) will take over the schedule when it lands.
- `METRICS_BUFFER_CAP_MINUTES` is a lossy ceiling: a Postgres outage longer than the cap drops data. The cap is tunable but the loss is real.
- One new npm dep (`recharts`), one new Python dep (`prometheus-client`). Both widely used and small; worth the budget.

**Neutral**:
- `metric_minute` is a new table; add it to `tests/conftest.py` `Base.metadata` imports so test fixtures `create_all` it (per the project pattern already used by executions/websites).
- The flusher task adds a lifespan concern alongside the httpx client; `/check verify` and `/test` of future features should assert both are cleaned up.
- Four new log event names enter the project vocabulary; spec 0011's catalogue must be amended in the same build (handled by task 13).

## Follow-up

- [ ] Add `metrics.flush_completed`, `metrics.flush_failed`, `metrics.buffer_overflow` to spec 0011's canonical event catalogue when the self-observability task lands (M3, task 13); this is a surgical spec edit, not a new spec.
- [ ] Rename the pre-existing DEBUG `metrics.observe_duration` and `metrics.increment_items` log events in `app/core/observability/metrics.py` to catalogue-allowed domains before M2 ships (spec 0011 heads-up carried over from `/test`). Candidates: `extraction.duration_observed`, `extraction.items_counted`, `execution.duration_observed`, `execution.counted`; or drop them entirely once real prometheus-client instruments replace them.
- [ ] Expose a Prometheus text-format scrape endpoint at `GET /metrics` once operators ask for it; the in-process registry is already there, the endpoint is ~10 lines. Decide auth (admin key vs CIDR allowlist) at that point.
- [ ] When feature 23 (job queue + workers) ships, move retention to the queue and point the flusher at the worker-process registry too (so job runtimes count as execution duration).
- [ ] If 1h/1m resolution is not enough, add `5m` and `1h` bucket roll-ups in a second table and let the query API pick the right one per `(from, to, bucket)` combo.
- [ ] Consider a client-side auto-refresh on the dashboard (every 30 s, pause-on-hidden) once the first operators dog-food it; held out of the MVP to keep the first slice tight.
