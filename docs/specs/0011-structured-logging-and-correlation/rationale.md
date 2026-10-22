# 0011 — Rationale

## Context

Spec 0001 chose `structlog` + `asgi-correlation-id` + JSON logs in deployed envs and spelled out that `X-Request-ID` is bound to structlog contextvars. The platform has already been living on that stack: `src/app/core/logging.py` configures the processor chain and the stdlib bridge; `src/app/main.py` installs `CorrelationIdMiddleware` and a `RequestLogMiddleware`; `src/app/domains/{executions,extraction}/service.py` emit domain events via `structlog.get_logger(...)`.

What was missing was a shared, enforced *standard*: event names drift (`startup` vs `app.startup_completed` vs `execution.completed`), required fields are a convention rather than a contract, redaction only covers HTTP headers, per-module log levels are not operator-tunable, there is no catalogue of what the platform emits, and `ExecutionService.execute` passes `execution_id` as a kwarg on every call site rather than binding it once.

Feature 23 (job queue & worker pool) is deferred. The scope row for feature 12 reads "JSON logs across the API, workers, and extractors", but there are no workers yet. The engineer confirmed the spec should define the contract now and let feature 23 inherit it, rather than scaffold a worker runtime here.

## Options considered

### Event-name convention

- `<domain>.<action>_<outcome>` — chosen. Matches the dominant shape in `extraction/service.py` and `executions/service.py`. Reads naturally; filter-by-prefix in a log tool is trivial (`event:execution.*`); every event is grep-friendly.
- `<domain>.<action>` + separate `outcome` field — fewer unique event names, better for dashboards that group by event name alone. Rejected: breaks the existing pattern, forces every emitter to add `outcome=`, and the aggregation benefit is small when `execution.completed` / `execution.failed` are already distinct values operators scan for.
- Free-form sentence event — most readable in a terminal, worst for structured queries. Rejected on sight for a JSON pipeline.

### Required fields

- `event` + `logger` + `timestamp` + `level` + `correlation_id` — chosen. Minimum viable baseline. Everything else is per-event optional. Keeps event JSON small (bytes matter at request volume) while guaranteeing a line can always be grouped by `correlation_id` and a logger.
- Baseline + always-bind `environment` + `service` + `git_sha` — attractive when logs ship to a shared aggregator. Rejected for now because nothing in the current deployment story (there is no cloud deploy spec yet; feature 29 is deferred) requires self-identifying lines. Easy to add later via a single `logger.bind` on startup.
- Baseline + split `request_id` / `correlation_id` — useful when one request fans into several async executions. Rejected because today the two are the same (one sync execution per request); introducing two concepts up front invites inconsistency. Feature 23 can promote one of them if async changes the shape.

### Correlation propagation into executions

- Execution adopts the request's `correlation_id`, binds its own `execution_id` separately — chosen. One correlation ID ties request → execution → extraction into a single trace in the logs, matching the scope row's "every API request and execution emits start/complete/error log events sharing a correlation id". The `execution_id` is first-class as a structured filter, not overloaded onto `correlation_id`.
- Execution mints a fresh `correlation_id`, logs a `parent_correlation_id` — correct for an async world where executions outlive their triggering request. Rejected for the sync path we have today; it splits what should be one trace. When feature 23 lands async execution, the worker spec can revisit (the natural answer there is still "the enqueued job carries the originating correlation_id").
- Correlation_id = execution_id inside an execution — simple, loses the pre-execution request phase (validation 4xx that never produces an execution still deserves a correlation).

### Per-module log levels

- `LOG_LEVEL` baseline + `LOG_LEVELS` JSON env override — chosen. One extra env var, zero new files, pydantic-settings parses and validates it. Honours the scope-row promise ("log levels are configurable per module") without a config-file surface.
- Global `LOG_LEVEL` only — simplest; drops the per-module promise. The platform already has domains with meaningfully different noise profiles (`sqlalchemy.engine` floods at DEBUG, `app.extraction` is useful at DEBUG when diagnosing a selector problem). Operator ergonomics win.
- `logging.config.dictConfig` YAML file — flexible, overkill for the roughly ten loggers the platform has. Rejected for being more surface than the project needs now.

### Redaction

- Headers (status quo) + `SENSITIVE_LOG_KEYS` processor on every event — chosen. The processor catches the "I added `password=` as a kwarg and forgot" case for free; the header pathway stays authoritative for middleware. Low cost (one dict walk per event), high safety.
- Headers only — kept open the "careless kwarg" leak path. Not worth the risk when the fix is 15 lines.
- Full-value regex scrubber — catches novel key names but has false positives (a product SKU resembling a token, a long base64 field). Reserved for a future hardening spec if an incident makes the case.

### Event vocabulary

- Enumerate a canonical catalogue in the spec — chosen. The catalogue is the contract; a new event is a documented change, not an ad-hoc coinage. The platform has about a dozen events; the list is small enough to maintain by hand.
- Pattern only, free coinage — cheapest, drifts fastest. The platform already drifted in a year with three contributors; it will drift faster with more.
- Enumerate + Python `Enum` registry — compile-time safety. Rejected because every new event becomes an import + enum entry + call-site change; the friction is wrong when the event name is right there as a string in the call. The catalogue in the spec is the enforcement; `/check verify` can grep it.

### Test strategy

- `caplog_structlog` fixture over `structlog.testing.capture_logs()` — chosen. 15 lines of fixture code, lets a test assert `events[0]["event"] == "execution.completed"` and that `correlation_id` matches the request's. No tool to adopt; structlog ships the primitive.
- stdlib `caplog` — awkward because structlog's `event` key becomes the message string; nested fields are lost.
- No log assertions — too permissive. A regression that drops `correlation_id` on `execution.failed` ships silently; the whole point of this spec is defending that invariant.

### Logging failure safety

- Swallow + emit `log.emission_failed` — chosen. A `Decimal` kwarg or a broken sink never crashes a business request. The meta-event tells operators instrumentation is broken.
- Propagate — fails loud; also crashes the request/execution the log was describing. Wrong trade for an observability concern.
- Swallow silently — hides broken instrumentation indefinitely.

### Bodies in logs

- Never — chosen. Problem Details on the HTTP response carries detail for the client; `correlation_id` ties the response back to the log line. Avoids PII in product/website data and avoids the DEBUG-left-on-in-prod leak path.
- DEBUG only — convenient for incident response, dangerous when a DEBUG override gets forgotten.
- 4xx/5xx only — easier post-mortems, still leaks credentials on auth-endpoint failures.

### Access-log policy

- Keep status quo: `uvicorn.access` silenced, `RequestLogMiddleware` emits `request.completed` — chosen. One structured line per request with `correlation_id` + `duration_ms` + redacted headers beats the unstructured uvicorn line, and avoids doubles.

### Apply scope

- Audit + conform every existing call site — chosen. Small diff (three files), zero drift the day the spec lands. Any later touch of these files inherits conformance without extra thought.
- Standard + helpers only, lazy conformance — keeps the drift the spec exists to fix.
- Also instrument silent paths — scope creep for a Slice 3 feature; punted to Follow-up.

## Rationale

The dominant judgment call is: the stack is already settled, so the spec's job is to turn implicit conventions into an enforced contract. Every chosen option favours "contract that catches the easy mistake" over "powerful machinery": the sensitive-key processor over caller discipline, the catalogue over free coinage, the `caplog_structlog` fixture over trust that developers will test logs. The contract is intentionally tight (five required fields, allowed domain prefixes, enumerated events) because the whole point is to stop drift; the extension points (new domains and events via spec update, new optional fields free to add) stay open so the tightness never blocks a legitimate addition.

The one place the spec declines ambition is workers. Feature 23 is deferred, there is no runtime to instrument, and inventing a background-task helper here would commit to a propagation mechanism before a queue is chosen. The spec gives feature 23 a normative rule ("bind `correlation_id` + `execution_id` via `contextvars` before running the job") and leaves the implementation open.

## References

None by choice (engineer picked `No references, keep it clean`). The reasoning above cites spec 0001 (stack), spec 0008 (admin UI, header deny list in `redact_headers`), and the current call sites in `src/app/`.
