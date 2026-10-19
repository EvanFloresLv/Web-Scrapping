# 0004. Workflow configuration & versioning

**Date**: 2026-10-19
**Status**: In Progress

## Summary

This spec is the build spec for Slice 1's workflow configuration feature. It adds the API surface and service layer that lets an operator register a reusable scraping workflow, create draft versions of its JSON configuration, publish them, archive them, and retrieve them. The data shape, lifecycle, and concurrency rules are already pinned by spec [0003](../0003-data-model-mvp/index.md); this feature owns the Alembic migration (one file, careful FK ordering), the repository implementation, the service layer that enforces lifecycle gates and the publish race, and the FastAPI router that mirrors spec [0002](../0002-website-target-registration/index.md)'s shape.

## Requirements

**User stories**

- As a platform operator, I want to register a scraping workflow under a known website, so that later executions have a stable, named thing to run.
- As a platform operator, I want to iterate on a workflow's extraction configuration as a draft and publish it when ready, so that the published version is a frozen record every execution can reproduce.
- As a platform operator, I want to publish a new version and have the previous `published` version archived in the same step, so that the invariant "at most one published version per workflow" always holds and `scraping_workflows.current_version_id` always points at the right row.
- As a platform operator, I want to list workflows filtered by website and status, and list versions filtered by lifecycle, so that the admin UI (feature 10) can land without extra endpoints.
- As a platform engineer building the executor (feature 7), I want `WorkflowConfig` validated at write time with coherence checks (field name uniqueness, output schema coverage), so that invalid configuration is caught at the write boundary and never reaches the extractor.

**Acceptance criteria** (the contract later skills check)

- **AC-1**: `POST /api/v1/websites/{website_id}/workflows` creates a `scraping_workflows` row with `status='active'`, `current_version_id=NULL`, defaulted audit fields, and returns `201` with the created resource. Payload is `{name: str(1..200), description: str(..2000) | null}`.
- **AC-2**: `POST /api/v1/websites/{website_id}/workflows` with a `(website_id, name)` matching a live (non-soft-deleted) workflow returns `409 application/problem+json` with `code=workflow.name_conflict`. A `(website_id, name)` matching a soft-deleted workflow returns `201` (the partial unique index per [0003](../0003-data-model-mvp/index.md) AC-14 excludes `deleted_at IS NOT NULL`). A `website_id` that is missing or soft-deleted returns `404 website_not_found`.
- **AC-3**: `GET /api/v1/websites/{website_id}/workflows` lists workflows under the website with offset pagination (`?page=N&page_size=M`, defaults `1` and `50`, `page=>=1`, `1<=page_size<=200`), optional `?status=active|inactive` filter, and optional `?with_deleted=true` to include soft-deleted rows (default `false`). Invalid `?status=` or out-of-range `page`/`page_size` returns `422 workflow.invalid_pagination`. A missing or soft-deleted `website_id` returns `404 website_not_found`. `GET /api/v1/workflows/{id}` returns one workflow by id or `404 workflow_not_found`. The response envelope is `{items: [WorkflowRead], total: int, page: int, page_size: int}`.
- **AC-4**: `PATCH /api/v1/workflows/{id}` updates `name`, `description`, and/or `status` (`active|inactive`), returns the updated resource. The Pydantic `WorkflowPatch` model is declared with `model_config = ConfigDict(extra='forbid')`; any field in the payload other than those three returns `422 workflow.immutable_field`. An empty-body PATCH (`{}`) is a no-op that returns `200` with the current resource (mirrors [0002](../0002-website-target-registration/index.md) AC-10). A `(website_id, name)` collision with another live workflow returns `409 workflow.name_conflict`.
- **AC-5**: `DELETE /api/v1/workflows/{id}` soft deletes the workflow (sets `deleted_at = func.now()`), hides it and its versions and executions from default repository reads (per [0003](../0003-data-model-mvp/index.md) AC-20), and returns `204`. The operation is **idempotent**: a DELETE on an already-soft-deleted workflow also returns `204` (mirrors [0002](../0002-website-target-registration/index.md) AC-11). Soft delete is **non-reversible** via this API (per [0003](../0003-data-model-mvp/index.md) AC-12, `deleted` is terminal from the API's perspective); an undelete path is deferred to a future admin spec, flagged in Follow-up. If any execution of this workflow's versions has `status IN ('pending','running')`, returns `409 workflow.has_in_flight_executions` (per [0003](../0003-data-model-mvp/index.md) AC-18). The check is a `SELECT 1 FROM executions WHERE workflow_version_id IN (SELECT id FROM workflow_versions WHERE workflow_id = ?) AND status IN ('pending','running') LIMIT 1` and deliberately does NOT filter by `workflow_versions.deleted_at` (versions aren't soft-deletable per [0003](../0003-data-model-mvp/index.md) AC-9, and the gate must see every live or hypothetically-live execution); the query returns zero rows pre-feature-7 (empty table), so the gate just works once feature 7 lands.
- **AC-6**: `POST /api/v1/workflows/{workflow_id}/versions` creates a draft version: inserts a `workflow_versions` row with auto-assigned monotonic `version_number`, `status='draft'`, the submitted `config` validated by `WorkflowConfig`, and returns `201` with the created version. Payload is `{config: WorkflowConfig}`; `version_number` is never accepted from the caller. Concurrent inserts under the same workflow serialize behind a `SELECT ... FOR UPDATE` on the parent `scraping_workflows` row and get consecutive `version_number` values; a lost race against the `UNIQUE (workflow_id, version_number)` index triggers **one** retry; the retry re-acquires the `SELECT ... FOR UPDATE` on the parent and recomputes `MAX(version_number)+1 WHERE workflow_id = ?` inside the retry transaction (not reuse of the stale value), then inserts; a second violation returns `409 workflow.version_conflict` (per [0003](../0003-data-model-mvp/index.md) AC-16). Creating a draft on a workflow whose `status='inactive'` returns `409 workflow.inactive`. Creating a draft on a soft-deleted or missing workflow returns `404 workflow_not_found`.
- **AC-7**: `WorkflowConfig` is validated at write time by the Pydantic model declared in [0003](../0003-data-model-mvp/index.md) AC-5 plus two service-layer coherence checks: (a) `config.fields[*].name` is unique inside one `WorkflowConfig`; (b) every name in `config.fields` appears as a key in `config.output_schema`. A violation returns `422 application/problem+json` with the field name(s) in `details`. Pydantic shape violations also return `422`.
- **AC-8**: `GET /api/v1/workflows/{workflow_id}/versions` lists versions for the workflow with offset pagination (same defaults and bounds as AC-3), optional `?status=draft|published|archived` filter, and optional `?with_deleted=true` to include versions of soft-deleted parents (default `false`). Results are ordered by `version_number DESC`. Invalid `?status=` or out-of-range pagination returns `422 workflow.invalid_pagination`. `GET /api/v1/workflows/{workflow_id}/versions/{id}` returns one version or `404 version_not_found`; if `{id}` exists but its `workflow_id` doesn't match the `{workflow_id}` in the path, returns `404 version_not_found` (not `400`). Response envelope mirrors AC-3.
- **AC-9**: `PATCH /api/v1/workflows/{workflow_id}/versions/{id}` with `{config: WorkflowConfig}` replaces the full config of a `status='draft'` version and runs the same validation as AC-7. The request body is a full-config replace, not a partial merge, so the semantics match the one-shape, write-once-at-publish rule. The Pydantic `WorkflowVersionPatch` model uses `extra='forbid'`; any field other than `config` returns `422 workflow.immutable_field`. An empty-body PATCH is a no-op `200`. Any PATCH on a `published` or `archived` version returns `409 workflow.version_not_draft`. PATCH on a draft under an `inactive` or soft-deleted workflow returns `409 workflow.inactive` or `404 workflow_not_found` respectively. The service enforces the immutability of every content column once `status='published'` (per [0003](../0003-data-model-mvp/index.md) AC-13).
- **AC-10**: `DELETE /api/v1/workflows/{workflow_id}/versions/{id}` hard-deletes a draft version (`status='draft'` only) and returns `204` (per [0003](../0003-data-model-mvp/index.md) AC-12's "`draft` is hard deletable until published"). Any DELETE on a `published` or `archived` version returns `409 workflow.version_not_draft`. A missing version returns `404 version_not_found`. Hard deletion of a draft frees its `version_number` only in the sense that the next draft keeps monotonically growing; no number is ever re-assigned.
- **AC-11**: `POST /api/v1/workflows/{workflow_id}/versions/{id}/publish` publishes a draft atomically per [0003](../0003-data-model-mvp/index.md) AC-16: opens a transaction, takes `SELECT ... FOR UPDATE` on the parent `scraping_workflows` row, **re-reads the target draft row inside the lock** (if its `status != 'draft'`, it was superseded by a concurrent commit → raises `409 workflow.version_conflict`), archives the currently-current published version (`UPDATE workflow_versions SET status='archived', archived_at=func.now() WHERE id = scraping_workflows.current_version_id AND status='published'`), promotes the draft (`UPDATE workflow_versions SET status='published', published_at=func.now() WHERE id = ?`), and swaps `scraping_workflows.current_version_id` to the new version's id (the swap triggers SQLAlchemy's `onupdate` so `scraping_workflows.updated_at` bumps in the same transaction) in one commit. First publish on a workflow with `current_version_id=NULL` follows the same path (the archive step is a no-op). Publishing a non-draft version returns `409 workflow.version_not_draft`. Publish on an `inactive` workflow returns `409 workflow.inactive`. Returns `200` with the published version resource.
- **AC-12**: `POST /api/v1/workflows/{workflow_id}/versions/{id}/archive` archives a `status='published'` version that is NOT the current `scraping_workflows.current_version_id`: sets `status='archived'`, `archived_at=func.now()`, and returns `200`. Archiving the current published version returns `409 workflow.version_is_current` (the operator must publish a replacement first; archiving the current version would leave the workflow with no runnable version and would strand `current_version_id` pointing at an archived row). Archiving a `draft` or already `archived` version returns `409 workflow.version_not_published`. Archive on an `inactive` workflow is **allowed** (archive is a cleanup move, not a new state commit, and an operator must be able to tidy history on a paused workflow).
- **AC-13**: Every error response is `application/problem+json` (RFC 7807) with `type` (defaults to `about:blank` for MVP; a per-code URI convention is deferred to a future spec, flagged in Follow-up), `title`, `status`, `detail`, `code` (from `WorkflowErrorCode`, AC-15), and `correlation_id`, mirroring the shape established in [0002](../0002-website-target-registration/index.md). Validation errors include a `details` array naming the offending fields.
- **AC-14**: The Alembic migration ships as a single file `migrations/versions/YYYYMMDDHHMM_add_workflows_and_versions.py` that creates both tables, breaks the `scraping_workflows.current_version_id ↔ workflow_versions.id` FK cycle by creating `scraping_workflows` without the FK on `current_version_id`, creating `workflow_versions`, then adding the FK via `ALTER TABLE`, exactly as [0003](../0003-data-model-mvp/index.md) Follow-up pins. The migration passes `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` cleanly in the test container.
- **AC-15**: The `WorkflowErrorCode` StrEnum is declared in `src/app/core/errors/execution_codes.py` (the registry pinned by [0003](../0003-data-model-mvp/index.md) AC-17). Members:
  - 404 lookups: `website_not_found`, `workflow_not_found`, `version_not_found`.
  - 409 conflicts: `workflow.name_conflict`, `workflow.version_conflict`, `workflow.version_not_draft`, `workflow.version_not_published`, `workflow.version_is_current`, `workflow.has_in_flight_executions`, `workflow.inactive`.
  - 422 validation: `workflow.validation_error` (shape + coherence per AC-7), `workflow.immutable_field` (unknown or non-patchable field in a PATCH body), `workflow.invalid_pagination` (`?status`/`page`/`page_size` out of allowed set/range).

  The registry filename `execution_codes.py` is a legacy name from [0003](../0003-data-model-mvp/index.md) ("execution codes" meaning "error codes used during the execution of any domain action", not "codes owned by the executions domain"); flagged in Follow-up for a rename to `error_codes.py` once feature 7 also adds its enum.
- **AC-16**: The repository layer applies the `workflow.deleted_at IS NULL` filter by default on every list and get for workflows and versions (through the join for versions), and exposes a `with_deleted=True` keyword to opt into history reads (per [0003](../0003-data-model-mvp/index.md) AC-20). The `?with_deleted=true` query param wires straight to this.
- **AC-17**: Published versions are immutable at the service layer (per [0003](../0003-data-model-mvp/index.md) AC-13): a direct repository `update()` of a `published` or `archived` version's content columns raises `ImmutableFieldError`. The only service calls that modify a non-draft version are `publish()` and `archive()`, each touching only `status`, `published_at`, or `archived_at`.

## Decision

**Chosen option**: Option 1: Nested resource shape with dedicated action endpoints for lifecycle, offset pagination for admin lists, full-config PATCH on drafts, and a single ordered migration that breaks the FK cycle.

The feature is a pure build-out on top of [0003](../0003-data-model-mvp/index.md)'s pinned data model: the service layer and router mirror the shape [0002](../0002-website-target-registration/index.md) just shipped (nested parent-child URLs, offset pagination, Problem Details on errors, soft-delete via the repository), and the lifecycle moves (`publish`, `archive`) are dedicated action endpoints so the concurrency contract pinned by [0003](../0003-data-model-mvp/index.md) AC-16 maps to one service method with one lock scope.

**Implementation skills**: `fastapi` (`fastapi/fastapi`, `.claude/skills/fastapi/`) · `sqlalchemy-alembic-expert-best-practices-code-review` (`wispbit-ai/skills`, `.claude/skills/sqlalchemy-alembic-expert-best-practices-code-review/`) · `python-testing-patterns` (`wshobson/agents`, `.claude/skills/python-testing-patterns/`) · `modern-python` (`trailofbits/skills`, `.claude/skills/modern-python/`)

## Rationale

Reasoning and options considered: see [`rationale.md`](rationale.md).

## Feature design

**Data model sketch**

Fully pinned by [0003](../0003-data-model-mvp/index.md). This feature creates the two tables [0003](../0003-data-model-mvp/index.md) specifies for Slice 1:

- `scraping_workflows` (aggregate root): columns, indexes, CHECK constraints per [0003](../0003-data-model-mvp/index.md). Key index: `UNIQUE (website_id, name) WHERE deleted_at IS NULL`.
- `workflow_versions` (immutable child): columns, indexes, CHECK constraints per [0003](../0003-data-model-mvp/index.md). Key index: `UNIQUE (workflow_id, version_number)`.
- FKs: `scraping_workflows.website_id → websites(id) ON DELETE RESTRICT`; `scraping_workflows.current_version_id → workflow_versions(id) ON DELETE RESTRICT` (nullable, added via `ALTER TABLE` after both tables exist); `workflow_versions.workflow_id → scraping_workflows(id) ON DELETE RESTRICT`.

Not re-specified here; see [0003](../0003-data-model-mvp/index.md) `## Feature design` for the authoritative tables.

**State transitions** (service-enforced; mirror [0003](../0003-data-model-mvp/index.md) AC-12)

```
scraping_workflows
    active  ──PATCH status──▶  inactive
            ◀──PATCH status──
         └── DELETE ──▶ (soft-deleted; invisible by default)

workflow_versions
    draft  ──POST .../publish──▶  published  ──POST .../archive──▶  archived
      │                          (also auto-archived when a
      │                           sibling draft is published)
      └── DELETE (hard) while status=draft
```

Not permitted: `draft→archived` directly, `archived→draft`, `archived→published`, `published→draft` (per [0003](../0003-data-model-mvp/index.md) AC-12).

**API surface**

All endpoints under `/api/v1`. Auth is open-on-localhost (feature 26 adds the gate). Errors are `application/problem+json` per AC-13.

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/websites/{website_id}/workflows` | POST | `name:str(1..200) (req)`, `description:str(..2000) (opt)` | `201` + `WorkflowRead` | open | `404 website_not_found`, `409 workflow.name_conflict`, `422 workflow.validation_error` |
| `/websites/{website_id}/workflows` | GET | `page?int(def 1,>=1)`, `page_size?int(def 50,1..200)`, `status?active|inactive`, `with_deleted?bool(def false)` | `200` + paginated `WorkflowRead` list | open | `404 website_not_found`, `422 workflow.invalid_pagination` |
| `/workflows/{id}` | GET | path only | `200` + `WorkflowRead` | open | `404 workflow_not_found` |
| `/workflows/{id}` | PATCH | `name? description? status?` (`extra='forbid'`) | `200` + `WorkflowRead` | open | `404 workflow_not_found`, `409 workflow.name_conflict`, `422 workflow.immutable_field`, `422 workflow.validation_error` |
| `/workflows/{id}` | DELETE | path only | `204` (idempotent) | open | `409 workflow.has_in_flight_executions` |
| `/workflows/{workflow_id}/versions` | POST | `config: WorkflowConfig` | `201` + `WorkflowVersionRead` | open | `404 workflow_not_found`, `409 workflow.inactive`, `409 workflow.version_conflict`, `422 workflow.validation_error` |
| `/workflows/{workflow_id}/versions` | GET | `page? page_size? status?draft|published|archived with_deleted?` | `200` + paginated `WorkflowVersionRead` list ordered `version_number DESC` | open | `404 workflow_not_found`, `422 workflow.invalid_pagination` |
| `/workflows/{workflow_id}/versions/{id}` | GET | path only | `200` + `WorkflowVersionRead` | open | `404 version_not_found` (also when `id` belongs to a different workflow) |
| `/workflows/{workflow_id}/versions/{id}` | PATCH | `config: WorkflowConfig` (`extra='forbid'`) | `200` + `WorkflowVersionRead` | open | `404 version_not_found`, `409 workflow.inactive`, `409 workflow.version_not_draft`, `422 workflow.immutable_field`, `422 workflow.validation_error` |
| `/workflows/{workflow_id}/versions/{id}` | DELETE | path only | `204` | open | `404 version_not_found`, `409 workflow.version_not_draft` |
| `/workflows/{workflow_id}/versions/{id}/publish` | POST | empty body | `200` + `WorkflowVersionRead` | open | `404 version_not_found`, `409 workflow.inactive`, `409 workflow.version_not_draft`, `409 workflow.version_conflict` |
| `/workflows/{workflow_id}/versions/{id}/archive` | POST | empty body | `200` + `WorkflowVersionRead` | open | `404 version_not_found`, `409 workflow.version_not_published`, `409 workflow.version_is_current` |

**Response schemas** (pinned here so `/develop` doesn't re-decide the wire shape)

- `WorkflowRead`: `id, website_id, name, description, status, current_version_id, created_at, updated_at`. `deleted_at` is included only when the row was returned via `?with_deleted=true`; omitted otherwise.
- `WorkflowVersionRead`: `id, workflow_id, version_number, status, config, published_at, archived_at, created_at, updated_at`. `config` is the full `WorkflowConfig` document.
- Pagination envelope: `{items: [T], total: int, page: int, page_size: int}`.
- Problem Details body: `{type: str (default 'about:blank'), title: str, status: int, detail: str, code: WorkflowErrorCode, correlation_id: str, details?: list[{field: str, message: str}]}`.

**Value sourcing**

| Action | Value produced / displayed | Source |
|---|---|---|
| POST `/websites/{website_id}/workflows` | `id` | Application UUIDv7 generator pinned by [0001](../0001-stack-and-architecture/index.md) |
| POST `/websites/{website_id}/workflows` | `website_id` | Path parameter, validated against the live (non-soft-deleted) `websites` row; missing or soft-deleted → `404 website_not_found` |
| POST `/websites/{website_id}/workflows` | `status` | Server default `'active'` on the `scraping_workflows.status` column (one source, no ORM-side default to avoid skew) |
| POST `/websites/{website_id}/workflows` | `current_version_id` | NULL at creation; set by `publish()` on first publish |
| POST `/websites/{website_id}/workflows` | `created_at`, `updated_at` | DB server default `func.now()` on insert; SQLAlchemy `onupdate=func.now()` on UPDATE per [0001](../0001-stack-and-architecture/index.md) |
| GET `/websites/{website_id}/workflows` | pagination `total`, `page`, `page_size` | `total` is `SELECT COUNT(*)` with the same filter, computed in the repository; `page` + `page_size` echo validated request params |
| GET `/websites/{website_id}/workflows` | `with_deleted` default | `false` (hide soft-deleted parents); explicit `?with_deleted=true` opts in per AC-16 |
| GET under soft-deleted parent `website_id` | status code | `404 website_not_found` (soft-deleted parents are hidden from the API, mirrors [0002](../0002-website-target-registration/index.md)) |
| GET `/workflows/{workflow_id}/versions/{id}` | version-ownership mismatch | If `id` exists but belongs to a different workflow, return `404 version_not_found` (not `400`); the (workflow, version) pair is the identity |
| PATCH `/workflows/{id}` | which fields are patchable | Allow-list in `WorkflowPatch` (Pydantic `model_config=ConfigDict(extra='forbid')`): `name`, `description`, `status`. Any other field returns `422 workflow.immutable_field`. Empty body is a no-op `200` |
| DELETE `/workflows/{id}` | idempotency | Idempotent: DELETE on an already-soft-deleted row returns `204` (mirrors [0002](../0002-website-target-registration/index.md) AC-11); soft delete is non-reversible via this API |
| DELETE `/workflows/{id}` | in-flight execution check | `SELECT 1 FROM executions WHERE workflow_version_id IN (SELECT id FROM workflow_versions WHERE workflow_id = ?) AND status IN ('pending','running') LIMIT 1`; the subselect deliberately does NOT filter by `workflow_versions.deleted_at` (versions aren't soft-deletable per [0003](../0003-data-model-mvp/index.md) AC-9); zero rows → delete succeeds; one row → `409 workflow.has_in_flight_executions` |
| POST `/workflows/{workflow_id}/versions` | `version_number` | Service: `SELECT ... FOR UPDATE` on parent + `MAX(version_number)+1 WHERE workflow_id=?` per [0003](../0003-data-model-mvp/index.md) AC-16; one retry on `IntegrityError` that re-acquires the lock and recomputes `MAX(version_number)+1` (not reuse of the stale value) |
| POST `/workflows/{workflow_id}/versions` | preconditions | Parent must exist and not be soft-deleted (`404 workflow_not_found` otherwise) and must be `status='active'` (`409 workflow.inactive` on inactive) |
| POST `/workflows/{workflow_id}/versions` | `status` | Server default `'draft'` on the `workflow_versions.status` column |
| POST `/workflows/{workflow_id}/versions` | `config` validation | `WorkflowConfig.model_validate(payload)` plus two service checks: field name uniqueness (set vs list length) and output_schema coverage (every `fields[*].name` is a key in `output_schema`); any violation → `422 workflow.validation_error` with `details[]` naming the offending field(s) |
| PATCH `/workflows/{workflow_id}/versions/{id}` | `config` replace semantics | Full replace of the `config` JSONB column, not a merge; the request body must be a complete `WorkflowConfig`. `WorkflowVersionPatch` is `extra='forbid'`; unknown fields → `422 workflow.immutable_field` |
| POST `.../publish` | superseded-draft detection | Inside the `SELECT ... FOR UPDATE` on parent, re-read the target draft row; if its `status != 'draft'`, raise `409 workflow.version_conflict` (another thread committed a transition on this draft between the request and the lock acquisition) |
| POST `.../publish` | `published_at` | `func.now()` (DB clock) set in the same UPDATE as the status promotion |
| POST `.../publish` | archive of prior current version | Same transaction as the promote; sets `status='archived'`, `archived_at=func.now()` on the row whose id equals `scraping_workflows.current_version_id` AND `status='published'`; a no-op row count on first publish |
| POST `.../publish` | `scraping_workflows.current_version_id` swap | Same transaction; set to the newly-published version id. SQLAlchemy `onupdate` fires on this UPDATE so `scraping_workflows.updated_at` bumps in the same commit |
| POST `.../archive` | `archived_at` | `func.now()` (DB clock) set by the service in the UPDATE |
| POST `.../archive` | inactive-workflow handling | Allowed on an `inactive` workflow (archive is cleanup, not a new state commit) |
| Error responses | `type` | `about:blank` default for MVP; a per-code URI convention is deferred (Follow-up) |
| Error responses | `code` | `WorkflowErrorCode` StrEnum from `src/app/core/errors/execution_codes.py` (AC-15) |
| Error responses | `correlation_id` | `asgi-correlation-id` middleware contextvar per [0001](../0001-stack-and-architecture/index.md) |
| Error responses | `details[]` on 422 | List of `{field, message}` naming each offending field (Pydantic field path for shape errors; the duplicate `name` or uncovered `name` for coherence errors in AC-7) |

**Key invariants** (service-enforced; mirror [0003](../0003-data-model-mvp/index.md))

- At most one `workflow_versions` row per `workflow_id` has `status='published'` at any time (publish transaction, AC-11).
- `scraping_workflows.current_version_id`, when NOT NULL, references a `workflow_versions` row whose `workflow_id` equals this row's `id` and whose `status='published'` (AC-11, AC-12 together).
- A `workflow_versions.config` is only writable while `status='draft'`; once published, every content column is immutable (AC-9, AC-17).
- `version_number` is monotonically assigned per `workflow_id` and never re-assigned (AC-6, AC-10).
- A `scraping_workflows` row is only soft-deletable when zero of its executions are in `pending` or `running` (AC-5).

**Security model**

- No new authn/authz. Inherits the open-on-localhost assumption of the MVP per [0003](../0003-data-model-mvp/index.md). Feature 26 (slice 11) adds the API-key gate in front of every endpoint.
- No regulated data: workflow names, descriptions, and extraction configs are not PII and carry no secrets.
- `correlation_id` is a request trace id, not an auth token; safe to log and return in error bodies.

**Configuration required**

None. The feature uses only settings already pinned by [0001](../0001-stack-and-architecture/index.md) (DB URL, UUIDv7 generator, correlation-id middleware, JSON encoding).

**Critical test scenarios** (each maps to an acceptance criterion)

- Happy path: create a workflow under a website, create a draft version with a valid `config`, publish it, GET the workflow and confirm `current_version_id` points at the published version. Verifies **AC-1**, **AC-6**, **AC-11**.
- Duplicate name: a second POST with the same `(website_id, name)` while the first is live returns `409 workflow.name_conflict`. Verifies **AC-2**.
- Re-register after soft-delete: soft-delete a workflow, POST the same `(website_id, name)` again; succeeds because the partial unique index excludes `deleted_at IS NOT NULL`. Verifies **AC-2**, **AC-5**.
- Config validation (shape): `POST .../versions` with a `config` missing `container_selector` returns `422` (Pydantic). Verifies **AC-7**.
- Config validation (coherence): `POST .../versions` with two `fields` entries sharing the same `name` returns `422 validation_error` with the duplicate name in `details`. Same with a `fields[*].name` not present in `output_schema`. Verifies **AC-7**.
- Draft edit: PATCH a draft's `config` with a new full `WorkflowConfig`; the row is updated. PATCH a published version's `config` returns `409 workflow.version_not_draft`. Verifies **AC-9**.
- Draft delete: DELETE a draft version returns `204` and removes the row; DELETE a published version returns `409 workflow.version_not_draft`. Verifies **AC-10**.
- Concurrent version insert: two threads POST `.../versions` under the same workflow simultaneously; the row lock serializes them, both get consecutive `version_number` values, no `IntegrityError` escapes; a simulated lost-race scenario (bypassing the lock in a test) triggers the one-shot retry. Verifies **AC-6**.
- Concurrent publish: two threads publish two different drafts of the same workflow simultaneously; one commits, the other either succeeds (publishing a different draft, auto-archiving the one the first thread published) or returns `409 workflow.version_conflict`; at every moment at most one row has `status='published'` per workflow. Verifies **AC-11**.
- First publish: a workflow with `current_version_id=NULL` publishes its first draft; the archive step is a no-op (0 rows); `current_version_id` is set from NULL to the new version's id; one row has `status='published'`. Verifies **AC-11**.
- Archive non-current: publish version A, then version B (A is auto-archived, B is current). Archive A explicitly: already archived, returns `409 workflow.version_not_published`. Archive B (the current): returns `409 workflow.version_is_current`. Verifies **AC-12**.
- Soft-delete gate (pre-feature-7): with the `executions` table empty, DELETE `/workflows/{id}` succeeds and returns `204`. Verifies **AC-5**.
- Soft-delete gate (post-feature-7, simulated): insert one `executions` row with `status='running'` for a version of this workflow, DELETE the workflow returns `409 workflow.has_in_flight_executions`; after the row transitions to `completed`, the delete succeeds. Verifies **AC-5**.
- Default repository filter: soft-delete a workflow, GET `/websites/{website_id}/workflows` omits it; GET `?with_deleted=true` includes it; same for `/workflows/{workflow_id}/versions`. Verifies **AC-3**, **AC-8**, **AC-16**.
- Pagination: insert 60 workflows under one website, GET `?page=2&page_size=25` returns rows 26..50 with `total=60`. Verifies **AC-3**.
- Immutable fields on PATCH: PATCH `/workflows/{id}` with `{"website_id": "..."}` returns `422` without touching the row. Verifies **AC-4**.
- Migration round-trip: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` passes in the test container; the FK on `current_version_id` exists after upgrade and is dropped on downgrade. Verifies **AC-14**.
- Problem Details shape: every error response has `type`, `title`, `status`, `detail`, `code`, `correlation_id`; a 422 includes `details[]` naming the field. Verifies **AC-13**.

## Build plan

Skateboard order: the thinnest usable whole first (schema + create a workflow), then grow slice by slice. The migration lands as one file at the top of the plan because every subsequent task reads or writes those tables; the service and router layers mirror [0002](../0002-website-target-registration/index.md)'s shape so the engineer builds against a known pattern.

1. **Alembic migration** at `migrations/versions/YYYYMMDDHHMM_add_workflows_and_versions.py`: create `scraping_workflows` WITHOUT the FK on `current_version_id` (keep the nullable column), create `workflow_versions` with every column/index/CHECK from [0003](../0003-data-model-mvp/index.md), then `ALTER TABLE scraping_workflows ADD CONSTRAINT fk_current_version FOREIGN KEY (current_version_id) REFERENCES workflow_versions(id) ON DELETE RESTRICT`. Downgrade removes in reverse. Satisfies **AC-14**.
2. **Error-code registry extension** at `src/app/core/errors/execution_codes.py`: add `WorkflowErrorCode` StrEnum with `name_conflict`, `version_conflict`, `version_not_draft`, `version_not_published`, `version_is_current`, `has_in_flight_executions`. Satisfies **AC-15**.
3. **Repository implementation** in `src/app/domains/workflows/repository.py`: concrete async methods against `AsyncSession` for `ScrapingWorkflow` and `WorkflowVersion`: `create`, `get`, `list(with_deleted=False, **filters)` with the join-based `deleted_at IS NULL` filter, `update`, `soft_delete`, `hard_delete`, plus `publish_atomic(workflow_id, draft_id)` encapsulating the `SELECT ... FOR UPDATE` + archive-current + promote-draft + swap-current-pointer transaction, and `has_in_flight_executions(workflow_id)` for AC-5. Satisfies **AC-5**, **AC-6**, **AC-11**, **AC-16**, **AC-17**.
4. **Service layer** in `src/app/domains/workflows/service.py`: `WorkflowService` (create, list, get, patch, soft_delete with the in-flight-executions gate) and `WorkflowVersionService` (create_draft with the two coherence checks + one-retry on `IntegrityError`, list, get, patch_draft, delete_draft, publish, archive). Each method raises typed domain exceptions mapped to `WorkflowErrorCode` by the router layer. Satisfies **AC-1**, **AC-4**, **AC-5**, **AC-6**, **AC-7**, **AC-9**, **AC-10**, **AC-11**, **AC-12**, **AC-17**.
5. **Pydantic request/response models** in `src/app/domains/workflows/schemas.py`: `WorkflowCreate`, `WorkflowRead`, `WorkflowPatch` (allow-list `name`, `description`, `status` only), `WorkflowVersionCreate` (just `config: WorkflowConfig`), `WorkflowVersionRead`, `WorkflowVersionPatch`, plus pagination envelope mirroring [0002](../0002-website-target-registration/index.md). Satisfies **AC-1**, **AC-4**, **AC-6**, **AC-9**.
6. **FastAPI router** in `src/app/api/v1/workflows.py`: every endpoint in the API surface table above, with `Depends(get_session)`, structured error mapping to `application/problem+json`, and OpenAPI docstrings. Registered under `/api/v1` in `src/app/api/v1/router.py`. Satisfies **AC-1**, **AC-2**, **AC-3**, **AC-4**, **AC-5**, **AC-6**, **AC-8**, **AC-9**, **AC-10**, **AC-11**, **AC-12**, **AC-13**.

Milestones for the scope row (coarse rollup; the atomic steps stay here):

- Migration + repository groundwork (steps 1–3; satisfies **AC-14**, **AC-15**, **AC-16**).
- Workflow CRUD (steps 4–6, workflow endpoints; satisfies **AC-1**, **AC-2**, **AC-3**, **AC-4**, **AC-5**).
- Version create and edit (steps 4–6, version endpoints without publish/archive; satisfies **AC-6**, **AC-7**, **AC-8**, **AC-9**, **AC-10**, **AC-17**).
- Publish and archive lifecycle (step 4 `publish_atomic` + step 6 action endpoints; satisfies **AC-11**, **AC-12**).
- Problem Details error mapping (step 6 router error handlers; satisfies **AC-13**).

## Consequences

**Positive**

- The admin UI (feature 10) can land without extra endpoints: workflow CRUD, draft iteration, publish, and archive are all here, with the right filters for its screens.
- The executor (feature 7) gets a stable contract: `GET /workflows/{id}` with `current_version_id` resolves "what runs when the caller omits a version" in one FK lookup, and `GET .../versions/{id}` returns the frozen `config` for a run.
- The publish race is pinned to one service method with one lock scope, so the invariant "at most one published version per workflow" is enforced by the transaction, not by a DB constraint that would need a partial-unique index workaround on an immutable column.
- Mirroring [0002](../0002-website-target-registration/index.md)'s router/service/repository shape means the engineer builds against a known pattern, and `/check verify` has a sibling to compare against.

**Negative / tradeoffs**

- Full-config PATCH on drafts means the admin UI must round-trip the whole `WorkflowConfig` even for a one-field edit; mitigated by configs staying small for MVP scrape targets and by the lack of concurrent draft editors (one operator at a time per draft in practice).
- The in-flight-executions check at delete time is a query against a table owned by feature 7. The query is correct and cheap today (empty table), but it hard-codes the `executions` columns `workflow_version_id` and `status`, so a rename in feature 7 would break it. Mitigated by the shape being pinned by [0003](../0003-data-model-mvp/index.md); flagged in Follow-up so feature 7's spec review catches a rename.
- `workflow.version_is_current` is an extra error code that strictly isn't in [0003](../0003-data-model-mvp/index.md) AC-17's examples. It's needed so archiving the current published version is refused with a specific reason (not just a generic 409); the alternative is a silent `current_version_id=NULL` after an archive, which would strand the workflow with no runnable version.
- `WorkflowConfig` coherence checks (field name uniqueness, output_schema coverage) are service-layer, not Pydantic-layer. A later refactor that validates on `model_validate` (via a `model_validator`) would collapse this into the Pydantic error; worth doing when a second validation seam appears (e.g. the agent-assisted path, feature 16).

**Neutral**

- No new third-party dependencies.
- Error-code registry gains one `WorkflowErrorCode` enum; feature 7 adds `ExecutionErrorCode` later, feature 6 adds `FetchErrorCode` and `ExtractionErrorCode`. The registry file stays the single source of truth per [0003](../0003-data-model-mvp/index.md) AC-17.
- `/architect`-authored endpoints follow the `/api/v1` prefix and `application/problem+json` conventions pinned in root `AGENTS.md`.

## Follow-up

- [ ] Flag to feature 7 (`/architect workflow execution endpoint (sync)`): the `has_in_flight_executions` service check in this feature queries `executions.workflow_version_id` and `executions.status`; keep those column names stable when feature 7 ships its migration, or update this feature's query in the same slice.
- [ ] Flag to feature 10 (`/architect workflow configuration screens`): draft config editing is a full-replace PATCH, not a merge; the UI must round-trip the whole `WorkflowConfig` on each save. If the UI wants per-field edits, consider adding a `PATCH` with JSON Merge Patch (RFC 7396) semantics in a dedicated child spec; this feature deliberately does not.
- [ ] Flag to feature 11 (`/architect execution browser`): the admin's "all executions for this workflow" view can rely on `scraping_workflows.current_version_id` being non-NULL once there's at least one published version, but must handle the NULL case (a brand-new workflow with only drafts).
- [ ] Consider a `/sync` edit to [0003](../0003-data-model-mvp/index.md) AC-17's examples to add `workflow.version_is_current` and `workflow.inactive` so the pattern "lifecycle refusal codes beyond the three initial examples" is captured once; one-line edit, no spec rewrite.
- [ ] Consider promoting the two `WorkflowConfig` coherence checks (field name uniqueness, output_schema coverage) into `WorkflowConfig` itself via a `model_validator` when the second write seam (agent-assisted discovery, feature 16) lands; today it would duplicate the service code with no gain.
- [ ] **Undelete / restore endpoint (deferred)**: this feature treats soft delete as non-reversible via the API (per [0003](../0003-data-model-mvp/index.md) AC-12). A later admin spec may add `POST /workflows/{id}/restore` (requires elevated authz, which only arrives with feature 26); not needed for MVP operation.
- [ ] **Problem Details `type` URI convention (deferred)**: MVP uses `about:blank` for every error's `type`. A later cross-cutting spec can define a per-code URI (e.g. `/errors/{code}`) once the error-code set across domains stabilizes (feature 7 and feature 6 both extend the registry); folds naturally into feature 8 (`structured errors & health endpoints`).
- [ ] **Rename `src/app/core/errors/execution_codes.py` → `error_codes.py`**: the file now holds `WorkflowErrorCode` as well as the executor-side enums [0003](../0003-data-model-mvp/index.md) AC-17 names, so the "execution" in the filename is misleading. Low-risk rename; worth doing when feature 7 lands and adds its own enum so the rename is a single commit touching the two call sites that will exist by then.
