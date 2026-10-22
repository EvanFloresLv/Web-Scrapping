# 0010. Execution browser — rationale

## Context

Spec 0006 landed the executions domain end to end: the `executions` and `execution_results` tables (defined by spec 0003), the two commit lifecycle (`running → completed | failed`), the `POST /api/v1/workflows/{id}/execute` endpoint, and a single row read (`GET /api/v1/executions/{id}`). It does not ship a list endpoint, and there is no admin UI for browsing past runs. Today an operator who wants to answer "what has run, which failed, and why" either reads the raw table or scrapes structlog by hand.

The forces that shape this spec:

1. **The scope row's done when is tight**: "the list paginates, filters work, and a run detail view renders JSON output, error reasons, and timing." It is a browsing surface, not an operations console. Any action (re-run, cancel, delete) adds moving parts that the row did not ask for.
2. **The executions table is unbounded and filterable.** A sync executor can emit a row per operator click today; the async worker (feature 23) will emit many more. OFFSET pagination gets slow fast on that shape, and COUNT(*) over a growing filterable table pays a tax on every page view. The AGENTS.md convention is explicit: cursor pagination for executions and products.
3. **The admin UI already has a shell convention** from spec 0008 and spec 0009: Zod `validateSearch` for URL-synced filters, `DataTable` + `FilterBar` + `EmptyState`, TanStack Query key families with explicit invalidation, and Problem Details rendering. Any new admin screen that reinvents these loses that convention.
4. **The executions domain is read heavy from the UI side.** A browser screen that never writes to the executions table is simpler than one that offers actions; the one actionable path (re-run) already exists as `POST /execute` and can be called from curl today for anyone who needs it.
5. **The one hygiene gap in the data model is a correlation id lookup.** Spec 0003 added three composite indexes keyed by `created_at` for the common sort, but `correlation_id` has no index. A support flow (operator pastes a correlation id, lands on the row) is the one filter that would seq-scan without new schema.

The consequence of not deciding: the admin UI stays frozen at the shell shipped by spec 0008 with a placeholder `/executions` route, and operators keep answering lifecycle questions by SSH-ing to Postgres. Feature 11 is also the shape the next three features in Slice 3 (observability) will build on, so an inconsistent shell here would be felt three times over.

## Options considered

### Option 1: Single feature, read only, list endpoint + two screens, reuses spec 0009's primitives

One new endpoint (`GET /api/v1/executions`) with cursor pagination and six filters, one Alembic revision (the `correlation_id` index), one list screen, one detail screen. The screens reuse spec 0009's `DataTable`, `FilterBar`, `EmptyState`, Zod `validateSearch` convention, Problem Details renderer, and TanStack Query key convention. Auto refresh is a client only pattern (conditional `refetchInterval` on the TanStack Query query); no new backend transport. Raw HTML, JSON diff, re-run, cancel are all explicitly out of scope.

**Pros**:
- Satisfies the scope row's `done when` with the smallest new surface area.
- Reuses every list primitive spec 0009 already shipped; the admin convention stays one pattern.
- No new backend infra (no SSE/WebSocket, no blob store, no new auth model).
- Auto refresh is bounded (polls only while an in-flight row is visible), so the view is idle at zero cost once nothing is running.
- One Alembic revision, one new index, no new tables, no changes to the lifecycle spec 0006 pins.

**Cons**:
- No `total` on the list response. Operators see "Showing N on this page" + Next, not "page 1 of X". Deliberate: COUNT(*) over a growing filterable table is a real cost and the UI does not actually need the total for anything load bearing.
- Cursor is forward only; there is no Previous button. An operator who wants to come back to page 2 bookmarks the cursor URL. Deferable.
- No raw HTML and no JSON diff vs the previous execution. Both would help real extraction debugging; both are big and each is a load bearing decision on its own (storage shape, retention, redaction).

### Option 2: Read only browse + a Re-run button on the detail

Everything in Option 1 plus a single Re-run button on the detail that POSTs the same body spec 0006's `POST /execute` already takes. No cancel, no delete.

**Pros**:
- One ergonomic win over Option 1: an operator can re-run a failing extraction from the UI without pasting into curl.
- Adds no new endpoint; reuses `POST /execute` as-is.

**Cons**:
- Mixes browsing with mutation; the scope row did not ask for an action.
- Needs a confirm dialog, a success/failure toast, a loading state, and invalidation of the executions list; small code, nonzero scope.
- A re-run is also a decision point (should it re-use the same `version_id`? the current published one? expose the choice?), which pulls more UX in.
- The decision is cheap to reverse: add it as a one-task follow-up spec once an operator asks.

### Option 3: Full operations console (re-run, cancel, soft delete, bulk actions)

Everything in Option 2 plus a cancel button for `running` rows, a soft delete action for operator hygiene, and bulk-select for deleting a range of old failed runs.

**Pros**:
- Richer operator surface.
- Soft delete lets operators prune noise from the browser.

**Cons**:
- Cancel does not exist in the backend (the sync executor is uncancellable; it blocks on `httpx` + extraction and commits on return). Cancel is a feature of the async worker (feature 23), which does not exist yet. Shipping a Cancel button that silently does nothing is worse than no button.
- Soft delete needs a new column (`executions.hidden_at` or `deleted_at`), a new filter, and a new Problem Details code; it changes the executions schema.
- Overshoots the scope row by a wide margin. The scope row's `done when` is browse + open; this option adds four actions.

## Rationale

Option 1 wins because the scope row asks for browse + open and names no action. Spec 0006 already ships the write path and the single row read; this feature only needs to add the list endpoint and the two screens. Reusing spec 0009's shell primitives keeps the admin convention one pattern (so feature 12's metrics dashboard and feature 11+'s later screens inherit the same list/filter/empty-state/error-render story without redeciding).

The cursor pagination choice is pinned by AGENTS.md (`cursor pagination for executions and products`) and justified by the forces above: the table is unbounded and filterable, OFFSET gets slow fast on it, and the UI does not need a total count for anything load bearing. The opaque `base64url(JSON.stringify({c, i}))` cursor shape is picked over structured `?before_created_at=&before_id=` params because the opaque form keeps the sort key private to the server; changing the sort key later never breaks a client.

Omitting `total` is a deliberate tradeoff and the one place Option 1 is less friendly than Option 2 or Option 3 would be. The alternative (`total` always, via COUNT(*) under the same WHERE) is the slow path on an unbounded filterable table; the partial alternative (`total` only when both `created_from` and `created_to` are set) is tidy but creates a conditional UX ("sometimes you see the total, sometimes you don't") that is harder to reason about than "we never show it". We pick the strict form.

Re-run (Option 2) is attractive but rejected for this slice on the grounds that mixing browsing with mutation is a one way door for the shell. The one-click re-run can land as a two task follow-up spec the moment an operator asks for it, costing nothing today.

Full operations (Option 3) is rejected because cancel is a dead feature without the async worker and soft delete is a schema decision the scope row did not ask for.

Two filters were added beyond the scope row's three (`website_id` and `correlation_id`), each justified: `website_id` makes the executions browser symmetric with the websites/workflows screens spec 0009 shipped (an operator viewing a website expects to see its executions), and `correlation_id` is the one hygiene flow that would otherwise seq-scan on a correlation id handed over from a support ticket. The `error_code` filter was explicitly dropped because it needs a different index strategy (GIN or a careful btree on a frequently-null column) and is a niche flow that structlog already answers today.

Auto refresh over push is motivated by scale, not laziness: a 3 s poll on the list query is a 20 request/minute per idle operator cost on a filtered, indexed query, and it stops the moment nothing is in flight. A push transport would need a new backend lifecycle (connection management, auth over the socket, backpressure, client reconnect), and no other feature in the roadmap uses it yet; adding it here would be the first adopter of a non-trivial new convention. If feature 12 (metrics dashboard) or feature 14 (Langfuse trace stream) later wants a push transport, this spec's auto refresh is cheap to retire.
