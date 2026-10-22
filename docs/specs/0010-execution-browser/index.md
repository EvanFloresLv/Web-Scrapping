# 0010. Execution browser

**Date**: 2026-10-21
**Status**: In Progress

## Summary

This spec is the build spec for Slice 2's third feature: a read only admin surface that lets an operator browse past workflow executions and open any single run to see what it did, what it extracted, and (on failure) why it failed. It adds one backend endpoint (`GET /api/v1/executions`) with cursor pagination plus six filters (workflow, status, time range, target URL, website, correlation id), one Alembic migration (a single new btree index), and two admin screens built on the list and detail primitives from spec 0009. No new tables, no changes to the execution lifecycle pinned by spec 0006, no raw HTML persistence (deferred).

## Requirements

**User stories**:

- As a platform operator, I want to open the admin and see the most recent executions in a paginated list filtered by workflow and status and a time window, so I can tell at a glance which runs are failing or slow without running SQL.
- As a platform operator, I want to click a single run and see the exact items it extracted, its timings, its error code and message if it failed, and the config version that ran, so I can diagnose a bad run end to end from one screen.
- As a platform operator, I want the list and the detail to refresh themselves while a run is `running`, so I can watch a run flip to `completed` or `failed` without clicking Refresh.
- As a support engineer handed a `correlation_id` from a log line, I want to paste it into the browser and jump straight to the matching execution, so I never have to touch the DB to answer a question.
- As a backend engineer owning spec 0004 and later work, I want this feature to reuse the exact list / Sheet / detail primitives spec 0009 shipped, so Features 11+ keep one shell convention.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable):

- **AC-1**: `GET /api/v1/executions` returns a page of executions, newest first, keyed on the composite sort `(created_at DESC, id DESC)`. The response shape is `{items: ExecutionRead[], next_cursor: string | null}`; `total` is omitted on purpose (see Rationale). Items carry exactly the columns `GET /api/v1/executions/{id}` already returns (spec 0006 AC-7's `execution` object, which already denormalises `workflow_id` onto the response, so no join column is added here). Guarded by the admin API key per spec 0008 AC-4.
- **AC-2**: Cursor pagination. The query accepts `?cursor=<opaque>&page_size=<int>` where `page_size` is validated against `25 | 50 | 100` with default `50`. The cursor is `base64url(JSON.stringify({c: <created_at ISO 8601>, i: <id>}))`. The server decodes it, applies the keyset predicate `(created_at, id) < (c, i)` on the sort, and returns `next_cursor` only when `len(items) == page_size` (a strict heuristic: it may yield a final empty page, which the UI handles). A malformed cursor returns `400 execution.invalid_cursor` as Problem Details and persists nothing.
- **AC-3**: Filters, each optional and independently combinable: `workflow_id: UUID`, `status: 'pending' | 'running' | 'completed' | 'failed'` (free-form single value today; a multi-value `status` is deferred), `target_url_id: UUID`, `website_id: UUID`, `correlation_id: str` (free-form; `executions.correlation_id` is a `text` column per spec 0003 AC-6, so the filter accepts any string the middleware could have minted; validated as non-empty), `created_from: ISO-8601 datetime (inclusive)`, `created_to: ISO-8601 datetime (exclusive)`, `with_deleted: bool (default false)`. Validation errors are `422 execution.invalid_list_query` with the Pydantic field path in `details[].loc`. `created_from > created_to` returns the same code with message "created_from must be <= created_to".
- **AC-4**: `with_deleted=false` (the default) hides executions whose parent `scraping_workflows` row is soft deleted (`deleted_at IS NOT NULL`, per spec 0003 AC-18), enforced via an INNER JOIN on `scraping_workflows` with `WHERE deleted_at IS NULL`. `with_deleted=true` drops the join predicate so forensic queries see every row. The `GET /api/v1/executions/{id}` detail route (shipped by spec 0006) is unchanged by this: it still 200s on a soft deleted parent so a direct deep link from a log or ticket keeps working.
- **AC-5**: The `website_id` filter is resolved by joining executions → workflow_versions (`executions.workflow_version_id = workflow_versions.id`) → scraping_workflows (`workflow_versions.workflow_id = scraping_workflows.id`) and filtering `scraping_workflows.website_id = :website_id`. The join reuses the FK indexes already in place (spec 0003); no new index on the join path is added.
- **AC-6**: The `correlation_id` filter is a point lookup backed by a new btree index `ix_executions_correlation_id` on `executions.correlation_id`. The migration is a single Alembic revision; no other schema change ships in this feature.
- **AC-7**: `/executions` is a list route with URL-synced search params (`page_size`, `status?`, `workflow_id?`, `target_url_id?`, `website_id?`, `correlation_id?`, `created_from?`, `created_to?`, `with_deleted?`, `cursor?`). A Zod schema validates on `validateSearch`; invalid or out of range values fall back to defaults with no crash (same pattern as spec 0009 AC-20). Pagination uses the server-returned `next_cursor` only; the Previous button is not shown because keyset cursor pagination is forward only in this slice (the operator can bookmark a cursor URL to come back, but the UI does not stash a backwards stack).
- **AC-8**: The list columns are: Status (badge), Workflow (parent `name`, resolved via `useQueries` cache fan-out over the page's unique non-null `workflow_id`s, cache key `['workflows', id]`; renders the uuid in muted monospace if the workflow is deleted and `with_deleted=true`), Target URL (truncated, with full URL in a tooltip), Items extracted, Duration, Started, and a `Run` link to `/executions/:id`. Column source: the generated `openapi-typescript` types in `frontend/src/api/schema.d.ts` (per spec 0008 AC-6).
- **AC-9**: The list toolbar renders a `FilterBar` matching spec 0009's: a workflow Combobox (searches `['workflows', {status: 'active'}]`), a status select, a target URL Combobox that becomes enabled only once a workflow is picked (and then scopes to that workflow's active targets via the same `GET /api/v1/websites/:website_id/targets?status=active&page_size=200` call spec 0009 uses in the Preview panel), a website Combobox, a `correlation_id` text input, two datetime-local inputs for `created_from` and `created_to`, and a Reset filters button that clears every search param back to defaults.
- **AC-10**: Auto refresh. While the current page of results contains at least one row whose `status in ('pending', 'running')`, the list query sets `refetchInterval: 3000` so the row flips to `completed` or `failed` without a manual reload. Once no in-flight row remains, `refetchInterval` returns to `false` so the view is idle at zero cost. The same rule applies to the detail route: `['executions', id]` refetches every 3 s only while that specific row's `status in ('pending', 'running')`.
- **AC-11**: `/executions/:id` is a detail route rendering the full execution record from `GET /api/v1/executions/{id}` (spec 0006 AC-7) in three sections: a header (status badge, duration, started/finished timestamps, correlation id with a Copy button), a metadata grid (links to the parent workflow at `/workflows/:workflow_id`, the parent website at `/websites/:website_id`, and the target URL at `/websites/:website_id` with the URL text; each link opens the matching admin screen), and an `error` block that renders only when `status == 'failed'` (shows `error_code` as a code badge, `error_message` as prose, and a note that fuller `error_details` live in structlog keyed by `correlation_id` per spec 0006 AC-13).
- **AC-12**: The detail route renders the extracted items as a shadcn `Table` whose columns are the keys of the version's `output_schema.properties` (not the fetched items' shapes, so a zero-item run still shows the column headers). The items come from the detail response's `items[]` payload (spec 0006 AC-7). A `Raw JSON` tab beside the Table renders the same payload as a read only CodeMirror JSON pane. A `Copy JSON` button copies the entire items array to the clipboard.
- **AC-13**: The detail route also renders a collapsed `Config that ran` pane: a read only CodeMirror JSON pane seeded by `GET /api/v1/workflows/:workflow_id/versions/:version_id` (reusing the fetcher and query key `['workflows', workflow_id, 'versions', version_id]` spec 0009 already set up). The pane is collapsed by default to keep the page light; the summary header shows `v{version_number}` and the version `status` as a badge.
- **AC-14**: Empty states. The list renders an `EmptyState` card with a one-line description and a CTA to clear the current filters when the result set is empty; a run with zero items on the detail renders an `EmptyState` ("No items extracted. If the run `completed`, the config matched but the page produced no rows; check the selectors.") that is distinct from the error block.
- **AC-15**: Problem Details propagation. Every 4xx the list endpoint can emit (`400 execution.invalid_cursor`, `422 execution.invalid_list_query`) is rendered by the list route's error banner with the `code`, `title`, `detail`, and `correlation_id`, matching the Problem Details rendering spec 0009 AC-17 uses on the Preview panel. The detail route reuses the existing error handling spec 0006 ships for `GET /api/v1/executions/{id}` (404 execution_not_found).
- **AC-16**: Access. The list and detail routes mount under `/_authed/` and go through `apiFetch`, which attaches the `X-API-Key` header per spec 0008 AC-4; a cold load with an invalid key is bounced to `/login` by the global 401 handler. There is no per-row scoping (an API key sees every execution across every website; see Follow-up).

## Decision

**Chosen option**: Option 1: single feature that ships one list endpoint + one Alembic index + two admin screens, built on the list / detail primitives from spec 0009, with cursor pagination and auto refresh while a run is in flight.

Spec 0006 already ships the executions domain (table, lifecycle, write path, single-row read); this feature adds only the browsing surface and one supporting index. The list route reuses spec 0009's `DataTable`, `FilterBar`, `EmptyState`, `useListQuery`, and search-param convention so there is one shell pattern across every admin list. Pagination follows the AGENTS.md pin (cursor for executions and products) via a `base64url` opaque cursor over `(created_at, id)`, and the server omits `total` on purpose so an unbounded, filterable table never pays the COUNT tax. The detail route is a plain client-fetched page under `/_authed/executions.$executionId.tsx` with the three sections from AC-11 and the config snapshot pane from AC-13.

**Implementation skills**:
- `fastapi` (`fastapi/fastapi`, `.claude/skills/fastapi/`) router + dependency injection + OpenAPI shape conventions
- `sqlalchemy-alembic-expert-best-practices-code-review` (`wispbit-ai/skills`, `.claude/skills/sqlalchemy-alembic-expert-best-practices-code-review/`) the index migration and the keyset query
- `tanstack-query` (`deckardger/tanstack-agent-skills`, `.claude/skills/tanstack-query-best-practices/`) query keys, conditional `refetchInterval`, `useQueries` fan-out
- `tanstack-router` (`deckardger/tanstack-agent-skills`, `.claude/skills/tanstack-start-best-practices/`) nested routes, `validateSearch`
- `shadcn-ui/ui` (`shadcn-ui/ui`, `.claude/skills/shadcn-ui/`) `Table`, `Tabs`, `Combobox`, `Tooltip` conventions
- `vitest` + `webapp-testing` for the component and smoke tests

## Rationale

Reasoning and options considered: see [`rationale.md`](rationale.md).

## Feature design

**Data model sketch**

No new tables. One new index:

| Index | Table | Columns | Shape | Why |
|---|---|---|---|---|
| `ix_executions_correlation_id` | `executions` | `(correlation_id)` | btree | AC-6: point lookup for the support-ticket workflow (paste a correlation id, land on the row). Not covered by the three existing composite indexes (`ix_executions_workflow_version_id_created_at`, `ix_executions_target_url_id_created_at`, `ix_executions_status_created_at`, all from spec 0003 AC-6). |

The join path for AC-5 (`website_id` filter) is `executions.workflow_version_id → workflow_versions.id → workflow_versions.workflow_id → scraping_workflows.id → scraping_workflows.website_id`; every hop uses a PK or an FK that already has an index per spec 0003 AC-6, so no additional index is added.

Client-side state:

| Store / shape | Where | Persistence |
|---|---|---|
| Per-route search params (filters + cursor + page_size) | TanStack Router search params | URL only; Zod `validateSearch` on each list route |
| TanStack Query cache: `['executions', filters]`, `['executions', id]`, plus parent workflow + target lookups | TanStack Query | In-memory; refetchInterval 3s only when an in-flight row is present (AC-10) |

**State transitions**

Execution lifecycle is owned by spec 0006 (not restated). This feature only reads it; auto refresh (AC-10) exists because `pending → running → completed | failed` happens asynchronously relative to the UI.

**API surface** (one endpoint added, two reused as-is)

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/api/v1/executions` | GET | `cursor?`, `page_size?`, `status?`, `workflow_id?`, `target_url_id?`, `website_id?`, `correlation_id?`, `created_from?`, `created_to?`, `with_deleted?` | `{items: ExecutionRead[], next_cursor: str \| null}` | admin API key (spec 0008 AC-4) | `400 execution.invalid_cursor`, `422 execution.invalid_list_query` |
| `/api/v1/executions/{id}` | GET | path `id` | spec 0006 AC-7 body | admin API key | `404 execution.not_found` (reused) |
| `/api/v1/workflows/{workflow_id}/versions/{id}` | GET | path | spec 0004 AC-8 body | admin API key | `404 workflow.version_not_found` (reused) |

`ExecutionRead` is spec 0006 AC-7's `execution` object as-is (which already denormalises `workflow_id` onto the row), so the list row never needs a second fetch to render the Workflow column.

**Value sourcing** (every value an action produces or displays names its source)

| Action | Value produced / displayed | Source |
|---|---|---|
| `/executions` list | row columns | `openapi-typescript`-generated `components['schemas']['ExecutionRead']` in `frontend/src/api/schema.d.ts` (spec 0008 AC-6) |
| `/executions` list | filter values | URL search params, parsed via Zod on `validateSearch`; invalid values fall back to defaults (AC-7) |
| `/executions` list | Workflow column name | TanStack Query cache lookup on `['workflows', workflow_id]`; cache miss falls back to a per-id GET batched via `useQueries` over the page's unique workflow_ids (AC-8) |
| `/executions` list | Target URL column text | denormalised onto `ExecutionRead` as `target_url` (the full URL string joined from `target_urls.url`); same pattern 0009 used for `/workflows` current-version resolution |
| `/executions` list | next_cursor | `base64url(JSON.stringify({c: last_item.created_at, i: last_item.id}))` computed server-side (AC-2); the UI treats it as opaque |
| `/executions` list | refetchInterval | derived client-side from `items.some(e => e.status === 'pending' \|\| e.status === 'running')`; `3000` if true else `false` (AC-10) |
| `/executions/:id` detail | metadata values | GET `/api/v1/executions/:id` response (spec 0006 AC-7) |
| `/executions/:id` detail | items table columns | keys of the version's `output_schema.properties` (not the fetched items' shapes, so empty results still render column headers) |
| `/executions/:id` detail | config snapshot JSON | GET `/api/v1/workflows/:workflow_id/versions/:version_id` response's `config` (AC-13) |
| `/executions/:id` detail | parent links | `execution.workflow_id` → `/workflows/:id`; `execution.target_url_id` is used only to render the URL text + a tooltip (clicking the target URL cell opens its parent website at `/websites/:website_id`, so the operator sees the full set of targets for that site); `workflow.website_id` from the cached parent workflow row powers the website link |
| Error block | `error_code`, `error_message` | `execution.error_code` and `execution.error_message` columns (spec 0003 AC-6); the fuller `error_details` lives in structlog per spec 0006 AC-13 and is NOT re-read from storage |
| 4xx banner | code, title, detail, correlation_id | `ApiError` from `apiFetch` (spec 0008 AC-8, spec 0007) |

**Key invariants**

- Every list request is admin API key gated (spec 0008 AC-4). No endpoint added by this feature is anonymous.
- Pagination is cursor forward only. The server returns `next_cursor` when the page is "full" (`len == page_size`), else `null`; `total` is never returned by the list endpoint.
- The list sort is `(created_at DESC, id DESC)`, tie-broken by id so the cursor predicate `(created_at, id) < (c, i)` has a strict total order even for executions that landed in the same millisecond.
- `with_deleted=false` on the list hides rows whose parent `scraping_workflows` is soft deleted; the detail route still 200s on a soft deleted parent so a direct deep link survives.
- Auto refresh is bounded: the 3 s poll runs only while at least one visible row is `pending` or `running`; when none is, the interval returns to `false`. The detail route applies the same rule to its single row.
- Every value the UI renders traces to either a column on `ExecutionRead`, a cached parent lookup, or a reused response from spec 0004/0006; no value is invented client-side.
- Problem Details is the only error wire shape (per `AGENTS.md`); the UI's existing `apiFetch` + Problem Details renderer handles every error path this feature touches, no custom per-code UI.

**Security model**

Admin-only, API key gated per spec 0008 AC-4. No role differentiation, no per-website scoping (every valid key sees every execution). No new PII; `execution_results.payload` is scraped product data whose provenance is already governed by spec 0005 (public web content). No new secrets, no new compliance scope. The `correlation_id` filter is a point lookup against values already in logs; it exposes no additional attack surface.

**Configuration required**

None. The feature uses only `ADMIN_API_KEY`, `SERVE_ADMIN_UI`, and `ADMIN_UI_DIST_PATH` from spec 0008; no new env vars, no new feature flags.

**Critical test scenarios** (each maps to an acceptance criterion in `## Requirements`)

- End-to-end happy path (Playwright, extends spec 0009's smoke): sign in, open `/executions`, see the most recent runs, filter by `status=failed`, click into one, assert the error block renders `error_code` + `error_message`, assert the items Table + Raw JSON + Copy JSON controls render, assert the config snapshot pane expands. Verifies **AC-1**, **AC-7**, **AC-8**, **AC-9**, **AC-11**, **AC-12**, **AC-13**.
- Cursor pagination (pytest + httpx): seed 150 executions, page through with `page_size=50`, assert each page is strictly older than the previous one, assert `next_cursor is None` on the final page, assert a malformed cursor returns `400 execution.invalid_cursor`. Verifies **AC-1**, **AC-2**.
- Filter combinability (pytest + httpx): seed executions across two workflows, two statuses, three days; assert each filter alone and all combined yield exactly the expected row IDs. Verifies **AC-3**.
- `created_from > created_to` guard (pytest): assert `422 execution.invalid_list_query` with the specific message. Verifies **AC-3**.
- `with_deleted` default (pytest): soft-delete a workflow with an existing execution; assert the row disappears from the default list and reappears with `with_deleted=true`; assert the detail route still 200s. Verifies **AC-4**.
- `website_id` join (pytest): assert the join path matches the workflow's `scraping_workflows.website_id` and that executions under a different website are excluded. Verifies **AC-5**.
- `correlation_id` lookup (pytest): assert the point lookup uses `ix_executions_correlation_id` (`EXPLAIN` is enough) and returns exactly the matching row. Verifies **AC-6**.
- URL-synced filters + invalid fallback (vitest): deep-link `/executions?status=garbage&page_size=999&created_from=not-a-date`, assert the list fetches with status undefined, page_size 50, created_from undefined; filter chips render default. Verifies **AC-7**.
- Auto refresh (vitest with fake timers): render the list with one `running` row, advance 3 s, assert a refetch; flip the mocked row to `completed`, advance 3 s, assert no further refetch. Verifies **AC-10**.
- Config snapshot pane (vitest): render the detail with a mocked version row, assert the collapsed `v{N}` header, expand, assert the CodeMirror pane shows the `config` JSON. Verifies **AC-13**.
- Empty states (vitest): render the list with zero rows + a non-default filter, assert the empty card with the Clear filters action; render the detail of a `completed` run with `items == []`, assert the empty items card. Verifies **AC-14**.
- Problem Details propagation (vitest): mock a `400 execution.invalid_cursor`; assert the list's error banner renders `code`, `title`, `detail`, `correlation_id`. Verifies **AC-15**.

## Build plan

Skateboard order: thinnest usable whole first (list endpoint + list screen with just the pagination and one filter), then grow filters, then the detail, then auto refresh, then polish. Six milestones, each shippable.

1. **Alembic migration + list repository groundwork** (satisfies **AC-6**, scaffolds **AC-1**, **AC-2**): add `ix_executions_correlation_id` as its own Alembic revision, add `ExecutionsRepository.list(filters, cursor, page_size)` implementing the keyset query `(created_at, id) < (c, i)` ordered `DESC, DESC`, add the `base64url` cursor codec and its `400 execution.invalid_cursor` error. Includes the pytest coverage for AC-6 and the cursor codec.
2. **List endpoint + Problem Details wiring** (satisfies **AC-1**, **AC-2**, **AC-3**, **AC-4**, **AC-5**): add `GET /api/v1/executions` under the admin-gated router (spec 0008 AC-4) with a Pydantic `ExecutionListQuery` model covering every filter in AC-3, the `with_deleted` INNER JOIN gate on `scraping_workflows`, the `website_id` join through `workflow_versions`, and the response model `{items: ExecutionRead[], next_cursor: str | null}`. `ExecutionRead` picks up the joined `workflow_id` column. Includes the pytest coverage for AC-3, AC-4, AC-5 and the `created_from > created_to` guard.
3. **`/executions` list screen scaffolding** (satisfies **AC-7**, **AC-8** partial, **AC-14** partial, **AC-16**): add `/_authed/executions.tsx` as a `createFileRoute` with a Zod `validateSearch`, wire a `useListQuery`-shaped TanStack Query key `['executions', filters]`, render the `DataTable` with the six columns from AC-8 (Workflow column renders the raw workflow_id as monospace in this milestone), the status badge, and the empty state card. Pagination controls: Next + Previous (Previous disabled, since cursors are forward only). No filters yet.
4. **Filter bar + parent workflow name resolution** (satisfies **AC-8**, **AC-9**): add the `FilterBar` composition (workflow Combobox searching `['workflows', {status:'active'}]`, status select, target URL Combobox gated on workflow pick, website Combobox, correlation_id text input, two datetime-local inputs for the time range, Reset filters button). Add the `useQueries` fan-out over the page's unique workflow_ids so the Workflow column renders the parent `name` once the cache fills.
5. **`/executions/:id` detail route + config snapshot pane** (satisfies **AC-11**, **AC-12**, **AC-13**, **AC-14**): add `/_authed/executions.$executionId.tsx` fetching `['executions', id]`, render the header + metadata grid + error block (AC-11), the items `Table` + `Raw JSON` tab + `Copy JSON` button (AC-12), and the collapsed `Config that ran` pane via `['workflows', workflow_id, 'versions', version_id]` (AC-13). Add the zero-items empty state card.
6. **Auto refresh + Problem Details propagation + tests** (satisfies **AC-10**, **AC-15**, every remaining critical test scenario): wire the conditional `refetchInterval: data.items.some(running) ? 3000 : false` on both the list and the detail queries. Add the vitest coverage enumerated in Critical test scenarios (auto refresh with fake timers, URL-synced fallback, empty states, Problem Details propagation). Extend the spec 0009 Playwright smoke with the end-to-end execution browser path.

## Consequences

**Positive**:
- Satisfies the scope row's `done when: the list paginates, filters work, and a run detail view renders JSON output, error reasons, and timing` with one new endpoint + one index + two screens.
- Reuses every list and detail primitive spec 0009 already shipped (`DataTable`, `FilterBar`, `EmptyState`, `useListQuery`, Zod `validateSearch`, Problem Details renderer), so the admin shell convention stays one pattern across every feature in this slice.
- Cursor pagination means the list stays fast as the executions table grows unbounded, matching the AGENTS.md pin.
- Auto refresh is bounded (polls only when an in-flight row is visible), so the view is idle at zero cost in the common case where the operator is browsing old runs.

**Negative / tradeoffs**:
- No `total` on the list response. Operators cannot see "page 1 of X"; they get "Showing N on this page" + Next. Acceptable because COUNT(*) over a growing filterable table gets slow fast, and the UI never actually needed the total for anything load bearing.
- The pagination is cursor forward only. There is no Previous button in this slice; an operator who wants to come back to page 2 bookmarks the URL. A backwards stack is deferable without impact.
- The `website_id` filter joins through `workflow_versions` and `scraping_workflows`. Three joins on every list query. The join path is indexed on every hop (spec 0003 AC-6), so the cost is small, but it is real.
- Auto refresh is 3 s polling, not push. Fine until an operator wants sub-second feedback; a push transport (SSE/WebSocket) is a whole new infra concern that no other feature uses yet, so deferred.
- No raw HTML, no JSON diff vs the previous execution. Both would help real debugging; both are big and get their own specs.
- No scoping. Every valid admin API key sees every execution across every website. Fine for the single-operator reality today; the multi-tenant posture is Follow-up.

**Neutral**:
- One new Alembic revision (one new index) and one new FastAPI endpoint. No new tables.
- Two new frontend route files (`_authed.executions.tsx`, `_authed.executions.$executionId.tsx`); the placeholder `_authed.executions.tsx` from spec 0008 is replaced by the real one in milestone 3.
- No new backend or frontend dependencies. The config snapshot pane reuses the CodeMirror + `@codemirror/lang-json` setup spec 0009 already installed.
- `AGENTS.md` is unchanged by this spec; nested `frontend/AGENTS.md` capture of the list / Sheet / detail conventions is still owned by spec 0009's Follow-up and is not duplicated here.

## Follow-up

- [ ] Spec 0003 AC-19 flags a cross-registration join for "all executions for this URL": when a `target_urls` row is soft deleted and the same canonical URL is re-registered, old executions point at the old id. This feature's `target_url_id` filter is strict (point lookup by id), which matches the scope row's wording but misses the cross-registration case; a follow-up spec can add either a `target_url=<canonical url>` filter that joins through `target_urls` with `with_deleted=true` and groups by canonical URL, or a backend convenience route for this one history read.
- [ ] A future spec: persist the fetched HTML on `executions` (new column or external blob store), with size cap, retention policy, and PII redaction. Needed before any serious extraction debugging; deferred because it is a load bearing data model decision on its own.
- [ ] A future spec: side-by-side JSON diff of the detail's items against the previous `completed` execution of the same (workflow_id, target_url_id). Adds a frontend dep (`react-diff-viewer-continued` or similar) and a backend convenience route or an extra client fetch.
- [ ] A future spec: backwards pagination for the list (either a `?direction=prev&cursor=…` variant on the endpoint, or a client-side backward-stack of the forward cursors it has seen).
- [ ] A future spec: multi-value `status` filter (`?status=pending,running`) once operators ask for it; the single-value filter in AC-3 handles 95% of the real workflow today.
- [ ] A future admin spec: a per-workflow Executions tab under `/workflows/:id` (nested route) that pre-fills the browser's `workflow_id` filter. Low lift; keeps the operator in the workflow context when debugging.
- [ ] A future backend spec: scope an API key to a `website_id` or a set of them so a key cannot see every tenant's executions. Multi-tenant posture; not needed today.
- [ ] A future spec: push notifications for lifecycle changes (SSE or WebSocket) replacing the 3 s poll, once a second feature (metrics dashboard, agent trace stream) justifies the transport.
- [ ] Follow-up for spec 0009: capture the list / Sheet / detail / table conventions in `frontend/AGENTS.md`. This spec reuses them but does not change the ownership of the capture task.
