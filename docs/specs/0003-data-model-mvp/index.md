# 0003. Data model (MVP entities)

**Date**: 2026-10-19
**Status**: Accepted

## Summary

This spec pins the shape of every MVP data entity (the tables the first three slices of the platform read and write) as one cohesive target before any slice builds. It covers `scraping_workflows`, `workflow_versions`, `executions`, and `execution_results` in full here; `websites` and `target_urls` are owned by spec [0002](../0002-website-target-registration.md) and referenced, not re-specified. Each later slice (features 5, 6, 7) ships its own Alembic migration against this target, so a slice can be reverted on its own, but no slice invents a new table shape. Audit fields, FK policies, and lifecycle states follow the conventions pinned in [0001](../0001-stack-and-architecture/index.md).

## Requirements

**User stories**

- As a platform engineer building a slice feature, I want the data model for every MVP entity to be settled upfront, so that my slice's migration is a mechanical translation of this spec and not a fresh design round.
- As a platform engineer building the deterministic executor (feature 6), I want workflow configuration to be one atomic JSONB document on `workflow_versions`, so that reading a version is one row and reconstructing it needs no joins.
- As a platform engineer building the execution endpoint (feature 7), I want every execution attempt (including failures) to persist exactly one `executions` row, so that the execution browser (feature 11) can list and filter failures the same way as successes.
- As a platform operator, I want historical executions to stay joinable to the workflow version and target URL that produced them, so that provenance survives soft deletes of parent rows.

**Acceptance criteria** (the contract later slice specs build to)

- **AC-1**: The MVP data model is `websites`, `target_urls`, `scraping_workflows`, `workflow_versions`, `executions`, `execution_results`. `websites` and `target_urls` are specified by [0002](../0002-website-target-registration.md) and are not re-specified here; the other four tables are specified in `## Feature design` below.
- **AC-2**: `scraping_workflows` is the mutable aggregate root for a workflow (name, description, website binding, lifecycle status, audit fields). `workflow_versions` is an immutable child: once a row is written with `status='published'`, its `config` JSONB and every other content column is write once; the row is never updated except by lifecycle moves (`draft→published`, `published→archived`).
- **AC-3**: A workflow belongs to exactly one website: `scraping_workflows.website_id` is a `NOT NULL` FK to `websites.id` with `ON DELETE RESTRICT`. A workflow is reusable across every `target_url` under that website; the binding to a specific target happens at execution time.
- **AC-4**: `scraping_workflows.current_version_id` is a `NULL`able FK to `workflow_versions.id` naming the version that `POST /workflows/{id}/execute` uses when the caller omits a version. The pointer is set by the workflow service when a version transitions to `published`; swapping it is one atomic row update.
- **AC-5**: `workflow_versions.config` is a `JSONB NOT NULL` document validated at write time by a Pydantic `WorkflowConfig` model (one shape, versioned by the spec, not by a JSON schema version column). The model defines at least: `container_selector:str`, `fields: list[{name:str, selector:str, transforms:list[str], type:str}]`, `output_schema: dict`, and optional `pagination: {next_selector:str, max_pages:int} | None`. The model is configured with `extra='allow'` so a historical row never fails validation on read when a new optional field lands. Changes to `WorkflowConfig` are additive only (new optional fields) until a superseding spec defines a `config_version` column plus a backfill plan. No separate `extraction_rules` table exists; rules are embedded.
- **AC-6**: `executions` row shape: `id` (UUIDv7), `workflow_version_id` FK (RESTRICT), `target_url_id` FK (RESTRICT), `status` enum (`pending`|`running`|`completed`|`failed`), `started_at`, `finished_at`, `duration_ms` (nullable until terminal), `error_code` text (nullable; drawn from the registry pinned by AC-17), `error_message` text (nullable), `items_extracted` int (default 0), `correlation_id` text (NOT NULL; sourced from the `asgi-correlation-id` middleware context when the execution starts from an HTTP request; when the execution is started outside a request, e.g. the async worker added by feature 23 or a startup/cron hook, the executor service mints a fresh UUIDv7 and binds it to the structlog contextvar before inserting the row), `created_at`, `updated_at`. The row is immutable after it reaches a terminal status (`completed` or `failed`).
- **AC-7**: `execution_results` row shape: `id` (UUIDv7), `execution_id` FK (`ON DELETE CASCADE`), `item_index` int (0 based, orders items within one execution), `payload` JSONB (the extracted item matching the workflow version's `output_schema`), `created_at`. One `execution_results` row per extracted item; a failed execution has zero rows; the row is immutable (append only, never updated).
- **AC-8**: Primary keys everywhere are UUIDv7 generated application side (per [0001](../0001-stack-and-architecture/index.md), using the generator established by that spec's scaffold).
- **AC-9**: Audit fields on every entity: `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` maintained by SQLAlchemy `onupdate` (ORM only; any raw SQL `UPDATE` that bypasses the ORM must set `updated_at` by hand, and the project convention is to go through the repository, never raw SQL in production code). Soft delete (`deleted_at TIMESTAMPTZ NULL`) applies only to `scraping_workflows` (and the two tables already covered by 0002). `workflow_versions`, `executions`, `execution_results` are immutable records and are not soft deletable; hard delete happens only via a future retention job.
- **AC-10**: FK `ON DELETE` policies: `workflow_versions.workflow_id` RESTRICT. `executions.workflow_version_id` RESTRICT. `executions.target_url_id` RESTRICT. `execution_results.execution_id` CASCADE. The RESTRICT policies make history unbreakable: a workflow with executions cannot be hard deleted; it can only be soft deleted.
- **AC-11**: Soft deleting a `scraping_workflows` row cascades to its `workflow_versions`, `executions`, and `execution_results` logically (service layer treats them as hidden), not physically. No DB CASCADE on these FKs. This mirrors the website→targets cascade pattern established by [0002](../0002-website-target-registration.md).
- **AC-12**: State transitions. `scraping_workflows.status`: `active ⇄ inactive`; `deleted` via soft delete; terminal from the API's perspective. `workflow_versions.status`: `draft → published → archived`; one way after `published`; a `draft` version is editable in place and hard deletable (DELETE row) until it reaches `published`; a `published` version is immutable; an `archived` version is readable but not runnable for new executions (historical reproducibility only). `draft → archived` is not permitted (archive is for retired published work, not abandoned drafts; use hard delete instead); `archived → draft` and `archived → published` are not permitted (archival is terminal). `executions.status`: `pending → running → completed | failed`, plus `pending → failed` when validation fails before the run starts; `completed` and `failed` are terminal and immutable.
- **AC-13**: Immutable fields after creation: `scraping_workflows.website_id`; `workflow_versions.workflow_id`, `workflow_versions.version_number`, `workflow_versions.config` (once `status='published'`); every column on `executions` after it reaches a terminal status; every column on `execution_results`.
- **AC-14**: Indexes required by the MVP read paths: on `scraping_workflows`: `(website_id)`, `UNIQUE (website_id, name) WHERE deleted_at IS NULL`. On `workflow_versions`: `UNIQUE (workflow_id, version_number)`, `(workflow_id, status)`. On `executions`: `(workflow_version_id, created_at DESC)`, `(target_url_id, created_at DESC)`, `(status, created_at DESC)` (the execution browser's three filters). On `execution_results`: `UNIQUE (execution_id, item_index)`.
- **AC-15**: Each later slice spec (features 5, 6, 7) ships its own Alembic migration for the tables it uses and the shape of that migration conforms to this spec exactly; adding or renaming a column requires updating this spec first via `/architect` (either an edit here or a superseding spec).
- **AC-16**: Concurrency rules the workflow and execution services enforce:
  - **Assigning the next `version_number`**: the service runs `SELECT id FROM scraping_workflows WHERE id = ? FOR UPDATE` inside the insert transaction, computes `MAX(version_number) + 1 WHERE workflow_id = ?`, then inserts. On a lost-race `IntegrityError` against the `UNIQUE (workflow_id, version_number)` index, the service retries once (same transaction scope); a second violation surfaces as a `409 Conflict` with a stable `code=version_conflict`.
  - **Publishing a draft**: `publish(version_id)` opens a transaction, takes `SELECT ... FOR UPDATE` on the parent `scraping_workflows` row, archives the currently-current version (`UPDATE workflow_versions SET status='archived', archived_at=now() WHERE id = scraping_workflows.current_version_id AND status='published'`), promotes the draft (`UPDATE workflow_versions SET status='published', published_at=now() WHERE id = ?`), and swaps `scraping_workflows.current_version_id` to the new version id, all in one commit. Two concurrent publishes on the same workflow serialize behind the row lock; the second one sees the first's result and either succeeds (publishing a different draft) or fails with `409` if its draft was already superseded.
  - **Invariant**: at most one `workflow_versions` row per `workflow_id` has `status='published'` at any time (enforced by the publish flow above; not a DB constraint, since the archive and promote happen in the same transaction).
- **AC-17**: `executions.error_code` values are drawn from a central registry defined in `src/app/core/errors/execution_codes.py`. The registry uses domain-prefixed dotted codes: `fetch.*` for HTTP fetch failures, `extraction.*` for extractor failures (feature 6), `execution.*` for executor-service failures (feature 7), `agent.*` for LLM-assisted paths (feature 15+). The column stays `text` with no DB `CHECK` constraint so new codes do not require a migration; the registry file is the source of truth and every writer imports from it. Feature 6, feature 7, feature 15, and feature 17 each extend the registry with their own prefix.
- **AC-18**: Soft deleting a `scraping_workflows` row is refused by the service layer with a stable `code=workflow_has_in_flight_executions` while any execution of its versions has `status IN ('pending','running')`; the operator must wait for or cancel the in-flight runs first. Once allowed, soft delete marks the workflow deleted and hides its versions, executions, and results from the API; the physical rows stay joinable for history.
- **AC-19**: The logical identity of a target for cross-registration history is `(website_id, canonical url)`, not `target_urls.id`. When a target is soft deleted and the same URL is re-registered (per spec [0002](../0002-website-target-registration.md) AC-12), the new row gets a fresh `id`; old executions still reference the old `id`. Feature 11's "all executions for this URL" read must join via `target_urls` including soft-deleted rows and group by canonical URL, not by `target_url_id` alone.
- **AC-20**: Default repository read filters: every `list` and `get` on `scraping_workflows`, `workflow_versions`, `executions`, and `execution_results` filters out logically-deleted parents (`WHERE scraping_workflows.deleted_at IS NULL` applied through the join chain). An explicit `with_deleted=True` keyword is required to opt into history reads (used only by feature 18's provenance queries and future retention jobs).

## Decision

**Chosen option**: Option 1: Umbrella data model spec that pins every MVP entity as a cohesive target; each slice ships its own migration against the pinned shape.

The platform's full MVP catalog shape is settled here before any slice builds, so slice features (5, 6, 7) are pure service and router work with mechanical migrations. Workflow and version are split (`scraping_workflows` + `workflow_versions`), extraction rules are embedded as JSONB inside `workflow_versions.config`, executions and results are append only with cascade only from execution to its results, and audit and lifecycle conventions follow [0001](../0001-stack-and-architecture/index.md).

**Implementation skills**: `sqlalchemy-alembic-expert-best-practices-code-review` (`wispbit-ai/skills`, `.claude/skills/sqlalchemy-alembic-expert-best-practices-code-review/`) · `modern-python` (`trailofbits/skills`, `.claude/skills/modern-python/`) · `python-testing-patterns` (`wshobson/agents`, `.claude/skills/python-testing-patterns/`)

## Rationale

Reasoning and options considered: see [`rationale.md`](rationale.md).

## Feature design

**Data model sketch**

`websites`, `target_urls`: specified in full by [0002](../0002-website-target-registration.md). Not restated here. This spec treats their IDs and host/url columns as fixed.

`scraping_workflows`

| Column | Type | Constraints |
|---|---|---|
| `id` | `uuid` | PK, UUIDv7 generated application side |
| `website_id` | `uuid` | NOT NULL, FK → `websites(id)` ON DELETE RESTRICT, indexed |
| `name` | `text` | NOT NULL, CHECK length 1..200 |
| `description` | `text` | NULL, CHECK length ≤ 2000 |
| `current_version_id` | `uuid` | NULL, FK → `workflow_versions(id)` ON DELETE RESTRICT, deferred initially (nullable until first publish) |
| `status` | `text` | NOT NULL, CHECK `status IN ('active','inactive')`, default `'active'` |
| `created_at` | `timestamptz` | NOT NULL, server default `now()` |
| `updated_at` | `timestamptz` | NOT NULL, SQLAlchemy `onupdate` |
| `deleted_at` | `timestamptz` | NULL (soft delete) |

Indexes: `(website_id)`; `UNIQUE (website_id, name) WHERE deleted_at IS NULL` (one workflow name per website at a time, re registrable after soft delete).

`workflow_versions`

| Column | Type | Constraints |
|---|---|---|
| `id` | `uuid` | PK, UUIDv7 |
| `workflow_id` | `uuid` | NOT NULL, FK → `scraping_workflows(id)` ON DELETE RESTRICT, indexed |
| `version_number` | `int` | NOT NULL, CHECK ≥ 1 |
| `status` | `text` | NOT NULL, CHECK `status IN ('draft','published','archived')`, default `'draft'` |
| `config` | `jsonb` | NOT NULL, validated by `WorkflowConfig` Pydantic model at write time |
| `published_at` | `timestamptz` | NULL (set when transitioning to `published`) |
| `archived_at` | `timestamptz` | NULL (set when transitioning to `archived`) |
| `created_at` | `timestamptz` | NOT NULL, server default `now()` |
| `updated_at` | `timestamptz` | NOT NULL, SQLAlchemy `onupdate` |

Indexes: `UNIQUE (workflow_id, version_number)` (version numbers are unique per workflow and monotonically assigned by the service layer); `(workflow_id, status)` (lookups like "the published versions of this workflow").

`executions`

| Column | Type | Constraints |
|---|---|---|
| `id` | `uuid` | PK, UUIDv7 |
| `workflow_version_id` | `uuid` | NOT NULL, FK → `workflow_versions(id)` ON DELETE RESTRICT, indexed |
| `target_url_id` | `uuid` | NOT NULL, FK → `target_urls(id)` ON DELETE RESTRICT, indexed |
| `status` | `text` | NOT NULL, CHECK `status IN ('pending','running','completed','failed')`, default `'pending'` |
| `started_at` | `timestamptz` | NULL (set at `running`) |
| `finished_at` | `timestamptz` | NULL (set at terminal) |
| `duration_ms` | `int` | NULL (computed at terminal, `finished_at − started_at`) |
| `items_extracted` | `int` | NOT NULL, default 0 |
| `error_code` | `text` | NULL (stable per domain enum when `status='failed'`) |
| `error_message` | `text` | NULL (human message when `status='failed'`, CHECK length ≤ 4000) |
| `correlation_id` | `text` | NOT NULL (the `X-Request-ID` bound by the middleware pinned in 0001) |
| `created_at` | `timestamptz` | NOT NULL, server default `now()` |
| `updated_at` | `timestamptz` | NOT NULL, SQLAlchemy `onupdate` |

Indexes: `(workflow_version_id, created_at DESC)`; `(target_url_id, created_at DESC)`; `(status, created_at DESC)` (the three filter axes feature 11, the execution browser, requires).

`execution_results`

| Column | Type | Constraints |
|---|---|---|
| `id` | `uuid` | PK, UUIDv7 |
| `execution_id` | `uuid` | NOT NULL, FK → `executions(id)` ON DELETE CASCADE, indexed |
| `item_index` | `int` | NOT NULL, CHECK ≥ 0 |
| `payload` | `jsonb` | NOT NULL (one extracted item matching the version's `output_schema`) |
| `created_at` | `timestamptz` | NOT NULL, server default `now()` |

Indexes: `UNIQUE (execution_id, item_index)` (also covers the common "all results for this execution, in order" read).

**Relationships**

- `websites` 1 — N `scraping_workflows` (RESTRICT on hard delete; soft delete cascades at service layer).
- `scraping_workflows` 1 — N `workflow_versions` (RESTRICT); `scraping_workflows.current_version_id` is a convenience FK back into one of its versions.
- `websites` 1 — N `target_urls` (per 0002).
- `workflow_versions` 1 — N `executions` (RESTRICT).
- `target_urls` 1 — N `executions` (RESTRICT).
- `executions` 1 — N `execution_results` (CASCADE).

**State transitions**

```
scraping_workflows
    active ───PATCH status───▶ inactive
            ◀──PATCH status──
        │
        └── DELETE ──▶ (soft-deleted; invisible to API)

workflow_versions
    draft ──publish──▶ published ──archive──▶ archived
    (editable)        (immutable, runnable) (immutable, readable only)

executions
    pending ──start──▶ running ──complete──▶ completed  (terminal, immutable)
                            └──fail──────▶ failed      (terminal, immutable)
```

A `draft` version is editable in place by the workflow service (feature 5); the moment it transitions to `published`, every content column is write once. An `archived` version is kept so historical executions remain reproducible; new executions against an archived version are refused by the executor service.

**API surface**

This spec is a pure data model spec; no HTTP endpoints are defined here. The endpoints that read and write these tables are owned by the slice specs that build on top: feature 5 (`/api/v1/workflows`, `/api/v1/workflows/{id}/versions`), feature 7 (`/api/v1/workflows/{id}/execute`, `/api/v1/executions`, `/api/v1/executions/{id}`), feature 11 (admin UI reads over the same tables). Each slice spec defines its own API table and value sourcing table against the shape pinned here.

**Value sourcing** (the values this spec's model produces, and where each comes from)

| Action | Value produced / stored | Source |
|---|---|---|
| Insert `scraping_workflows` | `id` | Application UUIDv7 via the generator established in 0001's scaffold (reused, not duplicated) |
| Insert `scraping_workflows` | `status` | Default `'active'` (DB default) |
| Insert `scraping_workflows` | `created_at`, `updated_at` | Server side `now()` (DB default + SQLAlchemy `onupdate`) |
| Insert `scraping_workflows` | `current_version_id` | NULL at creation; set by the workflow service when a `workflow_versions` row transitions to `published` |
| Insert `workflow_versions` | `version_number` | Monotonic per workflow, assigned by the workflow service as `MAX(version_number) + 1 WHERE workflow_id = ?` inside the insert transaction, guarded by `SELECT ... FOR UPDATE` on the parent `scraping_workflows` row (AC-16); on a lost-race unique violation, the service retries once |
| Insert `workflow_versions` | `config` | Request payload, validated by `WorkflowConfig` Pydantic model (see AC-5) before insert; a rejected payload returns `422` Problem Details |
| Transition `workflow_versions → published` | `published_at` | `now()` set by the workflow service in the same `UPDATE` |
| Transition `workflow_versions → archived` | `archived_at` | `now()` set by the workflow service |
| Insert `executions` | `correlation_id` | Request scoped structlog contextvar bound by the `asgi-correlation-id` middleware (per 0001) when the execution starts inside an HTTP request; when started outside a request (feature 23 async worker, a cron hook, a startup task), the executor service mints a fresh UUIDv7 and binds it to the structlog contextvar before the insert, so every execution row has a non-null correlation id and the log line for the run shares it (AC-6) |
| Insert `executions` | `status` | `'pending'` at creation (sync executor transitions straight to `running` then terminal within one request; async executor added by feature 23 uses the full state machine) |
| Transition `executions → running` | `started_at` | `now()` set by the executor service |
| Transition `executions → terminal` | `finished_at`, `duration_ms` | `now()` set as `finished_at`; `duration_ms = finished_at − started_at` on the normal path (ran then terminal); on `pending → failed` before start (e.g. a validation reject), `started_at` stays NULL and `duration_ms = finished_at − created_at` |
| Transition `executions → failed` | `error_code`, `error_message` | `error_code` from the per domain error enum defined by feature 7; `error_message` from the exception's message (truncated to 4000 chars at the service layer) |
| Insert `executions` | `items_extracted` | 0 at creation; updated to the final count at terminal in the same `UPDATE` as `finished_at` |
| Insert `execution_results` | `item_index` | Zero based ordinal assigned by the executor service as it iterates the container selector matches |
| Insert `execution_results` | `payload` | The extracted item dict produced by the deterministic extractor (feature 6), already matching the version's `output_schema` |

**Key invariants**

- Every `workflow_versions` row with `status='published'` has `published_at IS NOT NULL`; every row with `status='archived'` has both `published_at` and `archived_at` NOT NULL.
- A `workflow_versions.config` is only written for `status='draft'`; once the row transitions to `published`, `config` is immutable (enforced at the service layer; AC-13).
- An `executions` row with `status IN ('completed','failed')` has `finished_at IS NOT NULL AND duration_ms IS NOT NULL`. `started_at IS NOT NULL` holds for `status='completed'` and for `status='failed'` on the normal path; `started_at IS NULL` is allowed for `status='failed'` on the `pending → failed` validation-reject path.
- An `executions` row with `status='failed'` has `error_code IS NOT NULL`; one with `status='completed'` has `error_code IS NULL`.
- At most one `workflow_versions` row per `workflow_id` has `status='published'` at any time (service-layer invariant, AC-16).
- A `scraping_workflows` row can only be soft deleted when zero of its executions are in `pending` or `running` (AC-18).
- `execution_results.item_index` is a dense zero based sequence per `execution_id` (`item_index` 0..N-1 where N = `items_extracted` on the parent).
- A `scraping_workflows.current_version_id`, when NOT NULL, references a `workflow_versions` row whose `workflow_id` equals this row's `id` and whose `status = 'published'` (checked at the service layer; AC-4).
- `workflow_versions.workflow_id`, `workflow_versions.version_number`, `executions.workflow_version_id`, `executions.target_url_id`, and every column of `execution_results` are immutable after insert.

**Security model**

- No new authn or authz introduced by this spec; the tables inherit the open on localhost assumption of the MVP. Feature 26 (slice 11) adds real API key auth in front of every endpoint that reads or writes these tables.
- No regulated data: workflow names, extraction config, and extracted catalog payloads are not PII and carry no secrets. If a future slice persists customer credentials or PII inside `execution_results.payload`, that slice's spec must add a column level encryption decision; this spec deliberately does not.
- `correlation_id` on `executions` is a request trace identifier, not an auth token; it is safe to log and return.

**Configuration required**

None. The schema uses only existing settings pinned in [0001](../0001-stack-and-architecture/index.md) (DB URL, UUIDv7 generator, timezone, JSON encoding).

**Critical test scenarios** (each maps to an acceptance criterion)

- Workflow created under a website: `POST /workflows {website_id, name}` persists a `scraping_workflows` row with `status='active'`, `current_version_id=NULL`, matching audit fields; a duplicate `(website_id, name)` while the first is live returns `409`. Verifies **AC-2**, **AC-3**, **AC-14**.
- Version lifecycle: creating a draft, publishing it, then publishing a second draft swaps `scraping_workflows.current_version_id` to the new version atomically; the old version becomes `archived` (not required but allowed). Verifies **AC-2**, **AC-4**, **AC-12**.
- Config validation: a `workflow_versions` insert with a `config` missing `container_selector` is rejected before the DB write with a Pydantic `422`; the row is never created. Verifies **AC-5**.
- Immutability of published versions: an `UPDATE workflow_versions SET config=... WHERE id=... AND status='published'` is rejected by the service layer with an `ImmutableFieldError`. Verifies **AC-13**.
- Execution happy path: `POST /workflows/{id}/execute {target_url_id}` persists one `executions` row that transitions `pending → running → completed` and three `execution_results` rows with `item_index` 0, 1, 2 and `items_extracted=3` on the parent. Verifies **AC-6**, **AC-7**, **AC-14**.
- Execution failure: an executor exception persists one `executions` row with `status='failed'`, `error_code` set, `finished_at` set, zero `execution_results`. Verifies **AC-6**, **AC-7**.
- Cascade behavior on hard delete attempt: `DELETE FROM scraping_workflows WHERE id=...` on a workflow with versions fails with a FK violation (RESTRICT); the soft delete path on the service layer succeeds and marks the workflow row deleted while leaving versions/executions physically present. Verifies **AC-10**, **AC-11**.
- Result deletion: `DELETE FROM executions WHERE id=...` deletes all its `execution_results` by CASCADE in the same transaction. Verifies **AC-10**.
- Historical joinability: after soft deleting a workflow, a read `SELECT ... FROM executions e JOIN workflow_versions v ON e.workflow_version_id=v.id WHERE v.workflow_id=?` still returns every past execution (physical rows preserved). Verifies **AC-11**.
- Correlation ID round trip: an `executions` row persists the current request's `X-Request-ID`; the structured log line for the execution shares the same value. Verifies **AC-6**.
- Unique index on results: a race that attempts to insert two `execution_results` with the same `(execution_id, item_index)` is rejected by the UNIQUE index. Verifies **AC-14**.
- Concurrent publish: two threads call `publish()` on two different drafts of the same workflow simultaneously; one commits, the other sees the first's `current_version_id` under its `SELECT FOR UPDATE` and either succeeds (publishing a different draft, which auto-archives the one the first thread published) or returns `409` if its draft was already superseded; at every moment at most one row per `workflow_id` has `status='published'`. Verifies **AC-16**.
- Concurrent version insert: two threads insert a new version under the same workflow at the same time; the row lock serializes them, both get consecutive `version_number` values, no `IntegrityError` escapes; a simulated lost-race scenario (bypassing the lock in a test) triggers the one-shot retry. Verifies **AC-16**.
- Soft delete refused with in-flight executions: a `scraping_workflows` row with any `pending`/`running` execution returns `409 workflow_has_in_flight_executions` on delete; after the execution reaches terminal, the delete succeeds. Verifies **AC-18**.
- Pending to failed: an execution that fails validation before start persists with `status='failed'`, `started_at IS NULL`, `finished_at = now()`, `duration_ms = finished_at - created_at`, `error_code` set. Verifies **AC-6**, **AC-12**.
- Cross-registration history: soft delete a target, re-register the same URL (new `target_urls.id` per 0002), then query "all executions for this URL" by joining through `target_urls` with `with_deleted=True` and grouping by canonical URL; both the old and new rows appear in one list. Verifies **AC-19**.
- Default repository filter: `repository.list_workflows()` with no args omits soft-deleted parents; `repository.list_workflows(with_deleted=True)` includes them. Verifies **AC-20**.
- Config evolution: load a historical `workflow_versions.config` after `WorkflowConfig` gains a new optional field; `WorkflowConfig.model_validate(payload)` succeeds (no 422), the new field defaults to None. Verifies **AC-5**.

## Build plan

Skateboard order for a design foundation spec: ship the smallest usable whole first (SQLAlchemy ORM models for every MVP entity so Alembic can see them), then the Pydantic contract for `workflow_versions.config` that validates writes, then the module scaffolding each slice needs to drop its service and router onto. No migrations ship with this feature by design (chosen approach: one migration per entity cluster, shipped with its slice); the "initial migration applies cleanly" phrase on the scope row's `Done when` is revised in Follow-up to match this decision.

1. **Workflow ORM models** in `src/app/domains/workflows/models.py`: `ScrapingWorkflow` and `WorkflowVersion` SQLAlchemy mapped classes with every column, index, CHECK constraint, and FK listed in `## Feature design`. Registered with the project's declarative base so Alembic autogenerate sees them. Satisfies **AC-2**, **AC-3**, **AC-4**, **AC-9**, **AC-10**, **AC-12**, **AC-14**.
2. **Execution ORM models** in `src/app/domains/executions/models.py`: `Execution` and `ExecutionResult` SQLAlchemy mapped classes with every column, index, CHECK constraint, and FK listed above. Registered with the declarative base. Satisfies **AC-6**, **AC-7**, **AC-9**, **AC-10**, **AC-12**, **AC-14**.
3. **`WorkflowConfig` Pydantic model** in `src/app/domains/workflows/config.py` matching AC-5 exactly: `container_selector`, `fields` list, `output_schema`, optional `pagination`. Exposed as the single validator the workflow service calls before inserting or updating a `workflow_versions.config`. Satisfies **AC-5**, **AC-13**.
4. **Shared enums** in `src/app/domains/workflows/enums.py` and `src/app/domains/executions/enums.py` for `WorkflowStatus`, `WorkflowVersionStatus`, and `ExecutionStatus`, mirrored in the DB CHECK constraints and used by the repository and service layers to avoid stringly typed state. Satisfies **AC-12**.
5. **Repository stubs** in each domain (`src/app/domains/workflows/repository.py`, `src/app/domains/executions/repository.py`): empty interfaces that name the CRUD and lifecycle methods each slice will implement, including the default `with_deleted=False` keyword on every `list`/`get` method signature so the opt-in for history reads is uniform (AC-20). No queries implemented here; the file carries protocol/abstract definitions only. Satisfies **AC-2**, **AC-6**, **AC-20**.
6. **Error code registry** at `src/app/core/errors/execution_codes.py`: an initially empty module that declares the shape of the registry (a frozen dataclass/StrEnum per prefix, e.g. `FetchErrorCode`, `ExtractionErrorCode`, `ExecutionErrorCode`), plus a short module docstring saying feature 6, feature 7, feature 15, and feature 17 each extend their prefix. No concrete codes land here; the registry is populated by the slice features that produce the errors. Satisfies **AC-17**.
7. **Documentation hooks**: update spec [0002](../0002-website-target-registration.md)'s Follow-up item "Feature 3 (MVP data model) is still `needs a decision`" to point at this spec (one line edit; done at scope linking time). Satisfies **AC-1**.

Each later slice spec ships its own Alembic migration against this target: feature 5 adds `scraping_workflows` + `workflow_versions`, feature 7 adds `executions` + `execution_results`. This spec's acceptance criteria are the review checklist those migrations are judged against.

## Consequences

**Positive**

- Every slice feature (5, 6, 7) starts with the data shape pinned; the slice's design conversation is a pure service and router walk, not a model walk.
- Workflow and version are split cleanly, so a published version is a true immutable record and a change produces a new row rather than a mutating `UPDATE`. The `current_version_id` pointer makes "what runs when the caller omits a version" a single FK lookup.
- Extraction rules live inside `workflow_versions.config` as JSONB validated by one Pydantic model. One shape to read, one shape to write, one place to evolve the config schema (by versioning the Pydantic model and the Build plan step 3 behind it).
- Executions and results are append only with CASCADE only from execution to its results. History stays joinable past soft deletes of parent rows, which is what the execution browser (feature 11) and provenance queries (feature 18) will need.
- RESTRICT on cross entity FKs makes an accidental hard delete loud instead of silent; the only path to lose execution history is a deliberate retention job (deferred to a future spec).

**Negative / tradeoffs**

- Embedding extraction rules in JSONB means per rule editing in the admin UI (feature 10) is a read whole config, mutate in memory, write whole config loop. For large configs that is wasteful; mitigated by the config being small for MVP scrape targets.
- No DB level CASCADE on soft deletes means the workflow service and the executor service both need to know about `deleted_at` filters when they read parents. Mitigated by a tested service layer pattern that mirrors how [0002](../0002-website-target-registration.md) handles the website→targets case.
- `scraping_workflows.current_version_id` is a nullable FK back into a child table; this creates a mild cycle in the ERD. Deferring it initially (nullable) avoids an insert order problem but means every "which version is live" read must handle the NULL case.
- `workflow_versions.config` as a free form JSONB blob means a schema violation in a legacy row is only caught at read time by the Pydantic model; adding a required field to `WorkflowConfig` later needs a one time migration pass over every existing row. Mitigated by versioning `WorkflowConfig` conservatively and keeping its surface narrow until feature 15 (LLM assisted workflow discovery) lands.
- The `executions.status='pending'` state is unused by the sync executor (feature 7), which transitions straight to `running` within one request. It is kept so the async executor (feature 23) does not need a schema change. The dead state is a small readability cost today for a saved migration later.

**Neutral**

- No new third party dependencies; everything builds on SQLAlchemy 2, Pydantic v2, and Postgres 16 already pinned by [0001](../0001-stack-and-architecture/index.md).
- The product catalog entity (feature 18, slice 5) is deliberately out of scope here. When that spec lands, it will add a `products` table and a `product_sources` table that joins back to `execution_results.id`, which is why `execution_results.id` is UUIDv7 and stable.
- Rate limiting, SSRF controls, authn/authz, and retention are all deferred to their respective slices; this spec deliberately mentions them only to explain what is not here.
- Soft delete semantics on `scraping_workflows` extend the pattern [0002](../0002-website-target-registration.md) added to `target_urls` (not pinned by 0001). The convention is converging; a one line update to 0001 to pin "soft delete on mutable catalog aggregates" is a reasonable `/sync` cleanup.

## Follow-up

- [ ] Update spec [0002](../0002-website-target-registration.md)'s Follow-up item ("Feature 3 is still `needs a decision`") to point at this spec once scope linking is done (one line edit).
- [ ] The scope row for feature 3 reads `Done when: entities and relationships support slices 1 through 3 without a breaking migration; initial migration applies cleanly.` The chosen approach ships no migration here, each slice ships its own. Revise the `Done when` to: `the MVP data model is pinned in this spec; ORM models and the WorkflowConfig Pydantic model exist in src/app/domains/; later slice migrations conform to this spec exactly.`
- [ ] Flag to feature 5 (`/architect workflow configuration & versioning`): the workflow and version shape, `current_version_id` semantics, concurrency rules (AC-16), draft lifecycle (AC-12), and `WorkflowConfig` structure (AC-5) are pinned here; feature 5 owns the migration, the service layer, and the router. Feature 5's migration MUST order DDL to break the `scraping_workflows.current_version_id` ↔ `workflow_versions.id` FK cycle: create `scraping_workflows` without `current_version_id`'s FK (keep the nullable column), create `workflow_versions`, then `ALTER TABLE scraping_workflows ADD CONSTRAINT fk_current_version FOREIGN KEY (current_version_id) REFERENCES workflow_versions(id) ON DELETE RESTRICT`. The migration's CI contract runs `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` to catch an ordering regression.
- [ ] Flag to feature 6 (`/architect deterministic HTML extraction (static)`): the extraction config lives inside `workflow_versions.config`; the extractor reads one `WorkflowConfig` instance per execution and emits items matching `output_schema`.
- [ ] Flag to feature 7 (`/architect workflow execution endpoint (sync)`): the `executions` and `execution_results` shape, the per domain `error_code` enum, and the mandatory `correlation_id` persistence are pinned here; feature 7 owns the migration, the executor service, the router, and the error enum values.
- [ ] Flag to feature 11 (`/architect execution browser`): the three indexes on `executions` are shaped for the (workflow, target, status) × time filters; verify these cover the admin UI's planned queries before adding new indexes. The "all executions for this URL" view must join via `target_urls` including soft-deleted rows and group by `(website_id, canonical url)`, not by `target_url_id` alone (AC-19), because a soft-delete + re-register cycle produces a fresh `target_urls.id` and would otherwise split one URL's history across two rows.
- [ ] Flag to feature 18 (`/architect product entity & provenance`): `execution_results.id` is UUIDv7 and stable; use it as the join key for product provenance rather than inventing a surrogate.
- [ ] Consider a `/sync` edit to spec [0001](../0001-stack-and-architecture/index.md) to pin the convention "soft delete on mutable catalog aggregates, immutable append only tables for history." The pattern now spans websites, targets, workflows; stating it once in 0001 would stop later specs from re litigating it.
- [ ] Future spec (deferred): a retention job that hard deletes `executions` and `execution_results` older than a configurable window. Needs a decision on window size, archival vs delete, and whether per workflow overrides exist. Likely a slice 3 or slice 11 topic.

## Rationale

Reasoning and options considered: see [`rationale.md`](rationale.md).
