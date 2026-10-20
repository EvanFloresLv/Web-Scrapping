# 0006. Workflow execution endpoint (sync) — rationale

## Context

Slice 1's deterministic MVP is one step away from end-to-end. Feature 4 ([0002](../0002-website-target-registration/index.md)) registers websites and target URLs; feature 5 ([0004](../0004-workflow-configuration-versioning/index.md)) creates, versions, and publishes workflows; feature 6 ([0005](../0005-deterministic-html-extraction/index.md)) ships a pure `ExtractionService.run(workflow_version, target_url) -> ExtractionResult` plus a non-persistent preview endpoint. Feature 7 is the piece that persists an actual run.

The data model for executions is already pinned by [0003](../0003-data-model-mvp/index.md): `executions` and `execution_results` tables, UUIDv7 ids, append-only with CASCADE from execution to its results, the `pending → running → completed | failed` state machine, correlation-id persistence, the `error_code` registry convention. The extraction behavior is pinned by [0005](../0005-deterministic-html-extraction/index.md): one in-process service, `FetchErrorCode` / `ExtractionErrorCode` enums, a known error vocabulary.

Everything load-bearing about data and extraction is settled. What this spec decides is the HTTP shape of a persisted execution: which endpoints to ship, how the caller names the version and target, when the row is inserted and committed relative to the extraction call, what to do when pre-run validation rejects a request, and what shape the response takes on both success and run-failure.

## Options considered

### How broad is the HTTP surface?

**Option 1 (chosen)**: `POST /workflows/{id}/execute` + `GET /executions/{id}`. The POST returns the full execution row and items inline; GET-by-id lets operators and tests inspect a run after the fact. Full list and filter surface stays with feature 11.

**Option 2**: POST only. The response already includes the full result, so there is nothing to look up in sync mode. Rejected: tests, scripts, and the Admin UI (feature 10) all need to resolve an id back to a row at some point; forcing a round trip through a DB client is a bad default.

**Option 3**: POST + GET-by-id + `GET /workflows/{id}/executions` list. Rejected: the per-workflow list overlaps feature 11, which will add filters and cursor pagination anyway. Shipping it now would mean replacing it later or absorbing a second implementation.

### How does the caller name the target URL?

**Option 1 (chosen)**: `target_url_id: UUID` only. The caller already registered the target (feature 4) and holds its id; direct FK lookup. Unambiguous, one validation path.

**Option 2**: `target_url: str`, canonicalized like the preview endpoint ([0005](../0005-deterministic-html-extraction/index.md) AC-3). Rejected for this endpoint: duplicates `CanonicalURL` resolution at every execute call and spreads the canonicalization error paths across two endpoints. The preview endpoint keeps the URL-string shape because it is an operator-facing probe; the execute endpoint is a programmatic surface the Admin UI will call with ids.

**Option 3**: accept both. Rejected: widens the error surface for little benefit at MVP.

### Which version runs when `version_id` is omitted?

**Option 1 (chosen)**: use `scraping_workflows.current_version_id`; NULL → `409 execution.workflow_not_runnable`. Matches [0003](../0003-data-model-mvp/index.md) AC-4 verbatim: `current_version_id` is "the version that `POST /workflows/{id}/execute` uses when the caller omits a version".

**Option 2**: require `version_id` in every request. Rejected: forces every caller to make a prior lookup just to call the endpoint; defeats the purpose of `current_version_id`.

### Which version statuses may run when `version_id` is explicit?

**Option 1 (chosen)**: `published` only. Draft → `409 execution.version_not_published` (use preview to iterate). Archived → `409 execution.version_archived` ([0003](../0003-data-model-mvp/index.md) AC-12: "not runnable for new executions"). Keeps every persisted execution tied to a published version, which is what the audit trail is for.

**Option 2**: `published` + `draft` (preview parity). Rejected: mixes exploratory and audit executions in one table; feature 11 would need a filter to hide draft runs from the operational view.

**Option 3**: `published` + `archived` (reproduce old runs). Rejected: contradicts [0003](../0003-data-model-mvp/index.md) AC-12; reproducibility is better served by a dedicated "replay" endpoint when a feature actually needs it.

### When is the executions row inserted and committed, relative to the extraction call?

**Option 1 (chosen)**: insert `running` + commit, run extraction, UPDATE terminal + commit. Two commits per request. Durable from the moment work starts; a process crash mid-fetch leaves a `running` row the operator can see.

**Option 2**: run extraction first, then insert the terminal row in one commit. Rejected: a crash mid-fetch leaves no trace; `running` becomes unreachable in sync mode. The one saved commit is not worth losing the attempt record.

**Option 3**: three commits using the full `pending → running → completed | failed` machine. Rejected as over-engineered: the row is `running` for microseconds in sync; the `pending` state is for the async worker.

### What happens on pre-run validation failure?

**Option 1 (chosen)**: 4xx with Problem Details, no row persisted. Keeps the executions table a record of actual run attempts. The `pending → failed` validation-reject path from [0003](../0003-data-model-mvp/index.md) AC-12 stays reserved for the async worker (feature 23), which cannot return 4xx to the enqueuer.

**Option 2**: persist a `pending → failed` row and return 4xx. Rejected: adds noise to the executions table; feature 11's lists would need to filter out these rows.

**Option 3**: persist a `pending → failed` row and return 200. Rejected: hides HTTP-shape errors behind JSON errors; harder to use from scripts and curl.

### What HTTP status for a failed run (one that executed but produced an `ExtractionResult.status='failed'`)?

**Option 1 (chosen)**: `200` with `status='failed'` in the body. The API operation succeeded (the execution ran and was persisted); the job's result is failed. Mirrors preview ([0005](../0005-deterministic-html-extraction/index.md) AC-2); keeps HTTP semantics about the API layer.

**Option 2**: `502` for `fetch.*`, `422` for `extraction.*`, Problem Details body. Rejected: muddles "the API failed" and "the scrape failed"; preview and execute would then disagree on how to report the same failure class.

### Response shape

**Option 1 (chosen)**: `{execution: {...row...}, items: [...]}` on both POST success and GET by id. One shape to document, one Pydantic model, one round trip for the full picture.

**Option 2**: execution row only; items fetched via a second endpoint. Rejected: breaks the "synchronous" promise of the endpoint.

**Option 3**: reuse `ExtractionResult` shape ([0005](../0005-deterministic-html-extraction/index.md) AC-1) + an `execution_id`. Rejected: hides execution metadata (`correlation_id`, `started_at`, `created_at`) that callers often need; divergence from the preview shape is deliberate here.

### Target scoping

**Option 1 (chosen)**: `target.website_id = workflow.website_id`; mismatch → `404 execution.target_not_registered`. Matches [0005](../0005-deterministic-html-extraction/index.md) AC-3 and the workflow→website binding from [0003](../0003-data-model-mvp/index.md) AC-3.

**Option 2**: any registered `target_url_id` is accepted. Rejected: breaks the audit model; a workflow for site A could run against site B's targets.

### Idempotency

**Option 1 (chosen)**: not shipped in this feature; Follow-up for an `Idempotency-Key` header spec. Keeps MVP small; duplicates are visible in the executions list.

**Option 2**: ship `Idempotency-Key` now with a 24h dedupe window. Rejected: needs a key store (table or Redis) and a replay path; nontrivial for an MVP where retries are rare.

### Request budget beyond the fetch cap

**Option 1 (chosen)**: no new setting; the extraction fetch cap (`EXTRACTION_HTTP_TOTAL_TIMEOUT_S`, default 20s, from [0005](../0005-deterministic-html-extraction/index.md) AC-4) plus bounded parse/extract/validate on a capped 10MB body is the budget. One fewer setting to tune.

**Option 2**: add `EXECUTION_SYNC_TOTAL_BUDGET_S`. Rejected for MVP; hard wall-clock caps are feature 20's territory (retries, timeouts, breakers).

## Rationale

The one real design choice this feature makes is the lifecycle shape: insert `running` and commit before invoking the extraction service, UPDATE and commit the terminal state after. Everything else cascades from decisions already made in [0003](../0003-data-model-mvp/index.md), [0004](../0004-workflow-configuration-versioning/index.md), and [0005](../0005-deterministic-html-extraction/index.md).

Durability-first is the right call for an endpoint that persists history. A process can crash between a `httpx` request and its response; the DB can be fine when that happens; losing the row of a request that definitely started is a worse failure than paying one extra round-trip. The `running` state exists in the schema precisely so that this gap is observable. Feature 11 will show "running longer than expected" rows; a reconciliation sweep (Follow-up) will mark them `failed` with an `execution.orphaned` code. The design keeps the door open.

4xx-with-no-row keeps the executions table honest. Operators who typo an id get an immediate HTTP error; they do not pollute the history that feature 11, feature 15, and feature 18 all read for operational decisions. The `pending → failed` validation-reject path from [0003](../0003-data-model-mvp/index.md) AC-12 is not deleted; it is deferred to the async worker, where the enqueuer cannot see a 4xx and the row is the only visible record.

`200` for a run-failure keeps HTTP semantics about the API, not the job. Scripts that do `response.raise_for_status()` are not asking "did the scrape succeed", they are asking "did my API call go through". Preview ([0005](../0005-deterministic-html-extraction/index.md) AC-2) uses the same posture; execute matches so a caller never has to context-switch between the two.

The `target_url_id`-only body is the one place where execute diverges from preview on purpose. Preview is an operator-facing probe where typing a URL is faster than looking up an id. Execute is a programmatic surface the Admin UI (feature 10) and future workers will call with ids. Keeping the resolution semantics separate avoids leaking preview's URL canonicalization errors into the execute endpoint's error vocabulary.

`GET /executions/{id}` is a stopgap. Feature 11 will build the real browser with filters, pagination, and nested result reads. Shipping it here means tests, scripts, and the first draft of the Admin UI do not have to wait or query the DB directly; the surface is small enough (one route, one shape) that aligning with feature 11 later is a rename, not a redesign.

## References

Internal (within this repo):

- [0001](../0001-stack-and-architecture/index.md) — stack, request-scoped async session, correlation-id middleware, UUIDv7 generator, pydantic-settings, structlog.
- [0002](../0002-website-target-registration/index.md) — `target_urls`, `CanonicalURL`, soft-delete semantics.
- [0003](../0003-data-model-mvp/index.md) — `executions` and `execution_results` shape (AC-6, AC-7), state machine (AC-12), FK policies (AC-10), audit fields (AC-9), error-code registry convention (AC-17), default repository filter (AC-20).
- [0004](../0004-workflow-configuration-versioning/index.md) — workflow and version resolution, `workflow_not_found` / `version_not_found` codes (AC-15), Problem Details shape (AC-13).
- [0005](../0005-deterministic-html-extraction/index.md) — `ExtractionService.run(...)`, `ExtractionResult`, `FetchErrorCode`, `ExtractionErrorCode` (AC-14), observability pattern (AC-15).

External: none fetched. Conventions and APIs used (FastAPI dependency injection, SQLAlchemy 2 async session, httpx, Pydantic v2) are the stack pinned in `AGENTS.md` and used throughout the existing codebase.
