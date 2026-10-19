# 0004. Workflow configuration & versioning — rationale

The decision record `/develop` skips. The build spec lives in [`index.md`](index.md).

## Context

Slice 1 of the Skateboard plan needs a reusable, versioned, immutable-once-published scraping workflow before Feature 6 (deterministic HTML extraction) and Feature 7 (sync execution endpoint) can land. The data shape, lifecycle, and concurrency rules were pinned ahead of time by spec [0003](../0003-data-model-mvp/index.md), so this feature is not a model-design question: it is an API-and-service build-out that must honor [0003](../0003-data-model-mvp/index.md) exactly and ship the migration (0003 Follow-up explicitly delegates it here).

The forces at play:

- **The feature owns the FK-cycle migration.** `scraping_workflows.current_version_id` points at a `workflow_versions` row, and `workflow_versions.workflow_id` points back at `scraping_workflows`. A naive Alembic autogenerate would try to create both FKs upfront and fail. [0003](../0003-data-model-mvp/index.md) Follow-up spells out the ordering: create `scraping_workflows` without the current-version FK, create `workflow_versions`, then `ALTER TABLE` to add the FK. One migration file, one commit, verified by an `upgrade/downgrade/upgrade` CI check.
- **The feature owns the publish race.** [0003](../0003-data-model-mvp/index.md) AC-16 pins the exact transaction: `SELECT ... FOR UPDATE` on the parent, archive the currently-current published version, promote the draft, swap `current_version_id`, all in one commit. Two threads publishing on the same workflow serialize behind the row lock; the invariant "at most one `published` per workflow" is enforced by the transaction, not by a partial unique index (because the archive and promote happen in the same commit, no `CHECK` or `UNIQUE WHERE status='published'` could straddle it cleanly).
- **The sibling just shipped.** Feature 4 (website & target registration, spec [0002](../0002-website-target-registration/index.md)) landed last and set the project's shape for a Slice 1 feature: nested resource URLs, offset pagination for admin lists, soft-delete via repository filter with a `with_deleted=True` opt-in, Problem Details on every error, service exceptions mapped at the router boundary. Deviating here would create two patterns in one slice.
- **Consequence of not deciding well:** this spec is the contract for feature 7 (execution reads workflow versions) and feature 10 (admin UI reads/writes everything). A wrong endpoint shape, wrong lifecycle API, or a missed concurrency gate means a round-trip through `/architect` from each dependent later.

## Options considered

### Option 1: Nested resource shape with dedicated action endpoints for lifecycle, offset pagination for admin lists, full-config PATCH on drafts, and a single ordered migration that breaks the FK cycle

Mirror [0002](../0002-website-target-registration/index.md)'s shape wholesale: `/websites/{id}/workflows` (nested on create and list, flat for single-row ops), `/workflows/{id}/versions` (nested on create and list), dedicated `POST .../publish` and `POST .../archive` action endpoints for lifecycle moves, offset pagination on admin lists, `?with_deleted=true` opt-in via the repository, and one Alembic file that creates both tables with the FK added via `ALTER TABLE`.

**Pros**:
- Matches the pattern [0002](../0002-website-target-registration/index.md) set three days ago; the engineer builds against a known shape and `/check verify` has a sibling to compare against.
- Action endpoints make the concurrency contract explicit: one URL maps to one service method with one lock scope. Errors (`version_conflict`, `version_not_draft`, `version_is_current`) can be specific to the action rather than a generic PATCH 422.
- Full-config PATCH on drafts matches the "one shape, one `WorkflowConfig`, immutable at publish" model from [0003](../0003-data-model-mvp/index.md) AC-5; the draft is a holding pen, not a mutable DB document.
- One migration file with ordered DDL is testable in isolation with `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.

**Cons**:
- Full-config PATCH forces the UI (feature 10) to round-trip the whole config on each save; a per-field edit path would need a dedicated spec later.
- Dedicated action endpoints are not strictly REST; some teams prefer `PATCH .../status = published`. In practice the action style is more discoverable in OpenAPI and the publish body is empty anyway.

### Option 2: Flat resource shape with lifecycle via PATCH, cursor pagination throughout

Expose `/workflow-versions/{id}` flat (workflow_id in payload), move lifecycle to `PATCH /versions/{id} {status: 'published'|'archived'}`, and use cursor pagination for both workflows and versions in anticipation of growth.

**Pros**:
- Shorter URLs, closer to REST purism.
- Cursor pagination future-proofs the lists.

**Cons**:
- Breaks the aggregate boundary [0003](../0003-data-model-mvp/index.md) codified: the workflow is the aggregate root, the version is its child. Flat URLs make "list versions for this workflow" a query param, not a path, which [0002](../0002-website-target-registration/index.md) deliberately avoided.
- Lifecycle via PATCH mixes transition semantics with field edits; invalid transitions become generic 422s instead of specific 409s, which costs operator clarity.
- Cursor pagination for small, bounded lists (workflows per website, versions per workflow) is complexity with no measured need; AGENTS.md explicitly says "offset for small admin lists, cursor for executions and products" and the two tables under this spec are admin-list shaped.

### Option 3: Hybrid URLs plus JSON Merge Patch on draft config

Nest on create and list, flat on single-row ops; keep action endpoints for lifecycle, but accept RFC 7396 JSON Merge Patch on `PATCH /versions/{id}` for partial draft edits.

**Pros**:
- Nicer wire format for small edits in the UI (change one selector without re-sending the whole config).

**Cons**:
- `WorkflowConfig.fields` is a list of objects (each with `name`, `selector`, `transforms`); JSON Merge Patch has no identity for list elements, so it replaces the whole `fields` list or nothing. The partial-edit win evaporates on the only field that really needs it.
- Mixed URL shape (nested-on-create, flat-on-single) is harder to document and makes OpenAPI paths look inconsistent.
- Adds a Content-Type negotiation seam the service layer must handle for one endpoint.

## Rationale

**Option 1 is the right choice** because every force in Context points at mirroring the shape [0002](../0002-website-target-registration/index.md) just shipped, and because the concurrency contract in [0003](../0003-data-model-mvp/index.md) AC-16 wants a single service method with a single lock scope, which `POST .../publish` and `POST .../archive` provide cleanly. Option 2's cursor pagination is complexity with no measured need; AGENTS.md explicitly says "offset for small admin lists, cursor for executions and products", and workflows and versions are admin-list shaped. Option 3's JSON Merge Patch wins nothing on the one list field (`fields`) where a partial edit would help, and costs a URL inconsistency.

The one place the chosen option goes beyond [0003](../0003-data-model-mvp/index.md)'s pinned error codes is `workflow.version_is_current`: archiving the current `published` version is refused with a specific code so the operator sees "publish a replacement first" rather than a generic 409. The alternative (allow it, set `current_version_id=NULL`) would strand the workflow with no runnable version, which is strictly worse than refusing the archive.

The `has_in_flight_executions` service check at `DELETE /workflows/{id}` is a cross-feature touch: it queries a table owned by feature 7. The query is cheap and correct against the pinned [0003](../0003-data-model-mvp/index.md) column names, and defers to feature 7's row data when it lands (empty table today → zero rows → delete succeeds; later → the gate just works). The alternative (defer the check until feature 7) would ship a short-lived API that permits data corruption, and the "come back and add it" item is exactly the kind of Follow-up that gets forgotten.

The two `WorkflowConfig` coherence checks (field name uniqueness, output_schema coverage) sit at the service layer rather than inside `WorkflowConfig` because today there is one write seam (this feature); when the agent-assisted path (feature 16) adds a second write seam, promoting them into a `model_validator` is a one-line refactor and a Follow-up item here.
