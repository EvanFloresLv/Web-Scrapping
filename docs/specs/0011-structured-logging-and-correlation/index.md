# 0011 — Structured logging & correlation

**Status**: Accepted
**Date**: 2026-10-22
**Mode**: CROSS-CUTTING
**Scope feature**: 12 (Slice 3: Observability)
**Builds on**: [0001 Stack & architecture](../0001-stack-and-architecture/index.md), [0008 Admin UI foundation](../0008-admin-ui-foundation/index.md)
**Rationale**: see [rationale.md](./rationale.md)

## Summary

Define the project-wide structured logging contract on the stack already chosen in spec 0001 (`structlog` + `asgi-correlation-id`), and conform every existing log call site to it. Every event the platform emits must share one event-name shape, carry a minimum set of fields (including `correlation_id`), redact a known set of sensitive keys, and participate in a canonical catalogue listed in this spec. One correlation ID ties an HTTP request through its execution and extraction children; `execution_id` is a separate structured field. Per-module log levels become operator-tunable via a JSON env override. Future worker surfaces (feature 23) inherit the same contract; no worker runtime is added here.

## Context

- Spec 0001 already selected `structlog` + `asgi-correlation-id` and `src/app/core/logging.py` configures both. `src/app/main.py` installs `CorrelationIdMiddleware` and a `RequestLogMiddleware` that emits `request.completed`. `uvicorn.access` is silenced to avoid a duplicate line.
- Current call sites (`main.py`, `domains/extraction/service.py`, `domains/executions/service.py`) emit events in mixed shapes: `extraction.fetch_started`, `execution.completed`, bare `startup`/`shutdown`. The event-name convention is mostly `<domain>.<action>_<outcome>` but not enforced.
- Redaction today covers two HTTP headers (`x-api-key`, `authorization`) via `redact_headers`. Nothing protects a careless `logger.info("api_key.created", key=raw_key)`.
- The sync execution path binds no `execution_id` on its logger; `_log.info("execution.completed", **log_payload)` passes it as a kwarg each time.
- Feature 23 (job queue & worker pool) is deferred. The contract defined here must be propagation-ready so a future worker can bind `correlation_id` + `execution_id` in `contextvars` and inherit every rule.

## Requirements

Acceptance criteria the build plan satisfies and `/check verify` checks.

- **AC-1 Event naming**: every log event the platform emits uses the shape `<domain>.<action>_<outcome>` (lowercase, dot-separated domain, snake_case action and outcome). Allowed domains: `app`, `request`, `execution`, `extraction`, `workflow`, `website`, `log`.
- **AC-2 Required fields**: every rendered event JSON carries `event`, `logger`, `timestamp` (ISO-8601, UTC, trailing `Z`), `level`, and `correlation_id` (the sentinel `"-"` when no request/execution context is bound). Any other field is per-event optional.
- **AC-3 Correlation propagation (request)**: the HTTP `CorrelationIdMiddleware` binds `correlation_id` into structlog `contextvars`; every log line emitted while handling a request carries that id. `X-Request-ID` on the response matches it. (Already in place; AC asserts it remains true after the apply pass.)
- **AC-4 Correlation propagation (execution)**: `ExecutionService.execute` keeps its explicit `correlation_id: str` parameter (callers in the API layer already have it from middleware) and, inside the method body, wraps the work in `structlog.contextvars.bound_contextvars(correlation_id=correlation_id, execution_id=str(execution.id))` so every event emitted (including nested extraction events and any `asyncio.create_task` spawned inside) carries both fields automatically. The per-call `correlation_id=` and `execution_id=` kwargs on existing `_log.info(...)` sites are removed (now auto-bound). A programmatic caller that passes no `correlation_id` (future worker surface) receives a freshly minted UUID4 bound for the method duration; today's HTTP callers always pass one.
- **AC-5 Per-module levels**: operators can set `LOG_LEVEL` (baseline) and `LOG_LEVELS` (JSON map, e.g. `{"app.extraction": "DEBUG", "sqlalchemy.engine": "WARNING"}`). On startup both the structlog filtering wrapper and the matching stdlib loggers honour the overrides. Invalid JSON or an unknown level fails startup with a clear message (per spec 0001's "validate at startup, fail fast").
- **AC-6 Sensitive-key redaction**: a structlog processor replaces the value of any key in `SENSITIVE_LOG_KEYS = {"api_key", "authorization", "password", "token", "cookie", "set-cookie", "x-api-key"}` with `"<redacted>"` on every event, recursive into nested dicts one level deep. The existing header redaction keeps working for the request middleware.
- **AC-7 No body logging**: neither request nor response bodies appear in log output on any path, including error paths. Problem Details on the HTTP response carry the detail the client needs; `correlation_id` ties the response back to the log line.
- **AC-8 Access-log policy**: `uvicorn.access` stays at `WARNING`; the `request.completed` event emitted by `RequestLogMiddleware` is the per-request record. No duplicate lines.
- **AC-9 Canonical catalogue**: every event the platform emits today appears in the catalogue in [Standard definition § Canonical event catalogue](#canonical-event-catalogue). A new event introduced by a later feature arrives with a spec update adding it (or supersedes this spec).
- **AC-10 Logging failure safety**: if a log emission raises (non-serialisable kwarg, broken sink), the final renderer wraps the call in a last-resort handler that writes a single `log.emission_failed` event to `stderr` with `error_type` + `error_msg` and returns normally; business code never crashes because of a log call.
- **AC-11 Test ergonomics**: a pytest fixture `caplog_structlog` captures emitted events as a list of dicts (via `structlog.testing.capture_logs()`). Tests use it to assert event name, correlation_id, and required fields on at least one happy and one error path per domain (`request`, `execution`, `extraction`). Note: `capture_logs()` captures the pre-processor event dict, so redaction tests (AC-6) cannot use this fixture; those write to a `StringIO` sink via a dedicated test configuration and assert the rendered JSON contains `"<redacted>"`.
- **AC-12 Apply pass**: `main.py`, `extraction/service.py`, and `executions/service.py` are updated so every event they emit matches AC-1 and binds `execution_id` via `contextvars` (where applicable) rather than passing it as a kwarg per call. Bare events `startup`/`shutdown` become `app.startup_completed`/`app.shutdown_started`.

## Decision

**Choices (one line each):**

- Event-name convention: `<domain>.<action>_<outcome>`.
- Required-fields contract: `event` + `logger` + `timestamp` + `level` + `correlation_id`.
- Execution correlation: adopt request's `correlation_id`; bind `execution_id` as a separate contextvar.
- Per-module levels: single `LOG_LEVEL` env + optional `LOG_LEVELS` JSON map.
- Redaction: header deny-list (kept) + `SENSITIVE_LOG_KEYS` processor on every event.
- Event vocabulary: enumerated catalogue in this spec (no Enum registry; the catalogue is the contract).
- Test strategy: `caplog_structlog` fixture over `structlog.testing.capture_logs()`.
- Logging-failure mode: swallow + emit `log.emission_failed` from a wrapping processor.
- Bodies: never logged.
- Access log: `uvicorn.access` silenced; `request.completed` is authoritative.
- Apply scope: audit + conform every existing call site, do not add instrumentation to currently-silent paths (deferred to Follow-up).
- Workers: contract-only; no runner (feature 23 inherits).

**Implementation skills:** `python-testing-patterns` (for the `caplog_structlog` fixture shape), `fastapi` (for the middleware wiring).

## Standard definition

### Event name shape

```
<domain>.<action>_<outcome>
```

Lowercase, dot between domain and action, snake_case action and outcome. One domain prefix per event. Allowed domains: `app` (lifespan + top-level), `request` (HTTP middleware), `execution` (execution service), `extraction` (extraction pipeline), `workflow` (workflow CRUD), `website` (website CRUD), `log` (self-emitted meta-events like `log.emission_failed`). A new domain requires a spec update.

### Required fields on every event

| Field | Source | Example |
|---|---|---|
| `event` | caller | `"execution.completed"` |
| `logger` | `structlog.get_logger(name)` | `"app.executions"` |
| `timestamp` | `TimeStamper(fmt="iso", utc=True)` | `"2026-10-22T14:03:11.482Z"` |
| `level` | `add_log_level` processor | `"info"` |
| `correlation_id` | `contextvars` (middleware or `.execute`) | `"3f1b…"` or `"-"` |

### Per-event optional fields (bind via `logger.bind()` or kwargs)

`execution_id`, `workflow_id`, `workflow_version_id`, `target_url_id`, `website_id`, `method`, `path`, `status`, `duration_ms`, `items_extracted`, `error_code`, `error_type`, `error_msg`. Add new optional fields freely; register new domain prefixes via spec update.

### Correlation propagation rules

- **HTTP boundary**: `asgi-correlation-id` reads an incoming `X-Request-ID` header (or mints a UUID4), writes it to the response, and `CorrelationIdMiddleware` binds it to structlog `contextvars`.
- **Execution boundary**: `ExecutionService.execute(…)` wraps its body in `with structlog.contextvars.bound_contextvars(execution_id=str(execution.id)):`. The call also reads the current `correlation_id` from `contextvars`; if absent (programmatic caller with no request), it mints a fresh UUID4 and binds it for the duration of the call. The persisted `executions.correlation_id` column uses the same value.
- **Future worker boundary (feature 23, not built here)**: a worker runner MUST read the job's persisted `correlation_id` + `execution_id`, bind both via `structlog.contextvars.bind_contextvars`, and unbind on exit. This spec provides no runner; the rule is normative.

### Per-module level configuration

- `LOG_LEVEL` (existing): the baseline level for structlog's filtering wrapper and the root stdlib logger. Default `INFO`.
- `LOG_LEVELS` (new): a JSON object mapping logger name → level. Validated at startup via pydantic-settings; empty string / missing env means "no overrides". Example: `LOG_LEVELS={"app.extraction":"DEBUG","sqlalchemy.engine":"WARNING","httpx":"WARNING"}`. Applied once in `configure_logging` after the baseline is set. Unknown level → startup error; malformed JSON → startup error.

### Redaction

- `SENSITIVE_LOG_KEYS: frozenset[str] = {"api_key", "authorization", "password", "token", "cookie", "set-cookie", "x-api-key"}`.
- A new structlog processor `redact_sensitive_keys` sits in `shared_processors` before the renderer. For each key in the event dict (and one level into nested dicts, to catch `headers={...}`), if the lowercased key is in the set, the value becomes `"<redacted>"`.
- The existing `redact_headers` helper and `SENSITIVE_REQUEST_HEADERS` stay; the processor is a defence in depth, not a replacement.
- **Processor chain order (pinned)**: `merge_contextvars → TimeStamper → add_log_level → StackInfoRenderer → format_exc_info → redact_sensitive_keys → safe_render(renderer)`. `redact_sensitive_keys` must run AFTER `merge_contextvars` so contextvar-bound secrets are redacted too, and BEFORE the renderer so JSON only ever sees `"<redacted>"`. `safe_render` wraps the renderer and therefore runs last.

### Logging failure safety

A `safe_render` wrapper around the final renderer catches any exception and writes a last-resort line to `stderr`:

```json
{"event":"log.emission_failed","logger":"app.core.logging","timestamp":"…","level":"error","correlation_id":"-","error_type":"TypeError","error_msg":"Object of type Decimal is not JSON serializable"}
```

Then returns normally so the caller continues.

### Canonical event catalogue

Every event the platform emits today. Each row names the emitter and the typical bound/kwarg fields beyond the required baseline.

| Event | Emitter | Fields beyond baseline |
|---|---|---|
| `app.startup_completed` | `app/main.py` lifespan | `app`, `env`, `alembic_head`, `db_connect_ms` |
| `app.shutdown_started` | `app/main.py` lifespan | — |
| `request.completed` | `RequestLogMiddleware` | `method`, `path`, `status`, `duration_ms`, `headers` (redacted) |
| `execution.started` | `ExecutionService.execute` | `execution_id`, `workflow_id`, `workflow_version_id`, `target_url_id` |
| `execution.completed` | `ExecutionService.execute` | `execution_id`, `duration_ms`, `items_extracted` |
| `execution.failed` | `ExecutionService.execute` | `execution_id`, `duration_ms`, `error_code`, `error_type`, `error_msg` |
| `execution.terminal_persist_failed` | `ExecutionService.execute` rollback path | `execution_id`, `workflow_id`, `workflow_version_id`, `error_type`, `error_msg` |
| `extraction.fetch_started` | `ExtractionService.run` | `url`, `method` |
| `extraction.fetch_completed` | `ExtractionService.run` | `url`, `status`, `duration_ms`, `content_type` |
| `extraction.parse_completed` | `ExtractionService.run` | `duration_ms`, `root_count` |
| `extraction.extract_completed` | `ExtractionService.run` | `duration_ms`, `items_extracted` |
| `extraction.validate_completed` | `ExtractionService.run` | `duration_ms`, `valid` |
| `extraction.item_extracted` | `ExtractionService.run` (DEBUG) | `item_index`, `field_count` |
| `extraction.failed` | `ExtractionService._fail` | `duration_ms`, `error_code`, `error_type`, `error_msg` |
| `metrics.flush_completed` | `MetricsFlusher._tick` | `rows_written`, `duration_ms` |
| `metrics.flush_failed` | `MetricsFlusher._tick` on DB error | `error_type`, `error_msg`, `pending_minutes`, `duration_ms` |
| `metrics.buffer_overflow` | `MetricsFlusher._buffer_rows` on cap trip | `dropped_minutes` |
| `metrics.retention_completed` | `MetricsRetention._sweep` | `rows_deleted`, `cutoff`, `duration_ms` |
| `metrics.retention_failed` | `MetricsRetention._run` on DB error | `error_type`, `error_msg` |
| `log.emission_failed` | `safe_render` fallback | `error_type`, `error_msg` |

A new event emitted by a later feature slice MUST land in this catalogue via a spec update (either amending 0011 or a spec that supersedes it in part).

## Build plan

One Skateboard slice. Each task names the ACs it satisfies.

1. **Config surface**: add `LOG_LEVELS: dict[str, str] = {}` to `Settings` (parsed from JSON env), with pydantic validator that rejects unknown levels. (AC-5)
2. **Processor set**: in `src/app/core/logging.py` add `redact_sensitive_keys` (processor) and `safe_render` (final-renderer wrapper); extend `SENSITIVE_LOG_KEYS`. Wire into `shared_processors` and the renderer position. (AC-6, AC-10)
3. **Per-module levels wiring**: in `configure_logging`, after setting the baseline wrapper, iterate `settings.log_levels` and apply each to the corresponding stdlib logger; the structlog filtering wrapper stays at the baseline (per-logger filtering is already done by stdlib bridging). (AC-5)
4. **Required-fields enforcement**: ensure `correlation_id` always renders; add a tiny processor that sets `correlation_id = "-"` when the contextvar is unbound (prevents the `logger` field missing when nothing is bound). (AC-2)
5. **Execution contextvar binding**: in `ExecutionService.execute`, wrap the method body in `structlog.contextvars.bound_contextvars(execution_id=...)`; read `correlation_id` from contextvars at entry, mint a UUID4 if unbound and bind it. Remove per-call `execution_id` kwargs from the events (now auto-bound). (AC-4, AC-12)
6. **Rename bare events**: `main.py` lifespan — `startup` → `app.startup_completed`, `shutdown` → `app.shutdown_started`. (AC-1, AC-12)
7. **Catalogue conformance audit**: diff each event in `main.py`, `extraction/service.py`, `executions/service.py` against the canonical catalogue; rename or add missing kwargs to match. If the catalogue and the code disagree on a name, the catalogue wins (rename the code). If a real event is missing from the catalogue, extend the catalogue via a spec edit before touching the code. (AC-1, AC-9, AC-12)
8. **Test fixture**: add `caplog_structlog` fixture to `tests/conftest.py` yielding a `list[dict[str, Any]]` captured via `structlog.testing.capture_logs()`. (AC-11)
9. **Test coverage**: add tests asserting `request.completed`, `execution.started`/`.completed`/`.failed`, and one extraction event each carry the required fields and that `execution.*` events share the request's `correlation_id`. (AC-3, AC-4, AC-11)
10. **No-body check**: a targeted test that a POST with a body logs `request.completed` with no `body` or `payload` kwarg. (AC-7)
11. **Access-log check**: a test that a successful request yields exactly one `request.completed` event and zero `uvicorn.access` records at INFO. (AC-8)
12. **Documentation**: update root `AGENTS.md` logging section (via `/sync` after the build) to reference this spec as the authoritative standard.

## Rollout

Single Skateboard slice: the Build plan above IS the rollout. No feature flag, no staged migration, no backfill. The processor + config changes land first (steps 1–4), then the call-site conformance pass (steps 5–7), then the tests (steps 8–11). Each change is backwards compatible with existing log consumers (same JSON shape, strictly more fields and strictly tighter redaction).

## Exceptions

None at this time. Every domain module uses the standard. If a future need appears (e.g. a dedicated audit-log stream with its own schema), it supersedes this spec in part rather than opting out.

## Consequences

- Every domain module that logs now reads from a shared catalogue; drift becomes a spec change, not a one-off.
- Operators can tune verbosity per module without a redeploy of logging config.
- A careless `logger.info("…", password=…)` is now redacted automatically; writing `password=` by accident costs nothing beyond a `<redacted>` in logs.
- The `ExecutionService.execute` method gains a `contextvars` wrapper. Any code that reads `structlog.contextvars.get_contextvars()` mid-execution will now see `execution_id`.
- Future worker surfaces (feature 23) inherit the contract; the spec there only needs to say "bind correlation_id + execution_id before running the job" and pick a propagation mechanism.
- Adding a new log event requires a spec update to add it to the catalogue. Low friction; keeps drift out.

## Follow-up

- Instrument currently-silent paths (repository errors, route handler entry/exit) in a later slice if operational need surfaces. Not in this spec's scope.
- When feature 23 (job queue) lands, add a worker-propagation spec that references this one and names the mechanism (likely a decorator over the job entry point).
- When feature 13 (metrics) lands, align its event vocabulary with this catalogue so a log event and a metric increment share the same label set.
- Consider a lightweight CI check that greps for `logger.(info|warning|error|debug)\(["']\w+["']` and verifies the event appears in the catalogue; cheap, catches drift. Defer until drift is observed.
