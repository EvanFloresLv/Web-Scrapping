# 0006. Workflow execution endpoint (sync)

**Date**: 2026-10-20
**Status**: In Progress

## Summary

This spec is the build spec for Slice 1's execution endpoint. It adds `POST /api/v1/workflows/{workflow_id}/execute`, which runs a published workflow version against a registered target URL by invoking the pure `ExtractionService.run(...)` call from [0005](../0005-deterministic-html-extraction/index.md), persists one `executions` row plus (on success) one `execution_results` row per extracted item against the shape pinned by [0003](../0003-data-model-mvp/index.md), and returns the full execution record and items inline. It also adds `GET /api/v1/executions/{id}` so operators and tests can inspect a run after the fact; the full execution browser (list + filters) is feature 11. Pre-run validation failures (unknown workflow / version / target, archived or draft version, workflow without a current version, target not under the workflow's website) return 4xx with Problem Details and persist no row; failures that occur after the run has started persist a `failed` row and return `200` with the failed body. The sync executor transitions `running → completed | failed`; the `pending` state (0003 AC-12) stays reserved for feature 23's async worker.

## Requirements

**User stories**

- As a platform operator, I want `POST /workflows/{id}/execute` to run my published workflow against a registered target URL and return the structured items in one response, so that I can verify end-to-end behavior from a script or curl without touching the DB.
- As a platform operator, I want every actual run (success and failure) to persist exactly one `executions` row with its correlation id, so that I can look up what happened after the fact and so later features (feature 11 execution browser, feature 18 product provenance) can build on real history.
- As a platform operator, I want a typo in a workflow id, version id, or target id to return a clean 4xx without creating an execution row, so that the executions table is a record of actual attempts, not of mistyped requests.
- As a platform engineer building the async worker (feature 23), I want the execution lifecycle rules enforced by one `ExecutionService` module (version resolution, target scoping, transaction shape, error code mapping), so that the async path can reuse the same core and only replace the HTTP shell.

**Acceptance criteria** (the contract later skills check)

- **AC-1**: `POST /api/v1/workflows/{workflow_id}/execute` accepts a JSON body `{target_url_id: UUID (req), version_id: UUID | null = null}` and runs the resolved workflow version against the resolved target URL via `ExtractionService.run(...)`. The endpoint is open on localhost (feature 26 adds the auth gate). A missing, malformed, or wrong-type body (Pydantic shape failure) returns `422 execution.invalid_execute_body` as RFC 7807 Problem Details (per AC-11), with the Pydantic field path in `details`.
- **AC-2**: Version resolution rules:
  - If `version_id` is `null` (or omitted), the executor uses `scraping_workflows.current_version_id`. If that pointer is `NULL` (no version has ever been published for this workflow), the endpoint returns `409 execution.workflow_not_runnable` with no row persisted.
  - If `version_id` is provided, it must belong to the workflow at the path parameter (`workflow_versions.workflow_id = workflow_id`); mismatch returns `404 version_not_found` (reusing the code pinned by [0004](../0004-workflow-configuration-versioning/index.md) AC-15).
  - The resolved version's `status` must be `published`. A `draft` version returns `409 execution.version_not_published` (iterate on it via the preview endpoint from [0005](../0005-deterministic-html-extraction/index.md) AC-2 instead). An `archived` version returns `409 execution.version_archived`, per [0003](../0003-data-model-mvp/index.md) AC-12 ("not runnable for new executions"). No row persisted in either case.
- **AC-3**: Target binding and scoping. The body carries `target_url_id` (not a URL string); the executor loads the `target_urls` row by id with the default `with_deleted=False` filter. A missing or soft-deleted target returns `404 execution.target_not_registered`. The loaded target's `website_id` must equal the workflow's `website_id` (0003 AC-3); mismatch returns `404 execution.target_not_registered` (same code, so a caller cannot distinguish "unknown target" from "target under a different website", which is deliberate: both are "this target is not registered under this workflow"). No row persisted. URL-string resolution stays with the preview endpoint ([0005](../0005-deterministic-html-extraction/index.md) AC-3); the execute endpoint is id-only.
- **AC-4**: The soft-delete gate from [0003](../0003-data-model-mvp/index.md) AC-18 still applies at the workflow aggregate: a `scraping_workflows` row with `deleted_at IS NOT NULL` is invisible to the executor (treated as unknown) and returns `404 workflow_not_found` (reusing the code from [0004](../0004-workflow-configuration-versioning/index.md) AC-15). The in-flight-execution refusal on workflow delete ([0003](../0003-data-model-mvp/index.md) AC-18) is enforced by feature 5's workflow service, not here; this endpoint only has to see a currently-live workflow.
- **AC-5**: Execution lifecycle (two-commit transaction shape):
  1. **Insert + commit (session A)**: after pre-run validation passes, the executor inserts a new `executions` row with `status='running'`, `started_at = datetime.now(UTC)` set by the service in Python (NOT a DB `now()` default; one clock domain across both commits per AC-5 step 3), `correlation_id` sourced from the `asgi-correlation-id` middleware contextvar (per [0003](../0003-data-model-mvp/index.md) AC-6), `items_extracted = 0`, every error column `NULL`. The transaction commits before the extraction service is called, so the row is durable from the moment work begins.
  2. **Extraction**: `ExtractionService.run(workflow_version, target_url)` runs outside any DB transaction. Its result (`ExtractionResult` per [0005](../0005-deterministic-html-extraction/index.md) AC-1) is turned into the terminal update below. `ExtractionResult.error_details` is NOT persisted on `executions` (no column; the row stores `error_code` + `error_message` only, per [0003](../0003-data-model-mvp/index.md) AC-6); the full `error_details` list is attached to the `execution.failed` structlog event (AC-13) so it remains inspectable without widening the schema.
  3. **UPDATE + commit (session B)**: in one transaction, the executor UPDATEs the `executions` row to the terminal status (`completed` or `failed`), sets `finished_at = datetime.now(UTC)` (same clock domain as `started_at`), computes `duration_ms = int((finished_at - started_at).total_seconds() * 1000)`, sets `items_extracted` to the final count (0 on failure), on failure sets `error_code` and `error_message`, and on success inserts the N `execution_results` rows (one per item, dense `item_index` 0..N-1). Both the UPDATE and the INSERTs commit together so a `completed` execution and its results are visible atomically.
  The sync executor never writes `status='pending'`; it inserts straight into `running`. The `pending → *` path stays reserved for feature 23's async worker.
- **AC-6**: Pre-run validation failures (every 4xx from AC-1 through AC-4) persist **no** `executions` row. The executions table is a record of actual run attempts; mistyped requests and workflow state violations stay in the HTTP layer. (Rationale: 4xx callers get an actionable error immediately; feature 11's lists stay signal.) The `pending → failed` validation-reject path pinned by [0003](../0003-data-model-mvp/index.md) AC-12 is reserved for the async worker (feature 23), which cannot return 4xx to the enqueuer.
- **AC-7**: Response body on `200 OK`:
  ```
  {
    "execution": {
      "id": "01HV...-uuid",
      "workflow_id": "01HV...-uuid",
      "workflow_version_id": "01HV...-uuid",
      "target_url_id": "01HV...-uuid",
      "status": "completed" | "failed",
      "started_at": "2026-10-20T12:34:56.789Z",
      "finished_at": "2026-10-20T12:34:57.123Z",
      "duration_ms": 334,
      "items_extracted": 2,
      "error_code": "fetch.timeout" | null,
      "error_message": "..." | null,
      "correlation_id": "01HV...-uuid",
      "created_at": "2026-10-20T12:34:56.789Z"
    },
    "items": [
      { "item_index": 0, "payload": { ... } },
      { "item_index": 1, "payload": { ... } }
    ] | []
  }
  ```
  `items` is the empty list on `status='failed'`, never `null`. On success it holds exactly `items_extracted` entries in `item_index` order. The `execution.workflow_id` field is denormalised onto the response (joined from `workflow_versions.workflow_id`) so a caller does not need a second lookup to know which workflow ran. Field names are snake_case; UUIDs are strings; timestamps are ISO-8601 with trailing `Z`; per the wire conventions in `AGENTS.md`.
- **AC-8**: HTTP status rules:
  - A successfully persisted execution returns `200 OK` whether `status='completed'` or `status='failed'`. A failed run is a successful API operation whose job result is failed; it does not fail the HTTP layer. (Preview endpoint ([0005](../0005-deterministic-html-extraction/index.md) AC-2) uses the same posture.)
  - Pre-run validation (AC-1 through AC-4) returns 4xx with Problem Details (per AC-11). Codes: `404 workflow_not_found | version_not_found | execution.target_not_registered`; `409 execution.workflow_not_runnable | execution.version_not_published | execution.version_archived`; `422 execution.invalid_execute_body`.
  - A failure to persist the `executions` row (DB connectivity, FK race, etc.) returns `500` with a generic `internal_error` code; the extraction has not been attempted yet, so no partial state is possible.
  - A failure to UPDATE the terminal row after the extraction ran (DB connectivity lost between the two commits) returns `500` with code `execution.terminal_persist_failed` and leaves the `running` row in place; the operator or a future reconciliation job (deferred) handles cleanup. Flagged in Follow-up.
- **AC-9**: `GET /api/v1/executions/{id}` returns the same response body as AC-7 (`{execution, items}`). The route reads the `executions` row by id with the default `with_deleted=False` filter (hidden when the parent workflow is soft deleted, per [0003](../0003-data-model-mvp/index.md) AC-20); misses return `404 execution.not_found`. For a currently-`running` execution (visible mid-run if the caller polls between the two commits of AC-5), the response carries the `running` row and `items: []`; `finished_at`, `duration_ms`, and error columns are `null`.
- **AC-10**: The error code registry `src/app/core/errors/execution_codes.py` is extended with one new StrEnum shipped by this feature:
  - `ExecutionErrorCode`: `execution.workflow_not_runnable` (no current version), `execution.version_not_published` (explicit draft requested), `execution.version_archived` (explicit archived version requested), `execution.target_not_registered` (unknown target or target under a different website), `execution.invalid_execute_body` (bad Pydantic shape), `execution.terminal_persist_failed` (DB UPDATE after the run), `execution.not_found` (GET by id miss).
  The existing codes reused from other specs (`workflow_not_found`, `version_not_found` from [0004](../0004-workflow-configuration-versioning/index.md) AC-15) are not re-declared here; they live in the workflows registry. Every new code uses the `execution.*` prefix per [0003](../0003-data-model-mvp/index.md) AC-17.
  Persisted `executions.error_code` values on a `failed` row are drawn from `FetchErrorCode | ExtractionErrorCode` (shipped by [0005](../0005-deterministic-html-extraction/index.md) AC-14), not from `ExecutionErrorCode`; the executor passes `ExtractionResult.error_code` through untouched. `ExecutionErrorCode` values are returned over HTTP only; they never land in `executions.error_code`.
- **AC-11**: Every 4xx and 5xx response is `application/problem+json` (RFC 7807) with the shape pinned by [0004](../0004-workflow-configuration-versioning/index.md) AC-13: `{type: 'about:blank', title, status, detail, code, correlation_id, details?}`. A `200` success body is JSON (not Problem Details), using the shape in AC-7.
- **AC-12**: Correlation and persistence. The `correlation_id` on the `executions` row is the current request's `X-Request-ID` (bound by `asgi-correlation-id` per [0001](../0001-stack-and-architecture/index.md) and persisted per [0003](../0003-data-model-mvp/index.md) AC-6). Every structlog event emitted by this feature carries it, so the HTTP access log line, the executor events, the extraction events (from [0005](../0005-deterministic-html-extraction/index.md) AC-15), and the stored `executions.correlation_id` all share the same value.
- **AC-13**: Observability (structlog + metrics):
  - Events: `execution.started` (after the insert + commit), `execution.completed` (after the terminal commit, `status='completed'`), `execution.failed` (after the terminal commit, `status='failed'`). Each event carries `correlation_id`, `execution_id`, `workflow_id`, `workflow_version_id`, `target_url_id`, `duration_ms` (when known), `items_extracted` (when known), `error_code` (when failed), and `error_details` (the full `ExtractionResult.error_details` list on `execution.failed`, since it is intentionally not persisted on the row per AC-5 step 2).
  - Metrics (extending the wrapper at `src/app/core/observability/metrics.py` shipped by [0005](../0005-deterministic-html-extraction/index.md) AC-15): `executions_total` (counter, label `status=completed|failed`) and `execution_duration_seconds` (histogram, label `status=completed|failed`). Pre-run 4xx rejections are **not** counted here (they are HTTP errors, not executions); FastAPI's standard access log picks them up.
- **AC-14**: Repositories. Concrete `SqlAlchemyExecutionRepository` and `SqlAlchemyExecutionResultRepository` land in `src/app/domains/executions/repository.py`, implementing the Protocols pinned by [0003](../0003-data-model-mvp/index.md). Each read method defaults to `with_deleted=False`; the join chain to `scraping_workflows` filters out `deleted_at IS NOT NULL` parents per [0003](../0003-data-model-mvp/index.md) AC-20. The `finalise(execution)` method is the one-shot UPDATE from AC-5 step 3; it refuses to run on a row that is already in a terminal state (defensive assertion against double-finalise). The `add(execution)` method inserts in `running` for this feature; the Protocol signature keeps the broader docstring from [0003](../0003-data-model-mvp/index.md). The `get(execution_id)` method eager-loads results via `selectinload(Execution.results)` (`Execution.results` is `lazy="raise_on_sql"` per the ORM) and also joins `workflow_versions` (`selectinload` or `joinedload`) so `workflow_versions.workflow_id` is available for the response field `execution.workflow_id` (AC-7) without a second query. Both load strategies apply to both the POST terminal-row refetch (if the service re-reads before building the response) and the GET-by-id path.

- **AC-14a**: Cross-domain workflow and version read access. The `executions` domain cannot import `app.domains.workflows` models (`import-linter` contract per `AGENTS.md`: "A domain module may import `core` and its own package only"). This feature introduces a `WorkflowReadPort` Protocol defined in `app.core.workflows` (new module; cross-domain port lives in `core` by convention) with the methods `ExecutionService` needs: `get_live_workflow(workflow_id) -> WorkflowSummary | None` (returns `{id, website_id, current_version_id, status, deleted_at}` as a value object; `None` when soft-deleted or missing) and `get_version_for_workflow(workflow_id, version_id) -> VersionSummary | None` (returns `{id, workflow_id, status, config: WorkflowConfig}`; `None` when the version does not belong to the workflow). The concrete implementation `WorkflowReadAdapter` lives under `app.domains.workflows` and is wired into FastAPI via `Depends(get_workflow_read_port)`. `ExecutionService` only ever imports from `app.core.workflows` and its own package, so the import boundary stays clean. Pydantic value objects for `WorkflowSummary` and `VersionSummary` live beside the Protocol in `app.core.workflows`.
- **AC-15**: Alembic migration `migrations/versions/202610XXXXXX_add_executions_and_execution_results.py` (timestamp assigned at build time) creates `executions` and `execution_results` with every column, FK (RESTRICT on parents, CASCADE on `execution_results.execution_id → executions.id`), CHECK constraint, and INDEX pinned by [0003](../0003-data-model-mvp/index.md) `## Feature design`. The parents (`workflow_versions`, `target_urls`) already exist by this point (features 5 and 4 shipped their migrations), so no DDL ordering trick is needed. The migration is reversible: `downgrade()` drops both tables in the reverse FK order (`execution_results` then `executions`). CI contract per [0003](../0003-data-model-mvp/index.md) Follow-up to feature 5: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` runs clean.
- **AC-16**: Testing (reusing the fixture suite + `respx` setup from [0005](../0005-deterministic-html-extraction/index.md) AC-19):
  - **Happy path**: `POST /workflows/{id}/execute` with a published version and a registered target returns `200 completed` with the expected items; one `executions` row persists with `status='completed'`, `started_at`/`finished_at` set, `duration_ms` populated, `items_extracted` matching the body, `correlation_id` matching the request's `X-Request-ID`; N `execution_results` rows persist with dense `item_index`. Verifies **AC-1, AC-5, AC-7, AC-12, AC-13**.
  - **Failed extraction**: a workflow against a fixture where the container selector matches zero → `200 failed` with `error_code='extraction.no_container_match'`; one `executions` row with `status='failed'`, `error_code`/`error_message` set, zero `execution_results`. Verifies **AC-5, AC-6, AC-7, AC-8**.
  - **Failed fetch**: `respx` stubs a 503 → `200 failed` with `error_code='fetch.http_error'`; row persists with same shape. Verifies **AC-5, AC-7, AC-8**.
  - **Omitted version_id uses current**: a workflow with `current_version_id` set runs that version when body omits `version_id`. Verifies **AC-2**.
  - **No current version**: a workflow whose `current_version_id` is NULL returns `409 execution.workflow_not_runnable` with no row. Verifies **AC-2, AC-6**.
  - **Explicit draft version**: passing `version_id` of a draft returns `409 execution.version_not_published` with no row. Verifies **AC-2, AC-6**.
  - **Explicit archived version**: passing `version_id` of an archived version returns `409 execution.version_archived` with no row. Verifies **AC-2, AC-6**.
  - **Version from a different workflow**: passing `version_id` from workflow B against workflow A returns `404 version_not_found` with no row. Verifies **AC-2, AC-6**.
  - **Target under a different website**: `target_url_id` belongs to a target under a different website than the workflow → `404 execution.target_not_registered` with no row. Verifies **AC-3, AC-6**.
  - **Soft-deleted target**: a target with `deleted_at` set → `404 execution.target_not_registered` with no row. Verifies **AC-3, AC-6**.
  - **Soft-deleted workflow**: a workflow with `deleted_at` set → `404 workflow_not_found` with no row. Verifies **AC-4, AC-6**.
  - **Invalid body**: missing `target_url_id`, or wrong UUID shape → `422 execution.invalid_execute_body` with Pydantic field path in `details`. Verifies **AC-1, AC-11**.
  - **GET by id after success**: `GET /executions/{id}` returns the same body as the POST response. Verifies **AC-9**.
  - **GET by id after failure**: returns the failed body. Verifies **AC-9**.
  - **GET by id miss**: unknown id → `404 execution.not_found`. Verifies **AC-9, AC-10**.
  - **GET by id for soft-deleted workflow**: an execution under a workflow that is now soft deleted → `404 execution.not_found` (default `with_deleted=False`). Verifies **AC-9**.
  - **Correlation id round trip**: client-supplied `X-Request-ID` ends up on the response's Problem Details body (on 4xx) and on the stored `executions.correlation_id` (on 200). Verifies **AC-12**.
  - **Error shape**: every 4xx response body is RFC 7807 shaped with `code`, `correlation_id`, and `details` when applicable. Verifies **AC-11**.

## Decision

**Chosen option**: Option 1: ship a thin `ExecutionService` under `src/app/domains/executions/` that wraps `ExtractionService.run(...)` with id-only version and target resolution, a two-commit transaction (insert `running` → run → UPDATE terminal), 4xx-with-no-row for pre-run validation, and a single `POST /execute` plus `GET /executions/{id}` surface. Response body returns the execution row plus items inline, so one round trip is enough. Failed runs return `200` with `status='failed'`; 4xx and 5xx are reserved for API-layer and persistence errors.

The feature is the smallest useful whole that makes the extraction service persistent: operators can run, get the result, and look it up later; feature 11 adds the browser; feature 23 adds the async path by reusing the same `ExecutionService`.

**Implementation skills**: `fastapi` (`fastapi/fastapi`, `.claude/skills/fastapi/`) · `sqlalchemy-alembic-expert-best-practices-code-review` (`wispbit-ai/skills`, `.claude/skills/sqlalchemy-alembic-expert-best-practices-code-review/`) · `python-testing-patterns` (`wshobson/agents`, `.claude/skills/python-testing-patterns/`) · `modern-python` (`trailofbits/skills`, `.claude/skills/modern-python/`) · `uv-package-manager` (`wshobson/agents`, `.claude/skills/uv-package-manager/`)

## Rationale

Reasoning and options considered: see [`rationale.md`](rationale.md).

## Feature design

**Data model sketch**

No new tables are designed here; the shape is pinned by [0003](../0003-data-model-mvp/index.md). This feature ships the Alembic migration that materialises `executions` and `execution_results` as described in [0003](../0003-data-model-mvp/index.md) `## Feature design`. No additive change to any Pydantic model, no change to `WorkflowConfig`.

Reused value objects and services: `WorkflowVersion` and workflow resolution patterns from [0004](../0004-workflow-configuration-versioning/index.md); `TargetUrl` and the `with_deleted=False` filter from [0002](../0002-website-target-registration/index.md); `ExtractionService.run(...)`, `ExtractionResult`, `FetchErrorCode`, `ExtractionErrorCode` from [0005](../0005-deterministic-html-extraction/index.md).

**State transitions**

```
executions (sync path, feature 7)
    (no row)  ──── pre-run 4xx ───▶  (no row; returned to caller)
         │
         └── pre-run OK ──▶  insert running + commit
                                   │
                                   └─ ExtractionService.run(...)
                                             │
                                 ┌─ ExtractionResult.status='completed' ─▶ UPDATE completed + INSERT results + commit
                                 │
                                 └─ ExtractionResult.status='failed' ────▶ UPDATE failed + commit
```

`pending`, and the `pending → failed` transition, are not used by this feature. They stay reserved for feature 23's async worker.

**API surface**

All endpoints under `/api/v1`. Auth is open on localhost (feature 26 adds the gate). Errors are `application/problem+json` per AC-11.

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/workflows/{workflow_id}/execute` | POST | `target_url_id: UUID (req)`, `version_id: UUID \| null (opt)` | `200 {execution, items}` (per AC-7) | open | `404 workflow_not_found \| version_not_found \| execution.target_not_registered`; `409 execution.workflow_not_runnable \| execution.version_not_published \| execution.version_archived`; `422 execution.invalid_execute_body`; `500 internal_error \| execution.terminal_persist_failed` |
| `/executions/{id}` | GET | `id: UUID (path)` | `200 {execution, items}` (per AC-9) | open | `404 execution.not_found` |

**Internal service surface** (not an HTTP endpoint; feature 23 will reuse it)

- `executions.service.ExecutionService.execute(workflow_id: UUID, target_url_id: UUID, version_id: UUID | None) -> Execution` — the core of this feature; raises typed exceptions (`WorkflowNotFoundError`, `VersionNotFoundError`, `VersionNotPublishedError`, `VersionArchivedError`, `WorkflowNotRunnableError`, `TargetNotRegisteredError`) for pre-run failures and returns the terminal `Execution` row (with `results` populated via `selectinload`) on success or failed-run.
- `executions.service.ExecutionService.get(execution_id: UUID) -> Execution | None` — thin pass-through to the repository for `GET /executions/{id}`.
- `executions.repository.SqlAlchemyExecutionRepository` and `SqlAlchemyExecutionResultRepository` — concrete implementations of the Protocols pinned by [0003](../0003-data-model-mvp/index.md), using the request-scoped `AsyncSession` from `Depends(get_session)` per `AGENTS.md`.
- `core.workflows.WorkflowReadPort` (new; see AC-14a) — the cross-domain Protocol `ExecutionService` depends on for workflow and version reads. Concrete `WorkflowReadAdapter` lives in `app.domains.workflows` and is injected via `Depends(get_workflow_read_port)`.

**Request / response schemas**

Request (POST):

```
{
  "target_url_id": "01HV...-uuid",
  "version_id": "01HV...-uuid" | null
}
```

Response (POST success and GET by id): see AC-7 for the full shape. Problem Details (4xx / 5xx) match [0004](../0004-workflow-configuration-versioning/index.md) AC-13 verbatim.

**Value sourcing** (the values this spec's endpoints produce or persist, and where each comes from)

| Action | Value produced / stored | Source |
|---|---|---|
| POST `/execute` | `workflow_id` | Path parameter, validated against live `scraping_workflows` (default `with_deleted=False`); miss → `404 workflow_not_found` |
| POST `/execute` | Resolved `version_id` | Body `version_id` if provided (must match `workflow_versions.workflow_id = workflow_id`; mismatch → `404 version_not_found`); else `scraping_workflows.current_version_id` (NULL → `409 execution.workflow_not_runnable`) |
| POST `/execute` | Runnability check | Resolved version `status` must be `published`; `draft` → `409 execution.version_not_published`; `archived` → `409 execution.version_archived` |
| POST `/execute` | Resolved `target_url_id` | Body field, validated against live `target_urls` filtered by `website_id = workflow.website_id` (default `with_deleted=False`); any miss (unknown, soft-deleted, or under a different website) → `404 execution.target_not_registered` |
| POST `/execute` | `WorkflowConfig` passed to the extraction service | `WorkflowConfig.model_validate(workflow_versions.config)` on read, per [0005](../0005-deterministic-html-extraction/index.md) `## Value sourcing` |
| Insert `executions` | `id` | Application UUIDv7 via the generator pinned by [0001](../0001-stack-and-architecture/index.md) |
| Insert `executions` | `status` | Literal `'running'` on insert (sync path only; AC-5) |
| Insert `executions` | `started_at` | `datetime.now(UTC)` set by the service in Python immediately before the INSERT (not a DB-side default); same clock domain as `finished_at` (AC-5) |
| Insert `executions` | `correlation_id` | `asgi-correlation-id` middleware contextvar bound by the request (per [0003](../0003-data-model-mvp/index.md) AC-6 and `AGENTS.md`) |
| Insert `executions` | `items_extracted` | `0` on insert; updated at terminal to the final count |
| UPDATE `executions` (terminal) | `finished_at` | `datetime.now(UTC)` set by the service in Python immediately before the UPDATE (same clock domain as `started_at`) |
| UPDATE `executions` (terminal) | `duration_ms` | `int((finished_at - started_at).total_seconds() * 1000)`, computed by the service in Python; one clock domain across both commits avoids the DB-clock vs host-clock skew risk |
| UPDATE `executions` (terminal) | `status` | `ExtractionResult.status` from the extraction service (`completed` or `failed`) |
| UPDATE `executions` (terminal) | `items_extracted` | `ExtractionResult.items_count` (0 on failure) |
| UPDATE `executions` (terminal) | `error_code`, `error_message` | `ExtractionResult.error_code` and `.error_message` from the extraction service (`FetchErrorCode | ExtractionErrorCode`); NULL on `completed`. `ExecutionErrorCode` values are **never** persisted here (AC-10). `ExtractionResult.error_details` is intentionally not persisted (no column on `executions`); it is attached to the `execution.failed` structlog event (AC-13) instead |
| Insert `execution_results` (per item) | `id` | Application UUIDv7 |
| Insert `execution_results` (per item) | `execution_id` | The `executions.id` from the insert above |
| Insert `execution_results` (per item) | `item_index` | Dense 0-based ordinal, one per entry in `ExtractionResult.items` in order |
| Insert `execution_results` (per item) | `payload` | `ExtractionResult.items[i]` dict, already matching the version's `output_schema` (validated by [0005](../0005-deterministic-html-extraction/index.md) AC-11) |
| Response (POST and GET) | `execution.workflow_id` | Joined from `workflow_versions.workflow_id` for the resolved version via `selectinload`/`joinedload` on the repository read (AC-14); no second query |
| Response (POST and GET) | `items` | Eager-loaded via `selectinload(Execution.results)` in the repository read (`Execution.results` is `lazy="raise_on_sql"` per the ORM), per AC-14 |
| Problem Details (4xx / 5xx) | `correlation_id` | Request-scoped structlog contextvar from `asgi-correlation-id` (per [0001](../0001-stack-and-architecture/index.md) and `AGENTS.md`) |

**Key invariants**

- Every `executions` row persisted by this feature has `started_at IS NOT NULL` (sync path never inserts `pending`); on `completed` and `failed`, `finished_at IS NOT NULL` and `duration_ms IS NOT NULL` (consistent with [0003](../0003-data-model-mvp/index.md) `## Key invariants`).
- A `completed` row has `error_code IS NULL` and `items_extracted = count(execution_results WHERE execution_id = this.id)`. A `failed` row has `error_code IS NOT NULL`, `items_extracted = 0`, and zero `execution_results` (consistent with [0003](../0003-data-model-mvp/index.md) `## Key invariants`).
- `executions.error_code`, when non-null, is a `FetchErrorCode` or `ExtractionErrorCode` value (never an `ExecutionErrorCode`); `ExecutionErrorCode` values travel over HTTP only.
- A 4xx response from `POST /execute` leaves `executions` and `execution_results` untouched (AC-6). A `200` response always corresponds to exactly one newly-persisted `executions` row.
- `POST /execute` ends in a terminal state within one HTTP request (sync): no `running` row is ever left behind by a normal response. A `running` row can exist mid-flight if the caller polls `GET /executions/{id}` between the two commits, or if the terminal UPDATE fails with `execution.terminal_persist_failed`; both are rare and visible.

**Security model**

- No new authn or authz; inherits the open-on-localhost posture of the MVP (feature 26 adds the API-key gate). The feature's attack surface is one write endpoint and one read endpoint, both over authenticated resources once feature 26 lands.
- SSRF controls (server-side request forgery, when a server fetches an internal URL on an attacker's behalf) are not added here (feature 27 owns them). The host allow-list is enforced indirectly: the executor can only fetch URLs under a `target_url` that is registered under the workflow's website (AC-3). An attacker with API access can only hit URLs the operator already registered under that workflow.
- No new logged secrets. `error_message` on `executions` can carry up to 4000 characters of the extraction service's message (truncated at insert per [0003](../0003-data-model-mvp/index.md)); the message never contains the HTML body or request headers (confirmed by [0005](../0005-deterministic-html-extraction/index.md) `## Security model`).
- `correlation_id` is a request trace identifier, not an auth token; it is safe to log and to return in the response and in Problem Details.
- Compliance scope: none for this feature (no PII, no regulated data).

**Configuration required**

None new. The feature uses the extraction settings already pinned by [0005](../0005-deterministic-html-extraction/index.md) `## Configuration required` (`EXTRACTION_HTTP_*`), the DB settings from [0001](../0001-stack-and-architecture/index.md), and the correlation-id middleware from [0001](../0001-stack-and-architecture/index.md).

**Critical test scenarios**

Every scenario is listed under AC-16; the acceptance mapping is kept there to avoid duplication.

## Build plan

Skateboard order for the sync executor: ship the thinnest usable whole first (migration + a happy-path POST that persists one row and its results), then thicken one dimension at a time (validation failures, failed runs, read endpoint, observability, tests).

1. **Alembic migration** `migrations/versions/202610XXXXXX_add_executions_and_execution_results.py` creating `executions` and `execution_results` per [0003](../0003-data-model-mvp/index.md) `## Feature design` (every column, FK, CHECK, INDEX). Reversible: `downgrade()` drops `execution_results` then `executions`. Satisfies **AC-15**.
2. **Error registry extension** in `src/app/core/errors/execution_codes.py`: add `ExecutionErrorCode` StrEnum with the entries listed in AC-10. Satisfies **AC-10**.
3. **Cross-domain workflow read port** `src/app/core/workflows.py`: `WorkflowReadPort` Protocol plus `WorkflowSummary` and `VersionSummary` Pydantic value objects (AC-14a). Concrete `WorkflowReadAdapter` under `src/app/domains/workflows/read_adapter.py` implements it (reads via the existing workflow repository, maps rows into the value objects) and is wired via a FastAPI dependency `get_workflow_read_port`. The adapter is the only module that imports from both executions and workflows contexts (it lives in workflows and exports an interface defined in core, so no boundary violation). Satisfies **AC-14a**.
4. **Concrete repositories** in `src/app/domains/executions/repository.py`: `SqlAlchemyExecutionRepository` (with `get` eager-loading `results` via `selectinload` plus the `workflow_versions` join for `workflow_id`, `list_for_workflow_version`, `list_for_target_url`, `list_by_status`, `add`, `finalise`) and `SqlAlchemyExecutionResultRepository` (with `list_for_execution`, `add_many`). Default `with_deleted=False` filter joined through `workflow_versions → scraping_workflows`. `finalise` refuses to run on a row already in a terminal state. Satisfies **AC-14, AC-5** (persistence half), **AC-7**/**AC-9** (eager-load coverage).
5. **`ExecutionService`** in `src/app/domains/executions/service.py`: `execute(workflow_id, target_url_id, version_id)` performs the version resolution via `WorkflowReadPort` (AC-2), target scoping (AC-3), workflow visibility check (AC-4), the two-commit lifecycle with one-clock-domain timing (AC-5), and the terminal UPDATE from the `ExtractionResult`. `get(execution_id)` is a thin repository pass-through. Raises typed exceptions for pre-run failures (`WorkflowNotFoundError`, `VersionNotFoundError`, `VersionNotPublishedError`, `VersionArchivedError`, `WorkflowNotRunnableError`, `TargetNotRegisteredError`). Satisfies **AC-1 through AC-6, AC-12, AC-14a**.
6. **Request / response schemas** in `src/app/domains/executions/schemas.py`: `ExecuteRequest`, `ExecutionResponse`, `ExecutionBody`, `ExecutionItem`. Pydantic models with the shapes from AC-1 and AC-7. Satisfies **AC-1, AC-7**.
7. **Router** `src/app/api/v1/executions.py`: `POST /workflows/{workflow_id}/execute` and `GET /executions/{id}` wired to the service via `Depends`; typed exceptions from the service mapped to Problem Details (shape per [0004](../0004-workflow-configuration-versioning/index.md) AC-13) with the right HTTP status per AC-8; mount on `src/app/api/v1/router.py`. Satisfies **AC-1, AC-7, AC-8, AC-9, AC-11**.
8. **Structlog events + metrics** wired into the service: `execution.started`, `execution.completed`, `execution.failed` emitters (the `failed` event carries the full `error_details` list per AC-13), plus `executions_total` and `execution_duration_seconds` on the metrics wrapper. Satisfies **AC-13**.
9. **Fixture + integration test suite** under `tests/` reusing feature 6's fixture layout and `respx` setup, covering every scenario in AC-16 (happy path, failed extraction, failed fetch, every pre-run 4xx, GET by id, correlation-id round trip, Problem Details shape). Satisfies **AC-16** and transitively every other AC.

The data model touch (migration in step 1) ships first because every later task reads it. No `WorkflowConfig` change; the extraction service, fetcher, parser, extractor, validator, and transforms from [0005](../0005-deterministic-html-extraction/index.md) are reused untouched.

## Consequences

**Positive**

- Feature 7 is a persistence shell around a solved problem: the extraction service and its error vocabulary ship from [0005](../0005-deterministic-html-extraction/index.md); the executions and results shape ships from [0003](../0003-data-model-mvp/index.md). The build plan is small, mechanical, and testable end-to-end against the existing fixtures.
- The two-commit lifecycle (insert `running` → run → UPDATE terminal) makes every attempt durable from the moment work begins. A process crash mid-extract leaves a `running` row the operator can see and reconcile; the alternative (persist only at the end) would silently lose the attempt.
- 4xx-with-no-row for pre-run validation keeps the executions table a signal of real run attempts, not of mistyped calls. Feature 11's lists do not need a "hide validation rejects" filter.
- `ExecutionService.execute(...)` is the one place that knows the sync lifecycle. Feature 23's async worker will reuse the resolution and the terminal mapping and only replace the "two synchronous commits in one request" wrapper with "enqueue a job, run it in a worker, poll via GET".
- Reusing [0005](../0005-deterministic-html-extraction/index.md)'s error prefixes verbatim (`fetch.*`, `extraction.*`) in `executions.error_code` means feature 11, feature 15, and feature 17 can read persisted history and apply the same error-class logic they apply to live preview runs.

**Negative / tradeoffs**

- The two-commit shape costs one extra DB round-trip per request versus a single-commit "persist terminal only" design. In the sync endpoint this is negligible (one more INSERT + commit on each run); the durability payoff is worth it.
- `GET /executions/{id}` is a stopgap read endpoint; feature 11 adds the full browser with filters and pagination. Callers that need to list executions for a workflow or filter by status have to wait or query the DB directly.
- The `pending` state and the `pending → failed` validation-reject path from [0003](../0003-data-model-mvp/index.md) AC-12 stay unused by sync, which is a readability cost today for a saved async-worker migration later ([0003](../0003-data-model-mvp/index.md) `## Consequences` already acknowledges this).
- `execution.target_not_registered` conflates "unknown target id" with "target under a different website" into one 404. A caller cannot distinguish the two; this is deliberate (the public response does not need to leak whether a specific id exists under some other website), but it does make operator triage slightly less precise. A log line names the distinction when it matters.
- A `500 execution.terminal_persist_failed` leaves a `running` row behind. In the MVP this is rare and visible via `GET /executions/{id}`; a reconciliation job is deferred (Follow-up).

**Neutral**

- No new third-party dependencies: everything builds on `httpx`, `jsonschema`, `selectolax`, SQLAlchemy 2, Pydantic v2, and Postgres 16 already pinned by [0001](../0001-stack-and-architecture/index.md) and [0005](../0005-deterministic-html-extraction/index.md).
- Idempotency is not shipped; retried executes create duplicate rows. Operators can see duplicates in the executions list by `(workflow_version_id, target_url_id, created_at)`. An `Idempotency-Key` header is captured in Follow-up for a later spec.
- No rate limiting (feature 21), no retries or breakers (feature 20), no SSRF guards (feature 27). The gaps are visible from the Security model and acknowledged in Follow-up.

## Follow-up

- [ ] Flag to feature 11 (`/architect execution browser`): the full list surface (filters on workflow, target, status, time range; cursor pagination over the `(status, created_at DESC)` and `(workflow_version_id, created_at DESC)` indexes) is owned by feature 11. The GET-by-id shape here is the detail view feature 11 will link to.
- [ ] Flag to feature 23 (`/architect job queue & worker pool`): `ExecutionService.execute(...)` is the reusable core; the async path replaces the sync "two-commit in one request" wrapper and uses the full `pending → running → completed | failed` state machine from [0003](../0003-data-model-mvp/index.md) AC-12. The async worker is also the owner of the `pending → failed` validation-reject path, which the sync endpoint deliberately does not use (AC-6).
- [ ] Flag to feature 17 (`/architect deterministic-first execution with agent fallback`): when agent-assisted repair lands, it will wrap `ExecutionService.execute(...)` with "run deterministic; on `extraction.*` failure, invoke agent repair, validate, persist a new version, re-execute". The persisted `executions.error_code` prefix (`fetch.*` vs `extraction.*`) is the signal that decides whether to retry the fetch or repair the selectors.
- [ ] Reconciliation of `running` rows left by a crashed process or a `500 execution.terminal_persist_failed`. Likely a slice 3 or slice 6 topic; captures the "mark `running` rows older than N minutes as `failed` with `error_code='execution.orphaned'`" sweep.
- [ ] `Idempotency-Key` header on `POST /execute`, with a 24h dedupe window. Its own spec; depends on a key store (likely cache slice).
- [ ] A denormalised `scraping_workflows.id` column on `executions` would remove the join to `workflow_versions` on the GET-by-id path (AC-7's `execution.workflow_id`). Not needed for MVP volumes; worth revisiting when feature 11's list queries show the join cost.
- [ ] A `GET /workflows/{id}/executions` list endpoint would overlap with feature 11; held here on purpose. Revisit if feature 7's own tests or the Admin UI (feature 9) need a quick list before feature 11 ships.
- [ ] `/sync` note: this spec's `GET /executions/{id}` adds the first read surface over the executions table from an endpoint feature. If feature 11 later chooses a different URL (`/api/v1/executions/{id}` here; feature 11 might want a nested `/workflows/{id}/executions/{eid}`), align them when feature 11 lands.
