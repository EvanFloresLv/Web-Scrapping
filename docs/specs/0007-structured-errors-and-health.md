# 0007. Unified structured error contract and operator health endpoints

**Date**: 2026-10-20
**Status**: Accepted

## Summary

This spec locks in one error contract across the whole API and finishes the health probes. Every error path returns RFC 7807 Problem Details (`application/problem+json`) with a dotted, domain prefixed `code`, a shared `errors[]` list for per field detail, and the request's `correlation_id`. The error code registry becomes browsable at `GET /api/v1/_meta/error-codes`. `GET /health/live` stays a dumb process check; `GET /health/ready` returns 503 with Problem Details when a dependency fails, and runs three cheap checks: database `SELECT 1` with a timeout, Alembic head matches the deployed app, and startup finished.

## Context

The scaffold shipped in spec 0001 (`Problem` model, five FastAPI exception handlers, `application/problem+json`, `correlation_id` extension) and every feature since (0002, 0004, 0005, 0006) added its own `PlatformError` subclasses. The scaffold works, but five slices of independent authorship left the contract fragmented. The websites domain uses bare slugs (`duplicate_website`, `host_mismatch`, `invalid_pagination`); workflows, extraction, and executions use dotted prefixes (`workflow.name_conflict`, `execution.not_found`). The `WorkflowErrorCode` enum itself mixes both styles. The validation handler emits `errors: [{loc, msg, type}]`, while `WorkflowValidationError.details` is populated by callers but never read by any shared handler, so the structured field detail is silently dropped. There is no single catalogue of what codes the API can emit.

`/health/live` and `/health/ready` exist (`src/app/api/v1/health.py`), but readiness returns HTTP 200 with `status: "degraded"` when the DB is unreachable. Kubernetes, ECS, and load balancers interpret 200 as "take traffic", so a database outage keeps the pod in rotation. The probe also checks only the DB; a deploy that ran the app ahead of its migrations, or a process that failed to finish startup, both read as ready today.

Feature 8 is Slice 1 MVP work: it is called "structured errors & health endpoints" in the scope because its job is to consolidate what the other MVP features put down piecemeal, fill the two readiness gaps, and publish the contract so later features (admin UI, metrics, logging) can lean on it without re inventing the shape.

## Requirements

**User stories**:
- As an API consumer, I want every error response to use the same body shape and a stable, documented `code` so that I can switch on failures without parsing prose.
- As an operator running the platform in Kubernetes or ECS, I want `/health/ready` to return 503 when a critical dependency fails so that my orchestrator removes the pod from traffic until it recovers.
- As the admin UI developer (feature 11), I want to fetch the error code registry at runtime so that I can render human readable messages for each code without hardcoding them.
- As an on call engineer, I want every error body to carry the request's `correlation_id` so that I can jump straight from a user bug report to the matching structlog line.

**Acceptance criteria** (every criterion is independently checkable):

- **AC-1**: Every error response the API returns uses `Content-Type: application/problem+json` and a body conforming to the `Problem` schema (`type`, `title`, `status`, `detail?`, `instance?`, `code?`, `correlation_id?`, `errors?`). The five shared handlers (`PlatformError`, `StarletteHTTPException`, `HTTPException`, `RequestValidationError`, `Exception`) all go through one response builder.
- **AC-2**: Every `code` emitted by the API matches `^[a-z][a-z0-9_]*\.[a-z0-9_.]+$` (lowercase, domain prefix, dot separators). The reserved prefixes are `website`, `workflow`, `execution`, `extraction`, `fetch`, `agent`, `platform`, `http`, `health`.
- **AC-3**: Structured per field details use a single shared list under the response key `errors`, where each entry has `{code: str, loc: list[str|int], message: str, meta?: dict}`. The validation handler (`RequestValidationError`) populates it from Pydantic's output; any `PlatformError` subclass that sets `self.errors` has those entries copied onto the response verbatim.
- **AC-4**: Every error body carries `correlation_id` populated from `asgi_correlation_id.correlation_id.get()`. When the context is unset the key is omitted (never `null`, never the string `"None"`).
- **AC-5**: The websites domain emits only dotted codes (`website.duplicate`, `website.target_duplicate`, `website.host_mismatch`, `website.inactive`, `website.immutable_field`, `website.invalid_pagination`, `website.not_found`, `website.target_not_found`, `website.validation_error`). The old bare codes (`duplicate_website`, `host_mismatch`, `website_inactive`, `immutable_field`, `invalid_pagination`, `duplicate_target`) are not emitted anywhere.
- **AC-6**: `WorkflowErrorCode.WEBSITE_NOT_FOUND`, `WORKFLOW_NOT_FOUND`, `VERSION_NOT_FOUND` emit the dotted values `website.not_found`, `workflow.not_found`, `workflow.version_not_found` (not the current bare `website_not_found`, `workflow_not_found`, `version_not_found`).
- **AC-7**: `GET /health/live` returns `200` with body `{"status": "ok"}` as long as the ASGI process is handling requests. It performs no I/O.
- **AC-8**: `GET /health/ready` returns `200` with body `{"status": "ok", "checks": {"database": "ok", "alembic": "ok", "startup": "ok"}}` when every check passes.
- **AC-9**: `GET /health/ready` returns `503` with `application/problem+json` and body `{type: "about:blank", title: "Service Not Ready", status: 503, code: "health.not_ready", detail, correlation_id?, checks: {database: "ok"|"fail", alembic: "ok"|"fail"|"mismatch", startup: "ok"|"fail"}}` when any check fails. The failing check's status is `fail` (or `mismatch` for an Alembic head drift); the `detail` string names which check failed. The `checks` key is carried as a first class field on the shared `Problem` model (not an untyped extension) so the shared response builder stays the only constructor.
- **AC-10**: Each readiness check honours `settings.health_ready_check_timeout_s` (default `1.0`). A check that exceeds the timeout is counted as `fail` with `detail` naming the timeout.
- **AC-11**: The Alembic head check compares the head cached from `alembic/script.py` at app startup against the single row in the `alembic_version` table. A missing row, no row, or any mismatch counts as `mismatch`. The expected head is resolved once at process start, not re read per request.
- **AC-12**: The startup check reports `ok` only after the FastAPI lifespan `startup` hook has finished. Before that it reports `fail` so a probe hitting the port before startup completes does not mark the instance ready.
- **AC-13**: `GET /api/v1/_meta/error-codes` returns `200` with `[{code: str, domain: str, http_status: int, title: str}]`, generated at startup from the error code enums (`FetchErrorCode`, `ExtractionErrorCode`, `ExecutionErrorCode`, `WorkflowErrorCode`, `AgentErrorCode`) and the registered `PlatformError` subclasses. The list is sorted by `code`.
- **AC-14**: `/health/live`, `/health/ready`, and `/api/v1/_meta/error-codes` are reachable without authentication. (No rate limit middleware exists today; when one lands in a later feature, these three endpoints are excluded. Captured in Follow-up.)
- **AC-15**: An unhandled `Exception` reaching the fallback handler emits code `platform.internal_error`, HTTP 500, body with no `detail` (the message is logged, not returned), and the request's `correlation_id`.

## Options considered

### Option 1: Fix in place; one shared response builder, dotted codes everywhere, three readiness checks

Reconcile the existing scaffold without new tech. Rename the websites domain codes to the dotted form, promote `errors[]` into the shared `Problem` model and the shared response builder (so a domain exception that sets `self.errors` renders it without any handler of its own), add two readiness checks beside the existing DB probe, and reflect the error enums into one `/api/v1/_meta/error-codes` endpoint. The platform is pre launch; nothing external depends on the bare `duplicate_website` style codes yet.

**Pros**:
- Keeps the existing `Problem` scaffold, the five handlers, and the per domain `PlatformError` subclasses. No new runtime dependency.
- Fixes every gap the scope row names with code the team already knows.
- Readiness checks stay cheap (`SELECT 1`, one metadata read, one boolean).
- Error registry comes "for free" by reflecting the already shipped enums.

**Cons**:
- Breaking rename of the websites bare codes; any client that pinned them has to update. (No client exists yet, so the risk is theoretical.)
- Readiness payload shape grows from `{status, database}` to `{status, checks: {database, alembic, startup}}`; anything already polling the flat shape would need to update too. (Only the probe itself exists today.)

### Option 2: Strangler; introduce a `v2` error contract behind a feature flag, deprecate `v1`

Keep the current contract live, publish the new one as a parallel body shape or at a `v2` prefix, run both, cut over per client. Give the websites domain time to emit both the old and the new code (via an `aliases` extension) for one release before dropping the old one.

**Pros**:
- Zero breakage for any client that already consumes the current shapes.
- Lets teams migrate on their own schedule.

**Cons**:
- The platform is pre launch; no "existing client" is paying for the extra machinery.
- Two code paths, two sets of handlers, two sets of tests, two things to document; the registry has to describe two shapes.
- The scope row explicitly asks for "a single error contract across the API", and this option fights that intent.

### Option 3: Replace directly; adopt a third party Problem Details library and a health framework

Pull in a library that renders Problem Details (there are several for FastAPI) and a health check framework (e.g. a dedicated `healthcheck` package). Delete the hand written response builder and the hand rolled `/health/*` router.

**Pros**:
- Less code to maintain in the project.
- Health frameworks ship ready made checks (DB, cache, queue).

**Cons**:
- The scaffold already fits in a single file; the library's abstractions would be larger than what they replace.
- Each library is one more thing to track for CVEs, API breakage, and typing fidelity against `mypy --strict`.
- The team ends up writing adapters anyway, because the per domain `PlatformError` subclasses do not match any library's base class.
- The scope row describes a very small surface (one shared schema, two probes, one registry endpoint); a framework is overkill.

## Decision

**Chosen option**: Option 1: Fix in place; one shared response builder, dotted codes everywhere, three readiness checks.

**Implementation skills**: `fastapi` (`fastapi/fastapi`, `.claude/skills/fastapi/`) · `sqlalchemy-alembic-expert-best-practices-code-review` (`wispbit-ai/skills`, `.claude/skills/sqlalchemy-alembic-expert-best-practices-code-review/`) · `python-testing-patterns` (`wshobson/agents`, `.claude/skills/python-testing-patterns/`)

## Rationale

The scaffold is not broken; it is fragmented, and three small design calls (naming rule, `errors[]` shape, 503 on failure) remove the fragmentation. The migration plan (below) is cheap because no client depends on the current shapes yet, which is the single biggest reason to do this rename now rather than later. Spec 0001 already locked Problem Details as the contract; replacing it with a library would churn the five handlers for marginal benefit, and introduce a dependency whose typing and release cadence the team does not control.

Three readiness checks beat one for a very specific reason: each catches a distinct outage class the team has already seen in production projects (DB unreachable, deployed app ahead of migrations, process booted but startup never finished). Each check is cheap, and the shared timeout keeps them from fighting a slow dependency. Doing all three now means feature 28 (CI/CD and container packaging) can wire the Dockerfile `HEALTHCHECK` and the Kubernetes probes to a single ready endpoint and trust it. Keeping `/health/live` dumb (zero I/O) means a wedged DB does not restart the pod, only de rotate it.

Reflecting the error code enums into `GET /api/v1/_meta/error-codes` turns the registry from a convention into an API. The admin UI (feature 11) can fetch it at build time, external clients can diff it against what they handle, and the test suite can assert that every subclass of `PlatformError` carries a code the registry recognises. The alternative (OpenAPI per endpoint `responses`) is correct and complementary, but it is not a single catalogue, and nothing stops a slice feature from adding a code the OpenAPI schema never mentions.

The `type` field stays `about:blank`. RFC 7807 permits it, the `code` field already identifies the class of problem, and a URL that encodes the deploy environment is one more thing to break at move time.

## Feature design

**Data model sketch**:
No new tables, no schema change. The feature reads `alembic_version` (already present, owned by Alembic) and the error enums (`src/app/core/errors/execution_codes.py`).

**State transitions**:
The startup check is the only state: `starting → ok`. The transition fires once per process, inside the FastAPI lifespan `startup` hook, after routers, DB engine, and settings have loaded. No transition back to `starting`.

**API surface**:

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/health/live` | GET | none | `{status: "ok"}` | none | never errors; always 200 unless the process is dead |
| `/health/ready` | GET | none | 200 `{status: "ok", checks: {...}}` or 503 `application/problem+json` with `code: "health.not_ready"` and `checks: {...}` | none | 503 on any check fail or timeout |
| `/api/v1/_meta/error-codes` | GET | none | `[{code, domain, http_status, title}]` sorted by `code` | none | none in v1 |

**Value sourcing**:

| Action | Value produced / displayed | Source |
|---|---|---|
| any error response | `Problem.correlation_id` | `asgi_correlation_id.correlation_id.get()`, bound by the ASGI middleware (already wired in `src/app/main.py`) |
| any error response | `Problem.type` | hardcoded `"about:blank"` in the response builder |
| any error response | `Problem.instance` | `str(request.url.path)` in the response builder (query string excluded) |
| any error response | `Problem.code` | the exception's `.code` attribute (`PlatformError` subclasses) or the derived code (`http.<status>` for `HTTPException`, `platform.internal_error` for unhandled) |
| any error response | `Problem.errors` | copied from `exc.errors` when present (`PlatformError` subclasses that set it, and the validation handler which builds entries from `RequestValidationError.errors()`). `WorkflowValidationError.details` (and any other subclass whose structured list lives under a different attribute today) is renamed to `self.errors` as part of Slice A so the shared builder reads a single attribute name |
| any error response | `Problem.checks` | passed through the shared response builder's `checks` parameter by the readiness handler; absent (and excluded) on every other error path |
| `/health/ready` 200 body | `checks.database` | `await session.execute(text("SELECT 1"))` wrapped in `asyncio.wait_for(..., timeout=settings.health_ready_check_timeout_s)`; "ok" when it returns, "fail" on any `Exception` or `TimeoutError` |
| `/health/ready` 200 body | `checks.alembic` | compare `MigrationContext.from_connection(...).get_current_revision()` against the module level cached head (populated at import time of `app.core.alembic_head` by loading `Config` from a package relative path to `alembic.ini` resolved as `Path(__file__).resolve().parents[3] / "alembic.ini"`, which is CWD independent and works under tests, containers, and `uv run`); "ok" when equal, "mismatch" when different, "fail" on any `Exception` or timeout. If the ini file cannot be read at import, `EXPECTED_HEAD` is set to `None` and the check reports `fail` with `detail` naming the ini path |
| `/health/ready` 200 body | `checks.startup` | read a module level `_startup_complete: bool` defined in a new `app.core.startup_state` module (not in `app.main`, to avoid a circular import from `app.api.v1.health` back onto the app factory), flipped true at the end of the existing `_lifespan` in `src/app/main.py` just before `yield`. The flag is per process; under `uvicorn --workers N` each worker tracks its own, which is the correct semantic since each worker probes independently |
| `/health/ready` 503 Problem | `detail` | first failing check named ("database check failed", "alembic head mismatch: expected X, found Y", "startup not complete", or "<check> timed out after <s>s") |
| `/api/v1/_meta/error-codes` entries | `code`, `domain` | enum member value split on the first `.`; the prefix is the domain |
| `/api/v1/_meta/error-codes` entries | `http_status`, `title` | reflected from every registered `PlatformError` subclass whose `.code` equals the enum value; where no subclass registers that code, defaults from the owning enum's convention: `*.not_found` → 404, `*.conflict` / `*.inactive` / `*.immutable_field` → 409, everything else → 422; `title` from the class attribute, or title cased code segments as fallback |

**Key invariants**:
- Every `PlatformError` subclass declares `code` matching the regex in AC-2. A startup assertion (`register_exception_handlers`) iterates subclasses and raises if any violates the regex, so a bad rename cannot ship.
- Every `code` value is unique across all registered `PlatformError` subclasses. Two subclasses sharing a code is a programming error; the same startup assertion raises on duplicates so the registry endpoint has a single `http_status` and `title` per code.
- The expected Alembic head is resolved exactly once per process, at import time of a dedicated `app.core.alembic_head` module, from the package relative `alembic.ini` path. No readiness request issues a filesystem read.
- `/health/live` performs zero I/O (no DB session dependency, no file read, no outbound call).
- The shared response builder is the only place that constructs a Problem body; no router or domain handler builds `JSONResponse(media_type="application/problem+json")` by hand. The builder's signature is `_problem_response(*, status_code: int, title: str, detail: str | None, code: str | None, instance: str | None, errors: list[ErrorDetail] | None = None, checks: dict[str, str] | None = None) -> JSONResponse`.
- The `_startup_complete` flag is per worker process; cross worker visibility is neither needed nor claimed.
- The registry endpoint is reflection, not a hand maintained list; adding an enum member in a later feature appears without a code change here.

**Security model**:
- `/health/live`, `/health/ready`, `/api/v1/_meta/error-codes` are unauthenticated by design. Operator probes do not carry credentials; the admin UI reads the registry at build time. Platform is pre launch and not internet exposed. Revisit when the admin UI auth story lands (scope feature 9).
- Error bodies never return the raw string of an unhandled exception; the fallback handler returns `detail=None` and the stack trace lands only in structlog.
- No compliance scope (PII, payments, health) is touched.

**`Problem` model extension**:
Add two optional fields on `Problem` (the shared pydantic model in `src/app/core/errors/__init__.py`):
- `errors: list[ErrorDetail] | None = None`
- `checks: dict[str, str] | None = None`

Both are excluded from the serialized body when `None` (the existing `model_dump(exclude_none=True)` already handles this). The new `ErrorDetail` model is `{code: str, loc: list[str | int], message: str, meta: dict[str, Any] | None = None}`.

**Configuration required**:
- `HEALTH_READY_CHECK_TIMEOUT_S`: per check timeout for `/health/ready` in seconds. Default `1.0`. Loaded through `pydantic-settings` on `app.core.settings.Settings` as `health_ready_check_timeout_s: float = 1.0`.

**Critical test scenarios**:
- Happy path: `GET /health/live` returns 200 `{"status": "ok"}` with no DB session needed, verifies **AC-7**.
- Happy path: `GET /health/ready` with the DB up, Alembic head matching, startup finished returns 200 `{"status": "ok", "checks": {"database": "ok", "alembic": "ok", "startup": "ok"}}`, verifies **AC-8**.
- Failure case: DB down (session raises on `SELECT 1`) returns 503, `application/problem+json`, `code: "health.not_ready"`, `checks.database: "fail"`, verifies **AC-9**.
- Failure case: DB slow (sleep longer than the configured timeout) returns 503 within `timeout + a small margin` seconds, `checks.database: "fail"`, `detail` names the timeout, verifies **AC-10**.
- Failure case: `alembic_version` points at an old revision returns 503 with `checks.alembic: "mismatch"` and `detail` naming both heads, verifies **AC-11**.
- Failure case: a probe hitting the port before the lifespan `startup` hook finishes returns 503 with `checks.startup: "fail"`, verifies **AC-12**.
- Contract: every registered `PlatformError` subclass has a `code` matching the AC-2 regex (static test iterating `PlatformError.__subclasses__()`), verifies **AC-2**.
- Contract: `GET /api/v1/_meta/error-codes` lists every enum member, each with a plausible `domain`, `http_status`, and `title`; the list is sorted and contains no duplicates, verifies **AC-13**.
- Contract: a request that triggers `RequestValidationError` returns Problem Details with `errors` containing `{code: "http.422", loc, message, meta?}` entries built from Pydantic's output, verifies **AC-3**.
- Contract: a request that triggers `WorkflowValidationError` with populated `self.errors` returns the same shape (`errors[]` on the body) via the shared response builder, verifies **AC-3**.
- Contract: a request with the `X-Request-ID` middleware set to a known value returns a Problem body with that id as `correlation_id`, verifies **AC-4**.
- Contract: a request that triggers an unhandled `RuntimeError` returns 500 with `code: "platform.internal_error"`, no `detail`, verifies **AC-15**.
- Rename: every endpoint that previously returned a bare websites code (`duplicate_website`, `host_mismatch`, `website_inactive`, `immutable_field`, `invalid_pagination`, `duplicate_target`, `website_not_found`, `workflow_not_found`, `version_not_found`) now returns the dotted equivalent and no test anywhere references the old string, verifies **AC-5**, **AC-6**.
- Open access: `/health/live`, `/health/ready`, `/api/v1/_meta/error-codes` return 200 without any `Authorization` header; no 401 or 403 is emitted, verifies **AC-14**.

## Build plan

The project's build approach is **Skateboard** (per root `AGENTS.md`): the thinnest usable whole first, then grow. The thinnest usable whole for this spec is "every error response shares one shape, one naming rule, one correlation id; `/health/ready` returns the right HTTP code; the registry is queryable". That lands in two slices, data free, no migration (the feature does not touch the schema). Within each slice, order the work so the shared code moves first, then the renames and new endpoints build on it.

Slice A: rename the bare codes first (prerequisite for the startup assertion and the registry reflection, both of which assume dotted codes).
1. Rename websites domain codes to the dotted form (AC-5), updating `src/app/domains/websites/errors.py` and every call site, fixture, test, or docstring that references the old strings. Satisfies **AC-5**.
2. Rename the three bare entries in `WorkflowErrorCode` (`WEBSITE_NOT_FOUND`, `WORKFLOW_NOT_FOUND`, `VERSION_NOT_FOUND`) to their dotted values (`website.not_found`, `workflow.not_found`, `workflow.version_not_found`) and update every call site. Satisfies **AC-6**.

Slice B: close the contract gaps on the shared scaffold.
3. Extend the `Problem` model in `src/app/core/errors/__init__.py` with the two new fields (`errors`, `checks`) and the `ErrorDetail` sub model per the `## Problem model extension` block above. Satisfies **AC-3** (shape only), **AC-9** (shape only).
4. Refactor `_problem_response` into one shared builder with the signature pinned in Key invariants (an `errors=` and a `checks=` parameter); make `instance` and `correlation_id` the only two "automatic" fields. Every existing handler calls this one function. Satisfies **AC-1**, **AC-4**.
5. Update `_validation_error_handler` to build `errors[]` entries from `RequestValidationError.errors()` (`{code: "http.422", loc, message, meta: {type}}`) and pass them through the shared builder; delete the ad hoc `body["errors"] = ...` hand assembly. Satisfies **AC-3**.
6. Rename `WorkflowValidationError.details` (and any other `PlatformError` subclass whose structured per field list uses a different attribute) to `self.errors`, with the list typed as `list[ErrorDetail]`; update every call site that constructs the exception. Then update `_platform_error_handler` to pass `exc.errors` through the shared builder when present. Satisfies **AC-3**.
7. Confirm `_unhandled_exception_handler` returns `detail=None`, `code="platform.internal_error"` (already close; adjust if needed). Satisfies **AC-15**.
8. Add two startup assertions in `register_exception_handlers`: one iterates every registered `PlatformError` subclass and raises if any `.code` fails the AC-2 regex, the other raises if two subclasses share a code. Satisfies **AC-2**, uniqueness invariant.
9. Add `settings.health_ready_check_timeout_s: float = 1.0`. Satisfies **AC-10** (settings only).

Slice C: finish the health probes and publish the registry (depends on Slices A and B).
10. Create `app/core/alembic_head.py` with module level `EXPECTED_HEAD` populated at import time per the Value sourcing row (package relative `alembic.ini`, `None` on failure). Satisfies **AC-11**.
11. Create `app/core/startup_state.py` with `_startup_complete: bool = False`; in `src/app/main.py` `_lifespan`, import and flip to `True` as the last statement before `yield`. Satisfies **AC-12**.
12. Rewrite `src/app/api/v1/health.py` so `/health/ready` runs the three checks in parallel via `asyncio.gather(..., return_exceptions=True)`, each wrapped in `asyncio.wait_for(..., timeout=settings.health_ready_check_timeout_s)`; shape the body per **AC-8** / **AC-9**; return 503 via the shared response builder passing `checks=`. Satisfies **AC-7**, **AC-8**, **AC-9**, **AC-10**, **AC-14**.
13. Add `app/api/v1/_meta/error_codes.py` with `GET /api/v1/_meta/error-codes` that reflects the five enums and the `PlatformError` subclass tree into the AC-13 payload at app startup, caches the result on the module, and serves it unauthenticated. Satisfies **AC-13**, **AC-14**.

Slice D: test it.
14. `/test structured errors and health endpoints`, driven by the Critical test scenarios list above. Satisfies **AC-1** through **AC-15** by test coverage.

## Consequences

**Positive**:
- One naming rule, one body shape, one `correlation_id` wiring across every error path.
- `/health/ready` behaves correctly under Kubernetes, ECS, and any load balancer that reads the HTTP status code; a DB outage removes the pod from rotation.
- `/api/v1/_meta/error-codes` publishes the contract so the admin UI and external clients stop pattern matching code strings.
- Startup assertion makes a bad rename or a missing prefix fail fast in CI, not in production.

**Negative / tradeoffs**:
- Breaking rename of the websites bare codes and three `WorkflowErrorCode` entries. Mitigated by: the platform is pre launch, no external consumer, every rename traced to a build task.
- Readiness response shape change (`{status, database}` → `{status, checks: {...}}`). The only reader today is the probe itself.
- Three parallel checks per readiness probe is more work than one `SELECT 1`; still well under 1s with the configured timeout.

**Neutral**:
- No database migration. No new runtime dependency. No new infrastructure.
- A new settings field (`HEALTH_READY_CHECK_TIMEOUT_S`); documented in the usual `.env` sample.
- Later features (scope 12 structured logging, 13 metrics, 28 CI/CD) can lean on the finished contract rather than re deciding it.

## Follow-up

- [ ] When scope feature 9 (admin UI foundation) lands, decide whether `/api/v1/_meta/error-codes` stays open or moves behind the API auth with the rest of `/_meta/`.
- [ ] When scope feature 28 (containerisation + CI) lands, wire the Dockerfile `HEALTHCHECK` and the Kubernetes `livenessProbe` / `readinessProbe` to these endpoints and raise the per check timeout only if a real dependency needs it.
- [ ] If and when any external API consumer appears, publish the registry's shape (`/_meta/error-codes` schema) in the OpenAPI document as the authoritative reference.
- [ ] When a rate limit middleware lands (not scoped today), add `/health/live`, `/health/ready`, and `/api/v1/_meta/error-codes` to its exclusion list and tighten AC-14 to assert the exclusion.
