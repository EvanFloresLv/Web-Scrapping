# 0009. Workflow configuration screens

**Date**: 2026-10-21
**Status**: In Progress

## Summary

This spec is the build spec for Slice 2's second feature: the admin UI screens that let an operator register websites, add target URLs under them, author scraping workflows and their versions, and run a preview against a sample URL. It builds on top of the shell shipped by spec 0008 (React 19, Vite, TanStack Router and Query, Zustand, React Hook Form plus Zod, shadcn/ui, Tailwind 4) and the backend endpoints already in place from specs 0002 (websites, targets), 0004 (workflows, versions, publish/archive), and 0005 (preview). No new backend surface is added; every change ships in the `frontend/` package.

## Requirements

**User stories**:
- As a platform operator, I want to register a website, add target URLs under it, create a workflow, draft its configuration, preview it against one of my target URLs, and publish it, all from the admin UI, so I never have to touch curl to set up a scrape.
- As a platform operator, I want to iterate on a draft version, see validation errors inline, and run a preview to confirm the extracted sample before I publish, so I catch broken selectors before an execution does.
- As a platform operator, I want clear, safe lifecycle actions (publish, archive, soft delete) with the right confirmations and conflict handling, so I never strand a workflow or accidentally wipe one with running executions.
- As a backend engineer owning Features 11 and later, I want this feature to establish the list/sheet/detail patterns so Executions and later catalog screens drop into the same shell without re-deciding navigation, forms, or error UX.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable):

- **AC-1**: `/websites` is a list route that reads filters from URL search params (`page:int(>=1,def 1)`, `page_size:int(25|50|100,def 50)`, `status:'active'|'inactive'?`, `with_deleted:bool(def false)`) validated by a Zod schema on the route, falling back to defaults on invalid or out-of-range values. The table columns come from the generated `openapi-typescript` types in `frontend/src/api/schema.d.ts` (per spec 0008 AC-6, no hand-mirrored field names). A `Register website` button opens a shadcn `Sheet`. An empty state card renders when the list has zero rows, with the same `Register website` call to action.
- **AC-2**: Website create (POST `/api/v1/websites`) and edit (PATCH `/api/v1/websites/{id}`) happen in the Sheet via React Hook Form plus Zod; `apiFetch` maps 422 `errors[].loc` entries to form fields (per spec 0008 AC-8). Delete opens a shadcn `AlertDialog` that requires the operator to type the website's canonical host before the Delete button activates; a short cascade warning ("Deleting also soft-deletes its target URLs") is shown. On success, mutations invalidate the `['websites']` query key family so the list refetches.
- **AC-3**: `/websites/:id` is a detail route that shows the website metadata (host, scheme, status, created_at, updated_at) and a nested targets list (GET `/api/v1/websites/:id/targets`) with the same filter/pagination contract as AC-1 (URL-synced), scoped to this website. An `Add target` button opens a Sheet. The route redirects to `/websites` with an error toast when the website is missing or soft-deleted (404).
- **AC-4**: Target create (POST `/api/v1/websites/:id/targets`), edit (PATCH `/api/v1/targets/:id`), and delete (DELETE `/api/v1/targets/:id`) follow the same Sheet / AlertDialog pattern as AC-2; 422 and 409 errors from the backend render inline on the form (422) or as a dialog-level banner (409). Target deletes use a plain confirm dialog, not type-to-confirm (targets are low-risk relative to a workflow).
- **AC-5**: `/workflows` is a list route with URL-synced filters (`page`, `page_size`, `status:'active'|'inactive'?`, `with_deleted:bool`, plus an optional `website_id:uuid?` filter). The row shows name, parent website name (joined via a batched read of `['websites', id]` entries from TanStack Query cache; cache misses are batched into a single `useQueries` fan-out over the unique website_ids on the page), status, current version number (resolved via a second `useQueries` fan-out over the unique non-null `current_version_id`s on the page, each query key `['workflows', workflow_id, 'versions', version_id]`; renders an em-dash when `current_version_id` is null), and updated_at. A `Register workflow` button opens a Sheet in which website is a shadcn `Combobox` searching `['websites', {status: 'active'}]`.
- **AC-6**: Workflow create (POST `/api/v1/websites/:website_id/workflows`) and edit (PATCH `/api/v1/workflows/:id`) use the Sheet pattern. Delete opens an AlertDialog that requires the operator to type the workflow's name before Delete activates. A 409 `workflow.has_in_flight_executions` renders as an inline banner inside the dialog listing the gate reason ("One or more executions are pending or running; wait for them to finish") and keeps the row in place; the dialog stays open with Delete disabled until the operator cancels.
- **AC-7**: `/workflows/:id` is a detail route with three tabs Overview | Versions | Preview, implemented as nested TanStack Router routes so the active tab lives in the URL (`/workflows/:id/overview`, `/workflows/:id/versions`, `/workflows/:id/preview`); the bare `/workflows/:id` redirects to `/workflows/:id/overview`. Overview shows the workflow metadata, a status toggle (active↔inactive), a link to the parent website, and the current published version (if any).
- **AC-8**: The workflow status toggle on Overview uses TanStack Query's `onMutate` optimistic update: the row flips immediately on click, rolls back on error (any non-2xx), and on settle (success or error) invalidates both `['workflows', id]` (the detail cache) and the `['workflows']` family (so every open list refetches); the error surfaces as a toast with the `correlation_id` (per spec 0008 AC-8).
- **AC-9**: The Versions tab lists versions via GET `/api/v1/workflows/:id/versions`, with a URL-synced `status:'draft'|'published'|'archived'?` filter and the same pagination contract as AC-1. A `+ New draft` button opens the version editor at the provisional path `/workflows/:id/versions/new` **without creating a server-side draft row**; the editor's RHF form is seeded with the literal `WorkflowConfig` below, so the operator starts editing immediately and the backend sees no row until the first Save. First Save POSTs to `/api/v1/workflows/:id/versions` and then navigates to `/workflows/:id/versions/:vid` for the newly-created row; subsequent Saves on that path PATCH the row. Navigating away from `/versions/new` before any Save creates no orphan draft. Pinned seed body (literal, so `/develop` doesn't invent one):

  ```json
  {
    "container_selector": "body",
    "fields": [
      {"name": "placeholder", "selector": "body", "type": "string", "required": true, "transforms": []}
    ],
    "output_schema": {
      "type": "object",
      "properties": {"placeholder": {"type": "string"}},
      "required": ["placeholder"]
    }
  }
  ```
- **AC-10**: `/workflows/:id/versions/:vid` is the version editor route, rendered as a split layout: the left pane is the config editor form, the right pane is the Preview panel (AC-17). The editor route owns one React Hook Form instance whose default values are the fetched version's `config`; a `useBlocker` guard warns on navigation away while the form is dirty.
- **AC-11**: The config editor is structured for the known schema and permissive for the arbitrary parts: a text input for `container_selector`; a repeatable rows editor for `fields[]` with inputs for `name`, `selector`, `type` (dropdown; see below), `transforms` (chip-list input, free-form strings), and `required` (toggle, default true); a CodeMirror 6 JSON pane (via `@uiw/react-codemirror` + `@codemirror/lang-json`) for `output_schema`; and a CodeMirror pane for an optional `pagination` object. The pane is absent by default; an "Add pagination" button inserts the literal seed `{"next_selector": "", "max_pages": 1}` (matches `PaginationSpec` in `src/app/domains/workflows/config.py`) into the pane for the operator to fill in. The `fields[*].type` dropdown values come from the typed OpenAPI enum when `openapi-typescript` exposes one; else they fall back to the pinned five values `string`, `integer`, `decimal`, `boolean`, `url` (the set spec 0005 pins). `fields[*].transforms` entries are free-form strings client-side; backend publish-time validation against the extraction transform registry is the authority (spec 0005 Follow-up). The Zod schema mirrors `src/app/domains/workflows/config.py`'s `WorkflowConfig`. Client-side the editor flags: duplicate `fields[*].name` (red outline on the duplicate rows), and `output_schema` coverage gaps (every `fields[*].name` must appear as a key in `output_schema`; missing keys shown as an inline warning above the JSON pane). These mirror spec 0004 AC-7's two service-layer coherence checks so the operator gets feedback before the save round-trip.
- **AC-12**: Save issues PATCH `/api/v1/workflows/:workflow_id/versions/:id` with the full `WorkflowConfig` object (per spec 0004 AC-9's full-config replace semantics), only when the form is dirty. The editor shows a `Dirty` badge in the header while unsaved; `Cmd/Ctrl+S` triggers Save when dirty. Attempting to navigate away or close the browser tab while dirty opens an AlertDialog ("You have unsaved changes. Discard?") with a Discard button that routes away and a Keep editing button that cancels. The editor is read-only for versions whose `status != 'draft'`: all inputs disabled, no Save button, a banner says "This version is {published|archived}; create a new draft to make changes".
- **AC-13**: 422 errors from Save map to RHF `setError` via `apiFetch`'s existing `errors[].loc` wiring (spec 0008 AC-8). Backend Pydantic field paths used in `loc` map to editor fields as: `body.config.container_selector` → the container input, `body.config.fields.{N}.name` → that row's name input, `body.config.fields.{N}.selector` → that row's selector input, `body.config.output_schema` → the output_schema pane (shown as a dialog-level error above the pane since CodeMirror has no RHF binding), and the two coherence codes (`workflow.validation_error` with a `field` in `details[]`) also render on the matching row or pane.
- **AC-14**: Publish on a draft opens a confirm Sheet listing effects ("Promote this draft to published. If there is a current published version, it will be archived in the same transaction. The workflow's current version pointer will swap to this one.") and a Publish button. **Publish is disabled when the editor form is `dirty`** (tooltip "Save first; Publish promotes the server-stored config, not the browser's unsaved state") for the same reason Preview is gated at AC-18. On confirm, POST `/api/v1/workflows/:workflow_id/versions/:id/publish` runs. On success, invalidates `['workflows', id, 'versions']` and `['workflows', id]`. On 409 `workflow.version_conflict`, the Sheet shows a specific banner ("Another operator changed this workflow. Reload to see the latest state.") with a Reload button that refetches and closes the Sheet; the local draft is not re-POSTed.
- **AC-15**: Archive is available on a published version via an AlertDialog confirm, except when the version is the workflow's current published version: then the Archive action is disabled with a tooltip ("Publish a replacement first; archiving the current version would leave the workflow with no runnable version."). On 409 `workflow.version_is_current` or `workflow.version_not_published`, the dialog renders the specific error, refetches the version list, and stays open with Confirm disabled.
- **AC-16**: Delete on a draft version opens a plain confirm AlertDialog (no type-to-confirm; drafts are safer than workflow-level deletes), POSTs DELETE, invalidates `['workflows', id, 'versions']`, and on 409 `workflow.version_not_draft` renders a specific banner and refetches.
- **AC-17**: The Preview panel reads the workflow's parent `website_id` from the workflow query cache, loads active target URLs under that website via GET `/api/v1/websites/:website_id/targets?status=active&page_size=200`, and renders a Combobox picker. When the response's `total > 200`, the picker footer shows "Showing first 200 of {total} active targets" so the operator knows some are hidden (server-side Combobox search is deferred to Follow-up). `Run preview` sends POST `/api/v1/workflows/:workflow_id/versions/:vid/preview` with `{target_url}` (the full URL string of the picked target). A Cancel button is wired to an `AbortController` that aborts the fetch. On success, the panel renders a tabbed view: a shadcn `Table` of extracted items (one row per item, columns derived from the version's `output_schema` keys), a raw-JSON tab (CodeMirror read-only), and a `Copy JSON` button. On error, the panel renders the Problem Details (`code`, `title`, `detail`, `correlation_id`) with a Retry button; spec 0005's `FetchErrorCode` and `ExtractionErrorCode` values are shown by code with no custom per-code UI.
- **AC-18**: Preview is gated: `Run preview` is disabled when the editor form is `dirty` (tooltip "Save first"), when the target picker has no selection, or while a preview request is in flight. The gate on dirty exists because the backend previews the server-stored `config`, not the browser's unsaved state; running against a stale config would mislead the operator.
- **AC-19**: Every list (Websites, Targets, Workflows, Versions) and every empty detail area (a workflow with no versions, a website with no targets) renders an empty state card with a one-line description and a primary action button that opens the corresponding create Sheet or triggers `+ New draft`.
- **AC-20**: TanStack Router search param schemas are defined as Zod on each list route and parsed in `validateSearch`; invalid or out-of-range values fall back to defaults with no crash. TanStack Query keys follow a stable convention: `['websites', filters]`, `['websites', id]`, `['websites', id, 'targets', filters]`, `['workflows', filters]`, `['workflows', id]`, `['workflows', id, 'versions', filters]`, `['workflows', id, 'versions', vid]`. Every mutation invalidates the matching key families so lists and details refetch in one place.

## Decision

**Chosen option**: Option 1: Single-spec, five-area build on the existing admin UI shell with full-page detail routes, side-sheet mutations, and a split-pane version editor with a server-driven preview.

Workflow configuration ships as five linked screen areas inside the `frontend/` app shipped by spec 0008: Websites CRUD, Targets CRUD (nested under a website), Workflows CRUD, Workflow Versions (list + lifecycle actions + full editor), and Preview (inside the editor). The lists share one URL-synced search param pattern (page, page_size, status, with_deleted) via Zod-validated TanStack Router schemas. Create and edit happen in shadcn `Sheet`s off the list; destructive deletes on Websites and Workflows require typing the name in an `AlertDialog`; destructive deletes on Targets and draft Versions use a plain confirm. The workflow detail is a tabbed route (`Overview | Versions | Preview`), nested so the active tab lives in the URL. The version editor is a sub-route at `/workflows/:id/versions/:vid` with a split layout: a structured form (container_selector + repeatable fields rows + typed inputs) plus two CodeMirror 6 JSON panes (output_schema and optional pagination); Save issues a full-config PATCH per spec 0004's write-once-at-publish contract; a dirty indicator plus `Cmd/Ctrl+S` plus a `useBlocker` guard protect in-flight edits; non-draft versions render read-only. Preview runs in the right pane against a picker of the workflow's website's active targets, uses an `AbortController` for cancel, renders results as a table plus a raw-JSON tab plus a copy-to-clipboard button, and is gated on a clean form so the operator never previews stale state. The only new frontend dependencies are `@uiw/react-codemirror` and `@codemirror/lang-json` (~100 KB gzipped combined); no new backend surface is added.

**Implementation skills**:
- `shadcn-ui/ui` (`shadcn-ui/ui`, `.claude/skills/shadcn-ui/`) `Sheet`, `AlertDialog`, `Table`, `Tabs`, `Combobox`, `Tooltip` conventions
- `tanstack-query` (`deckardger/tanstack-agent-skills`, `.claude/skills/tanstack-query-best-practices/`) query keys, invalidation, optimistic updates, `useMutation` patterns
- `tanstack-router` (`deckardger/tanstack-agent-skills`, `.claude/skills/tanstack-start-best-practices/`) nested routes, `validateSearch`, `useBlocker`
- `react-hook-form` (`pproenca/dot-skills`, `.claude/skills/react-hook-form/`) field arrays, dirty state, `setError`, Zod resolvers
- `vitest` (`antfu/skills`, `.claude/skills/vitest/`) component test patterns
- `webapp-testing` (`anthropics/skills`, `.claude/skills/webapp-testing/`) Playwright patterns for the end-to-end flow

Skills are listed as pointers; a skill file is opened on demand during build. Any skill not yet installed per spec 0008's Follow-up stays flagged there.

## Rationale

Reasoning and options considered: see [`rationale.md`](rationale.md).

## Feature design

**Data model sketch**

No persistent schema changes. The feature consumes the tables defined by specs 0002 (websites, target_urls) and 0003 / 0004 (scraping_workflows, workflow_versions). Client-side state additions:

| Store / shape | Where | Persistence |
|---|---|---|
| Per-route search params (page, page_size, status, with_deleted, website_id?) | TanStack Router search param state | URL only; parsed via Zod `validateSearch` on each list route |
| Per-form state (RHF) for website / target / workflow / version metadata | React Hook Form instance in each Sheet or editor | In-memory; cleared on Sheet close or navigation |
| Draft config edit buffer for the version editor | RHF instance owned by the editor route | In-memory; dirty state gates Save and Preview; `useBlocker` warns on navigation; discarded on confirm |
| Preview result and in-flight state | Local `useState` + a `useRef<AbortController>` in the Preview panel | In-memory; cleared when the editor route unmounts |
| TanStack Query cache: `['websites', ...]`, `['workflows', ...]`, `['workflows', id, 'versions', ...]`, plus parent lookups | TanStack Query | In-memory; no persistence across reloads |

No new Zustand slices. `authStore` and `themeStore` (spec 0008) are unchanged.

**State transitions**

Session, workflow, and version lifecycles are owned by other specs (0008 for auth, 0004 for workflow + version). The UI reflects:
- Workflow: `active ↔ inactive` via Overview toggle (optimistic); soft delete terminal.
- Version: `draft` is editable; `draft → published` via Publish action; `published → archived` via Archive action, or auto-archived when a sibling draft is published; `archived` and `published` versions render read-only in the editor.
- Editor form: `pristine → dirty → saving → pristine` (success) or `saving → dirty` (error with inline messages).

**API surface** (consumed only; no new endpoints)

The UI calls the endpoints already pinned by specs 0002, 0004, 0005. Nothing is added:

| Endpoint | Method | Where called | Notes |
|---|---|---|---|
| `/api/v1/websites` | GET, POST | `/websites` list, Register Sheet | List is URL-synced; POST invalidates `['websites']` |
| `/api/v1/websites/{id}` | GET, PATCH, DELETE | `/websites/:id` detail, Edit Sheet, Delete dialog | PATCH/DELETE invalidate `['websites']` and `['websites', id]` |
| `/api/v1/websites/{id}/targets` | GET, POST | `/websites/:id` detail, Add target Sheet | POST invalidates `['websites', id, 'targets']` |
| `/api/v1/targets/{id}` | GET, PATCH, DELETE | Edit Sheet, Delete dialog | PATCH/DELETE invalidate `['websites', websiteId, 'targets']` |
| `/api/v1/websites/{website_id}/workflows` | POST | Register workflow Sheet | Invalidates `['workflows']` |
| `/api/v1/workflows` | n/a (nested only; backend offers a nested list) | n/a | Reads use `GET /api/v1/websites/{website_id}/workflows` per spec 0004 AC-3; the `/workflows` list route fetches by batching per website_id in the active filter, else iterates the first page of websites. See Build plan step 5 for the exact strategy. |
| `/api/v1/workflows/{id}` | GET, PATCH, DELETE | Detail route, Edit Sheet, Delete dialog | DELETE handles 409 `workflow.has_in_flight_executions` |
| `/api/v1/workflows/{workflow_id}/versions` | GET, POST | Versions tab, `+ New draft` | POST invalidates `['workflows', id, 'versions']` |
| `/api/v1/workflows/{workflow_id}/versions/{id}` | GET, PATCH, DELETE | Version editor, Save, Delete draft | PATCH is full-config replace per spec 0004 AC-9 |
| `/api/v1/workflows/{workflow_id}/versions/{id}/publish` | POST | Publish Sheet | Handles 409 `workflow.version_conflict` |
| `/api/v1/workflows/{workflow_id}/versions/{id}/archive` | POST | Archive dialog | Handles 409 `workflow.version_is_current`, `workflow.version_not_published` |
| `/api/v1/workflows/{workflow_id}/versions/{id}/preview` | POST | Preview panel | Request body `{target_url: str}`; aborts via `AbortController` |

**Note on `/api/v1/workflows` listing**: spec 0004 AC-3 exposes list only under the nested `/api/v1/websites/{website_id}/workflows`. The admin's `/workflows` list route therefore operates in two modes:
- When the operator picks a `website_id` filter, the list calls the nested endpoint directly.
- When no `website_id` filter is set, the list fetches the first page of active websites, then does a batched `useQueries` of the per-website workflow list, and client-flattens. This is acceptable for Slice 2's expected volume (dozens of websites), and flagged in Follow-up: a top-level `/api/v1/workflows` list would simplify this and belongs in a future backend spec once volume motivates it.

**Value sourcing** (every value an action produces or displays names its source; no undecided inputs)

| Action | Value produced / displayed | Source |
|---|---|---|
| `/websites` list | row columns | generated `openapi-typescript` types in `frontend/src/api/schema.d.ts` (spec 0008 AC-6) |
| `/websites` list | page / page_size / status / with_deleted | URL search params, parsed via Zod on `validateSearch`; invalid values fall back to defaults |
| Website Delete dialog | type-to-confirm target string | the website's canonical host from the row |
| `/websites/:id` detail | metadata values | GET `/api/v1/websites/:id` response |
| `/websites/:id` detail | nested target list | GET `/api/v1/websites/:id/targets` response; filters per AC-3 |
| `/workflows` list | parent website name per row | TanStack Query cache lookup on `['websites', workflow.website_id]`; cache miss falls back to a per-id GET batched via `useQueries` over the page's unique website_ids |
| `/workflows` list | current version number per row | `useQueries` fan-out over the page's unique non-null `current_version_id`s, keyed `['workflows', workflow_id, 'versions', version_id]`; em-dash when `current_version_id` is null |
| `+ New draft` navigation | provisional path | `/workflows/:id/versions/new` (no server-side POST; the editor route renders with the pinned seed `WorkflowConfig` from AC-9) |
| Version editor First Save (on `/versions/new`) | POST body | the current RHF form values (seeded from the AC-9 literal, then edited) serialized to a full `WorkflowConfig` |
| Version editor First Save success | next route | `router.navigate` to `/workflows/:id/versions/{created.id}` so subsequent Saves PATCH |
| "Add pagination" button | pane seed JSON | the literal `{"next_selector": "", "max_pages": 1}` (matches `PaginationSpec` in `src/app/domains/workflows/config.py`) |
| `fields[*].type` dropdown options | the five enum values | typed OpenAPI enum via `openapi-typescript` when present; else the pinned fallback `string`, `integer`, `decimal`, `boolean`, `url` from spec 0005 |
| `fields[*].transforms` chip values | free-form strings | operator-entered; server validates at publish per spec 0005 Follow-up on publish-time registry validation |
| `/workflows` list | row entries when no `website_id` filter | per-website GETs stitched client-side (see "Note on `/api/v1/workflows` listing") |
| `/workflows/:id` Overview | current published version number | if `workflow.current_version_id` is non-null, GET `['workflows', id, 'versions', current_version_id]` and show `version_number`; else em-dash |
| Workflow status toggle | optimistic next status value | the opposite of the current `workflow.status` in cache; rolled back on error from `['workflows', id]` previous snapshot |
| Version editor form | initial form values | GET `/api/v1/workflows/:id/versions/:vid` response's `config` |
| Version editor Save | PATCH body | the current RHF form values serialized to a full `WorkflowConfig` (per spec 0004 AC-9's full-config replace) |
| Preview panel | target URL options | GET `/api/v1/websites/:website_id/targets?status=active&page_size=200` where `:website_id` comes from the parent workflow's cached entry |
| Preview panel | preview request body | `{target_url: <picked target.url>}` (the full URL field from the target row) |
| Preview panel | items table columns | keys of the version's `output_schema` (not the fetched preview's shape, so empty results still render column headers) |
| Error dialog / banner correlation id | correlation id | `ApiError.correlation_id` from `apiFetch` (spec 0008 AC-8, spec 0007) |
| Mutation success invalidation | affected query keys | by convention, every mutation names its invalidation targets (listed in the API table) |

**Key invariants**

- Every list route exposes its filters in the URL via a Zod `validateSearch`; no filter state is kept in component state. Reload or deep-link produces the same list.
- Every mutation goes through TanStack Query's `useMutation` with explicit `onSuccess` (invalidate) or `onMutate` (optimistic) hooks; no component calls `apiFetch` outside this pattern.
- Every editor path (Sheet or full editor) owns one RHF form instance; `apiFetch` is the only path to the backend; 422 errors reach fields via `errors[].loc` → `setError`.
- The version editor's Save path is a full-config PATCH only. There is no partial-merge save, no auto-save, and no local-only "edit until Publish" mode. This matches spec 0004 AC-9 exactly.
- Preview never runs against unsaved edits. The gate is a boolean of the RHF form's `dirty` flag; there is no "preview this unsaved config" escape hatch.
- Non-draft versions render read-only. The editor cannot write to a `published` or `archived` row via Save, Delete, or any other mutation; the UI mirrors spec 0004 AC-9 and AC-10.
- Destructive deletes on Websites and Workflows require typing the name; destructive deletes on Targets and draft Versions use a plain confirm. The threshold is: "the entity can hold meaningful downstream state (targets under a website, versions and executions under a workflow)".
- 409 conflicts are shown with the specific error code and remediation, not a generic "something went wrong". The three load-bearing codes to handle: `workflow.has_in_flight_executions` (delete workflow), `workflow.version_conflict` (publish race), `workflow.version_is_current` (archive current).
- `AbortController` is wired into every long-running request this feature issues (preview is the only one today); a user-initiated cancel aborts the in-flight fetch without crashing the panel.

**Security model**

- Same as spec 0008. The admin UI is operator-only, API-key-authenticated via `require_api_key` on every `/api/v1/*` endpoint. No role differentiation. No new secrets, no new compliance scope, no PII.
- `apiFetch` is the only path to the backend, so the `X-API-Key` header injection and the global 401 handler (both from spec 0008) cover every request this feature makes.
- Preview reads a target URL from the operator's registered targets; no free-text URL input, so the SSRF surface for this feature is bounded to URLs the operator already asserted are legitimate. Backend-side SSRF controls are feature 27 and out of scope here.
- No data leaves the browser. The `Copy JSON` button writes to the clipboard; it does not POST anywhere.

**Configuration required**

None. No new backend settings, no new frontend env vars. The feature uses only `ADMIN_API_KEY`, `SERVE_ADMIN_UI`, and `ADMIN_UI_DIST_PATH` from spec 0008.

**Critical test scenarios** (each maps to an acceptance criterion in `## Requirements`)

- End-to-end happy path (Playwright): sign in, register a website, add a target, register a workflow under the website, open the version editor on the auto-created draft, fill in `container_selector`, add one field with a matching `output_schema` key, Save, pick the target in Preview, Run preview, see one or more items in the results table, Publish. Verifies **AC-1**, **AC-2**, **AC-3**, **AC-4**, **AC-5**, **AC-6**, **AC-9**, **AC-11**, **AC-12**, **AC-14**, **AC-17**.
- Full-config PATCH + inline 422 (Vitest): edit a draft, remove a required field, Save, expect the form field to show the Pydantic error via `errors[].loc` → `setError`. Verifies **AC-12**, **AC-13**.
- Publish race (Vitest): mock a 409 `workflow.version_conflict` on POST publish; assert the Sheet banner, the Reload button triggers a refetch, and the local draft is not re-POSTed. Verifies **AC-14**.
- Archive the current published version (Vitest): render the version row for the workflow's current version; assert Archive is disabled with the correct tooltip; simulate a backend `workflow.version_is_current` from a race and assert the dialog shows the specific error and refetches. Verifies **AC-15**.
- Delete workflow with in-flight executions (Vitest): mock 409 `workflow.has_in_flight_executions`; assert the inline dialog banner lists the reason and Delete stays disabled. Verifies **AC-6**.
- Preview dirty gate (Vitest): edit a draft without saving; assert `Run preview` is disabled with a "Save first" tooltip; Save; assert it enables. Verifies **AC-18**.
- Preview cancel (Vitest): start a preview, click Cancel; assert the fetch is aborted via `AbortController` and the panel exits the in-flight state without rendering a crash. Verifies **AC-17**.
- URL-synced filters (Vitest): deep-link to `/workflows?page=3&status=active`; assert the list fetches page 3 with status=active and the filter chips render pre-selected; invalid `?page=abc` falls back to `page=1`. Verifies **AC-5**, **AC-20**.
- Optimistic status toggle rollback (Vitest): mock a 500 on PATCH; assert the Overview toggle flips, then rolls back on error, with a toast carrying `correlation_id`. Verifies **AC-8**.
- Read-only non-draft version (Vitest): render the editor on a published version; assert all inputs disabled, Save absent, banner present. Verifies **AC-12**.
- Empty states (Vitest): render each list and the two empty detail areas with no rows; assert the empty state card and its primary action button. Verifies **AC-19**.

## Build plan

Skateboard order: thinnest usable whole first (register a website, then a workflow under it, then a draft version, then preview, then publish), then add the surrounding CRUD and lifecycle actions. Six milestones, each shippable; the two CodeMirror dependencies land in milestone 3 where they are first used.

1. ✅ **Shared list, Sheet, and TanStack Router search param primitives** (satisfies **AC-1** scaffolding, **AC-19** scaffolding, **AC-20**): add shared components under `frontend/src/components/` (`DataTable` wrapping shadcn `Table` with pagination controls, `FilterBar`, `EmptyState`, `CrudSheet`), a Zod helper for the common search param schema (`page`, `page_size`, `status?`, `with_deleted?`), a `useListQuery` hook that composes URL search params with TanStack Query keys and `useQueries` for the batched-parent-lookup pattern. Document the query-key convention in a short header comment in `frontend/src/api/queryKeys.ts`.
2. **Websites CRUD + Targets CRUD** (satisfies **AC-1**, **AC-2**, **AC-3**, **AC-4**, **AC-19**): extend `/_authed/websites.tsx` from spec 0008 with the full URL-synced list, Register / Edit Sheet, Delete AlertDialog with type-to-confirm; add `/_authed/websites.$id.tsx` detail route with metadata plus nested targets list, Add target Sheet, Edit / Delete target. All mutations run through `useMutation` with explicit invalidation.
3. **Workflows list, create, detail with tabs** (satisfies **AC-5**, **AC-6**, **AC-7**, **AC-8**, **AC-19**): add `/_authed/workflows.tsx` list with the two-mode fetch (nested per website, or stitched when no `website_id` filter), Register workflow Sheet with Combobox website picker, Delete AlertDialog with type-to-confirm plus 409 handler; add `/_authed/workflows.$id.tsx` as a parent route that redirects `/workflows/:id` → `/workflows/:id/overview`; add `/_authed/workflows.$id.overview.tsx` with metadata plus optimistic status toggle plus parent website link.
4. **Versions tab + lifecycle actions** (satisfies **AC-9**, **AC-14**, **AC-15**, **AC-16**): add `/_authed/workflows.$id.versions.tsx` listing versions with URL-synced status filter, `+ New draft` button that navigates to `/workflows/:id/versions/new` **without issuing a POST** (the editor's First Save creates the row), per-row Publish / Archive / Delete actions and dialogs with the full set of 409 handlers (`version_conflict`, `version_is_current`, `version_not_published`, `version_not_draft`); Publish is dirty-gated.
5. **Version editor route + config form + CodeMirror panes** (satisfies **AC-10**, **AC-11**, **AC-12**, **AC-13**): add dev deps `@uiw/react-codemirror` and `@codemirror/lang-json`; add two route files sharing one editor component: `/_authed/workflows.$id.versions.new.tsx` (seeded with the pinned literal `WorkflowConfig` from AC-9; First Save POSTs and then `router.navigate` to the created `:vid`), and `/_authed/workflows.$id.versions.$vid.tsx` (loads the row and Saves via PATCH). Both render the split layout (left pane editor, right pane placeholder for Preview); build the RHF form (container_selector + repeatable fields rows with typed inputs + CodeMirror panes for output_schema and the optional pagination with its "Add pagination" seed), the Zod schema mirroring `WorkflowConfig`, the dirty indicator, `Cmd/Ctrl+S` keyboard shortcut, `useBlocker` navigation guard, the client-side duplicate-name and output_schema-coverage warnings; wire Save to full-config POST (new) or PATCH (existing); render read-only for non-draft versions.
6. **Preview panel + end-to-end smoke test + unit tests + nested AGENTS.md** (satisfies **AC-17**, **AC-18**, every critical test scenario, follow-up docs): add the Preview panel inside the editor route's right pane (target picker, `Run preview` with `AbortController`, Table + raw-JSON tabs, Copy JSON, Problem Details rendering with Retry); add Vitest tests enumerated in Critical test scenarios; extend the spec 0008 Playwright smoke to cover the end-to-end flow (register website → target → workflow → draft → save → preview → publish); flag in Follow-up that `frontend/AGENTS.md` should capture the list / Sheet / editor conventions established here (owned by `/audit` or `/sync`, not this feature).

## Consequences

**Positive**:
- The scope row's `done when: a user can create a workflow end-to-end from the UI and run a preview` is satisfied without any new backend endpoints; every missing capability from spec 0008 lands in this one feature.
- The list / Sheet / detail-with-tabs / split-pane-editor pattern becomes the shell convention for Feature 11 (Execution browser) and later admin screens. One set of primitives, one search param convention, one query-key convention.
- Full-config PATCH on draft matches spec 0004 AC-9 1:1, so no "merge semantics" bug can appear.
- The split-pane editor plus the dirty-gated preview keeps the edit-preview-publish loop in one screen; no tab juggling.
- The two CodeMirror dependencies are ~100 KB gzipped combined; small compared to a Monaco bundle, and tree-shakable.
- Every 409 the backend can emit for this surface has a specific UI remediation, so operators never see a generic error wall.

**Negative / tradeoffs**:
- The `/workflows` list has to stitch results client-side when no `website_id` filter is set, because spec 0004 did not add a top-level list endpoint. Fine for Slice 2's expected volume; flagged in Follow-up to add a top-level list once volume motivates it.
- The structured fields editor + raw-JSON output_schema pane is a two-mode UX; some operators will miss that `output_schema` is JSON (not a form). Mitigated by inline guidance text above the pane and by client-side coverage warnings.
- Full-config PATCH means every save re-sends the entire WorkflowConfig; harmless at MVP sizes but inefficient for very large configs. Acceptable because configs are small for Slice 2 scrape targets; a merge-patch spec was deferred by spec 0004 Follow-up and remains deferred.
- The optimistic status toggle complicates the mental model when a mutation fails mid-flight. Mitigated by the toast carrying the `correlation_id` so an operator can hand it to support.
- **Draft PATCH is last-write-wins across concurrent operators.** The backend has no `If-Match` / etag today (spec 0004 pins conflict detection at publish time only, via `workflow.version_conflict`). Two operators editing the same draft silently overwrite each other on Save; the race only surfaces at Publish. Acceptable for Slice 2's one-operator-at-a-time reality; flagged in Follow-up for a backend optimistic-concurrency spec once a second operator shows up.
- Adding `@uiw/react-codemirror` introduces another transitive dependency surface area to maintain (though both packages are mature). Reversible: swap for a plain textarea at a day of work.
- Scope row Feature 10 was `· needs a decision` and ships as a sizable feature (six milestones, 20 ACs). This is faithful to the "end-to-end workflow authoring" scope; a smaller skateboard was offered during the interview and rejected in favor of the full area.

**Neutral**:
- Two new dev-dependencies in `frontend/package.json`: `@uiw/react-codemirror` and `@codemirror/lang-json`.
- No new backend endpoints, no new environment variables, no new error codes.
- Design system stays shadcn/ui copy-in; no new design tokens. Any adjustments live in `frontend/src/components/`.
- `AGENTS.md` is unchanged by this spec; a nested `frontend/AGENTS.md` capturing the list / Sheet / editor conventions is enrolled as a Follow-up for `/audit` or `/sync` to pick up.

## Follow-up

- [ ] Flag to a future backend spec: add optimistic-concurrency to draft PATCH on `/api/v1/workflows/:id/versions/:vid` (return and require an `ETag` / `If-Match` on the row's `updated_at`), so two operators editing the same draft get a `412 Precondition Failed` instead of silent last-write-wins. Not needed today (one operator at a time); worth adding once a second operator shows up.
- [ ] Flag to a future admin spec: add server-side search for the Preview target picker Combobox (today it loads up to 200 active targets per website and shows a "showing first 200 of N" footer when `total > 200`). Not needed until a website has that many active targets.
- [ ] Flag to a future backend spec: add a top-level `GET /api/v1/workflows` list (with `website_id`, `status`, `with_deleted` filters) once admin volume makes the client-stitching in milestone 3 awkward. Spec 0004's "scoped to a website" shape was the right call for Slice 1; this feature's two-mode fetch is a workaround, not a long-term pattern.
- [ ] A per-field merge-patch endpoint for `WorkflowConfig` (RFC 7396) is still deferred (per spec 0004 Follow-up). Revisit if operators report edit-loop friction with full-config PATCH on larger configs.
- [ ] A dedicated `/workflows/:id/versions/:vid/preview` route (deep-linkable preview) is deliberately out of scope here (the Preview tab exists at the workflow level per AC-7, and the editor's Preview pane covers the common case); add later if an operator asks to share a preview URL.
- [ ] A nested `frontend/AGENTS.md` should capture the list / Sheet / detail-tabs / split-pane-editor conventions established in this feature plus the query-key convention; owned by `/audit` or `/sync`, not this feature.
- [ ] Spec 0008 Follow-up still owes an `AGENTS.md` capture of frontend skills and conventions; that work would also absorb this feature's conventions in one pass.
- [ ] Consider a shared `useProblemDetailsErrorRenderer` hook that AC-14, AC-15, AC-16, AC-17 all use (they re-render Problem Details four times). Low priority; worth it only if Feature 11 duplicates the shape.
