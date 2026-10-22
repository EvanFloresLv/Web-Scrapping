# 0008. Admin UI foundation

**Date**: 2026-10-21
**Status**: In Progress

## Summary

Pick the admin UI stack and ship the thinnest usable shell on top of it, so later screens (Features 10 and 11) have somewhere to land. The UI is a React single page app under `frontend/` that talks to the FastAPI backend over the existing `/api/v1` surface, signs in with an API key (a stub to be replaced by Feature 26 later), and shows real list screens for Websites and Targets plus empty state placeholders for Workflows and Executions. In development the Vite server proxies to uvicorn; in production FastAPI serves the built static assets at the same origin, so there is no CORS to configure anywhere.

## Requirements

**User stories**:
- As an operator, I want to open the admin UI, sign in with my API key, and reach a familiar shell with a sidebar so I know the tool is working.
- As an operator, I want to see the websites and target URLs that are already in the system without touching curl, so I can trust the backend data is really there.
- As a backend engineer building Feature 10 or 11, I want a stack with typed API calls, forms, server state, and routing already wired, so my screen is a drop in next to the empty state placeholders.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable):
- **AC-1**: Running `pnpm dev` from `frontend/` boots a Vite dev server at `http://localhost:5173` that proxies every `/api/*`, `/health/*`, `/docs`, `/redoc`, and `/openapi.json` request to `http://localhost:8000` (uvicorn) with no CORS configuration on either side. The proxied path list exactly mirrors the production mount's reserved paths (AC-10), so a call that works in dev also works in prod.
- **AC-2**: An unauthenticated visit to any route other than `/login` redirects to `/login`, preserving the original path as a `redirect` search param. The accepted shape is `^/[a-zA-Z0-9/_-]*$` (same origin only, no `//`, no scheme); any other value falls back to `/websites` on success. Guards against open redirect.
- **AC-3**: `/login` accepts an API key in a single text input; on submit it probes the key with `GET /api/v1/websites?limit=1` (a cheap authenticated read) before storing anything. On `200` it stores the key in `localStorage` under `admin.apiKey`, sets the Zustand auth store to signed in, and navigates to the `redirect` param (whitelisted per AC-2) or `/websites`. On `401` it surfaces an inline React Hook Form error ("Key rejected") on the input and does not store anything; this is the only path where a 401 does not trigger the global redirect handler.
- **AC-4**: Every API request from the UI sends an `X-API-Key` header carrying the stored key. The global 401 handler fires only when `authStore.isSignedIn` was already `true` (so a cold reload or a wrong login does not loop); it clears `localStorage['admin.apiKey']`, resets the auth store, resets the single shot "redirecting" flag, and navigates to `/login` once. The flag is also reset inside `signIn()` and on `router.subscribe('onLoad')` so later legitimate 401s still redirect.
- **AC-5**: The authenticated shell renders a persistent left sidebar with four navigation items (Websites, Targets, Workflows, Executions) and a top header with a signed in indicator, a light/dark/system theme toggle, and a sign out action.
- **AC-6**: `/websites` fetches `GET /api/v1/websites` via TanStack Query and renders either the list or an empty state card ("No websites registered yet. Register one via `POST /api/v1/websites`."). The displayed columns are read directly from the generated `openapi-typescript` types (the source of truth is spec 0002's response schemas, projected into `schema.d.ts`); no field name is hand mirrored in the component. The same contract holds for `/targets` against `GET /api/v1/targets`.
- **AC-7**: `/workflows` and `/executions` render static empty state placeholders ("This screen lands in Feature 10/11.") with no API call.
- **AC-8**: Any response with `Content-Type: application/problem+json` is parsed by the shared `apiFetch` wrapper into an `ApiError` object exposing `code`, `title`, `detail`, `errors[]` (each with `loc` and `msg`), and `correlation_id`. The wrapper routes the error by shape, not by status: when `errors[]` is non empty AND the caller passed a React Hook Form context, each `loc` is mapped to `setError` (inline field errors); unmapped entries and all other `ApiError`s surface as a toast (shadcn/ui Sonner) that always shows the `correlation_id`. A TanStack Router loader failure renders through a route error boundary that shows `code`, `title`, `detail`, and `correlation_id` plus a Retry action.
- **AC-9**: The FastAPI backend gains a `require_api_key` dependency reading `ADMIN_API_KEY` from settings. Every router under `/api/v1` carries it, except `/api/v1/_meta/error-codes` (`/health/*` is not under `/api/v1` and stays public already). On a missing or mismatched header, the dependency raises an `AdminUIUnauthenticated(PlatformError)` with `code="admin_ui.unauthenticated"` and `http_status=401`, so the existing spec 0007 Problem Details handler renders it with `correlation_id`; the dependency never raises a bare `HTTPException` (which would bypass the Problem Details shape). Comparison uses `hmac.compare_digest` against the configured key.
- **AC-10**: `pnpm build` emits `frontend/dist/`. When `SERVE_ADMIN_UI=true` and `frontend/dist/index.html` exists, FastAPI mounts the SPA router AFTER every API, health, docs, redoc, and openapi route has been registered, so no SPA route can shadow a backend one. The SPA router does two things: (a) for any GET whose path begins with `/api/`, `/health/`, `/docs`, `/redoc`, `/openapi.json`, or `/assets/` it does nothing (falls through to the backend's existing 404 shape, which stays Problem Details JSON); (b) for any other GET it inspects the `Accept` header, serves `index.html` only when `Accept` contains `text/html` (so a typed JSON client that misroutes a call gets a JSON 404, not SPA HTML), and 404s otherwise. Static assets from `frontend/dist/assets/` are served via a dedicated `StaticFiles` mount at `/assets/`.
- **AC-11**: The scripts `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm e2e` all exist and exit `0` on the committed shell.
- **AC-12**: A Playwright smoke test signs in with a known dev key, lands on `/websites`, toggles the theme, signs out, and verifies the redirect to `/login`.
- **AC-13**: A Husky pre commit hook runs `biome check --fix` on staged frontend files only (via lint staged); staging only backend files does not invoke it.
- **AC-14**: The dark mode toggle persists its selection in `localStorage` under `admin.theme`; the default is `system` (follows `prefers-color-scheme`); the choice applies without a page reload.
- **AC-15**: TypeScript runs in `strict` mode; `biome check --error-on-warnings` runs clean on the committed shell.
- **AC-16**: `pnpm gen:api` reads `http://localhost:8000/openapi.json` and writes `frontend/src/api/schema.d.ts`; the generated file is checked in; neither pre commit nor CI regenerates it silently.
- **AC-17**: `pnpm@10.13.0` is pinned exactly (not `10.x.y`) in `packageManager`; the README's "first time setup" section documents `corepack enable && corepack prepare pnpm@10.13.0 --activate` as the entry point for a new contributor, so a fresh clone does not need a global pnpm install.
- **AC-18**: Backend request logging middleware (structlog, spec 0007) redacts the `x-api-key` and `authorization` request headers before serialization, so a captured key never lands in logs. The Playwright smoke test's trace recording also redacts the key via a `page.route` interceptor, so CI artifacts stay clean.
- **AC-19**: The Zustand `authStore` is hydrated synchronously at module load (reading `localStorage` directly, not via `persist` middleware's async rehydrate); the router's `beforeLoad` on every protected route gates on `authStore.isHydrated === true` to eliminate the hydration race on cold reload.

## Decision

**Chosen option**: Option 1: React 19 SPA served separately, with the stack walked out below.

Admin UI foundation is a React 19 single page app bundled by Vite 8, written in TypeScript 7 strict, styled with Tailwind CSS 4 plus shadcn/ui copy in components, routed by TanStack Router with typed routes, backed by TanStack Query for server state and Zustand for the handful of client state slices (auth, theme, toasts). Forms use React Hook Form with Zod resolvers. The API client is `openapi-fetch` over types generated by `openapi-typescript` from FastAPI's OpenAPI. Lint and format go through Biome 2 (one Rust binary, matching the backend's "ruff is one tool" discipline). Testing uses Vitest plus Testing Library for components and Playwright for a thin smoke suite. The code lives in a `frontend/` subdirectory of this repo (one PR per change that touches both ends), pnpm 10 is the package manager, Node LTS 22 is pinned via `.nvmrc` and `packageManager`. In development the Vite dev server proxies `/api` to uvicorn; in production FastAPI mounts `StaticFiles` to serve `frontend/dist/` at the same origin, so no CORS is ever configured. Authentication is a stub: a login form stores an API key in `localStorage` and sends it in `X-API-Key`; the backend adds a `require_api_key` dependency reading `ADMIN_API_KEY` from pydantic settings. Feature 26 later replaces the mechanism without touching the shell's auth boundary.

**Implementation skills**:
- `shadcn-ui/ui` (`shadcn-ui/ui`, `.claude/skills/shadcn-ui/`) component conventions, CLI, theming
- `tanstack-query` (`deckardger/tanstack-agent-skills`, `.claude/skills/tanstack-query-best-practices/`) query keys, invalidation, mutations
- `tanstack-router` (`deckardger/tanstack-agent-skills`, `.claude/skills/tanstack-start-best-practices/`) typed routes, loaders, search params
- `react-hook-form` (`pproenca/dot-skills`, `.claude/skills/react-hook-form/`) form patterns with Zod and shadcn `<Form>`
- `ultracite` (`haydenbleasel/ultracite`, `.claude/skills/ultracite/`) Biome config bundle
- `vitest` (`antfu/skills`, `.claude/skills/vitest/`) Vitest conventions
- `webapp-testing` (`anthropics/skills`, `.claude/skills/webapp-testing/`) Playwright patterns from Anthropic

Skills are not installed yet (the registry CLI was not reachable during spec authoring); see Follow up.

## Rationale

Reasoning, options considered, references: see [rationale.md](./rationale.md).

## Feature design

**Data model sketch**:

No persistent schema changes. Client side state only:

| Store | Shape | Persistence |
|---|---|---|
| Zustand `authStore` | `{ apiKey: string \| null; isSignedIn: boolean; signIn(key); signOut() }` | Hydrated from `localStorage['admin.apiKey']` on boot |
| Zustand `themeStore` | `{ theme: 'light' \| 'dark' \| 'system'; setTheme(t) }` | Persisted to `localStorage['admin.theme']`, defaults to `system` |
| TanStack Query cache | Server state: `['websites']`, `['targets']` | In memory, no persistence |

**State transitions** (session lifecycle):

```
signed-out --(submit valid key)-->  signed-in
signed-in  --(401 from API)------>  signed-out  (apiKey cleared, redirect to /login)
signed-in  --(click sign out)---->  signed-out
```

**API surface**:

Backend adds:

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| (dependency) `require_api_key` | n/a | `X-API-Key` header | signed in request state | n/a | `401 admin_ui.unauthenticated` on missing or wrong key |
| `/` (SPA fallback mount) | GET | path | `index.html` | public | n/a; falls back to backend 404 for `/api/*` and `/health/*` |
| `/assets/*` (static mount) | GET | path | file bytes | public | 404 missing file |

Frontend consumes (no new backend endpoints beyond the dependency and static mount):

| Route (UI) | Calls | Notes |
|---|---|---|
| `/login` | none | Local only; submit triggers auth store signIn |
| `/websites` | `GET /api/v1/websites` | TanStack Query loader on route |
| `/targets` | `GET /api/v1/targets` | TanStack Query loader on route |
| `/workflows` | none | Static placeholder |
| `/executions` | none | Static placeholder |

**Value sourcing** (every value an action produces or displays names its source; no undecided inputs):

| Action | Value produced / displayed | Source |
|---|---|---|
| `apiFetch(path, init)` | `X-API-Key` header value | `authStore.apiKey` (hydrated synchronously from `localStorage['admin.apiKey']` at module load; `authStore.isHydrated` gates protected routes) |
| `apiFetch(path, init)` | form field errors (set via RHF `setError`) | `ApiError.errors[].loc` + `.msg`, when a form context is passed |
| Login submit | key accepted / rejected | result of `GET /api/v1/websites?limit=1` probe (200 vs 401), before anything is written to `localStorage` |
| Protected route guard | `redirect` search param value used after login | validated against `^/[a-zA-Z0-9/_-]*$`; invalid or absent → `/websites` |
| `apiFetch(path, init)` | `ApiError.code`, `.title`, `.detail`, `.errors[]`, `.correlation_id` | Parsed from the backend's `application/problem+json` body (spec 0007 contract) |
| Toast on unexpected error | `correlation_id` displayed | `ApiError.correlation_id` (backend sets it from `X-Request-ID`, spec 0007) |
| `/websites` list row | each displayed column | generated `openapi-typescript` types in `frontend/src/api/schema.d.ts` (projected from spec 0002's response schema); no hand mirrored field names |
| `/targets` list row | each displayed column | generated `openapi-typescript` types in `frontend/src/api/schema.d.ts` (projected from spec 0002's response schema); no hand mirrored field names |
| Theme applied to `<html>` class | `light` or `dark` | `themeStore.theme` resolved against `window.matchMedia('(prefers-color-scheme: dark)')` when `system` |
| Login redirect target | path to navigate to on success | `redirect` search param on `/login`, else `/websites` |
| `require_api_key` acceptance | the key to compare against | `settings.ADMIN_API_KEY` (pydantic settings, loaded at startup) |

**Key invariants**:
- The frontend never embeds a real API key in source or env defaults. `.env.local.example` lists `VITE_DEV_API_KEY_HINT` as documentation only; the actual key is pasted into the login form.
- The frontend sends `X-API-Key` on every `/api/*` request through one shared `apiFetch` wrapper. No request bypasses the wrapper.
- The backend's `require_api_key` is applied once at the router group level (`/api/v1/*`), not per endpoint, so there is no "forgot to add it" failure mode.
- A single login redirect per 401 (an atomic "redirecting" flag in `authStore`, reset in `signIn()` and on `router.subscribe('onLoad')`) so a cascade of failed queries cannot cause a redirect loop.
- Auth is header only: no cookie is ever read for auth, so the stub is CSRF safe out of the box (a custom header triggers a browser preflight, which cross site forms cannot replay). Feature 26 may introduce cookies but must keep CSRF protection explicit and documented.
- `authStore.apiKey` and `authStore.isHydrated` are set synchronously at module load; the router gates every protected route on `isHydrated === true` so the first query cannot fire with an empty header.
- `ADMIN_API_KEY` is compared via `hmac.compare_digest`; direct `==` is never used (avoids a timing side channel on the key).
- The SPA mount is registered AFTER every API, health, docs, redoc, and openapi route; it never shadows a backend route or returns HTML to a JSON client (gated on `Accept: text/html`).
- The `x-api-key` and `authorization` request headers are on the structlog redaction deny list; neither can leak into application logs.
- OpenAPI types in `frontend/src/api/schema.d.ts` are checked in; drift between frontend and backend is caught at CI time by comparing a fresh `pnpm gen:api` against the committed file.

**Security model**:
- The admin UI is operator only. No multi tenant isolation; a holder of `ADMIN_API_KEY` has full access to every endpoint except `/health/*` and `/api/v1/_meta/error-codes` (which stay public).
- API key auth is a stub for Feature 26 and is explicitly not suitable for production exposure. Documented in Consequences and the README.
- `ADMIN_API_KEY` is a required startup setting; a pydantic validator rejects empty or whitespace only values and requires length `>= 16`, and the key is compared with `hmac.compare_digest` (constant time, no timing side channel). The backend refuses to start without it. This matches spec 0007's "validate at startup, fail fast" rule.
- The key is stored in `localStorage` (not `sessionStorage`), so a cross site scripting bug would expose it; the admin UI runs no third party scripts, which keeps the surface small. Flagged in Consequences.
- CSRF: header only auth is CSRF safe (a custom header triggers a browser preflight that cross site forms cannot replay). No cookie is used for auth; the invariant above enforces this. If Feature 26 adds a cookie, it must add explicit CSRF protection.
- Log redaction: structlog's request logging middleware (spec 0007) adds `x-api-key` and `authorization` to its header deny list before serialization. Playwright trace recording also redacts the key via a `page.route` interceptor so CI artifacts never carry it.
- Compliance scope: none for this feature. No PII crosses the shell; the catalog data it reads is operational metadata.

**Configuration required**:

Backend:
- `ADMIN_API_KEY`: the single key the admin UI must present. Required at startup; the app refuses to boot without it. A pydantic validator rejects empty / whitespace only values and requires `len(key.strip()) >= 16`.
- `SERVE_ADMIN_UI`: boolean, default `false` in dev (so uvicorn stays a pure JSON API and the Vite dev server owns the browser), `true` in container builds; gates the SPA router mount.
- `ADMIN_UI_DIST_PATH`: path to the built SPA, default `frontend/dist`. Used by the SPA router only when `SERVE_ADMIN_UI` is `true`.

Frontend:
- `.env.local.example`: documents `VITE_DEV_API_KEY_HINT` (plain prose, not loaded as a real key).

**Critical test scenarios** (each maps to an acceptance criterion in `## Requirements`):
- Happy path: open `/`, redirected to `/login`, submit the dev key, land on `/websites`, see the list, toggle theme to dark, sign out, redirected to `/login`. Verifies **AC-2**, **AC-3**, **AC-5**, **AC-6**, **AC-14** (Playwright smoke; **AC-12**).
- Auth failure: the stored key is wrong (manually tampered in `localStorage`); loading `/websites` triggers a 401 which clears `localStorage` and redirects to `/login` exactly once. Verifies **AC-4**.
- Problem Details rendering: Vitest test mocking an `apiFetch` response with `application/problem+json` body asserts the `ApiError` fields are parsed and the toast includes `correlation_id`. Verifies **AC-8**.
- Backend dependency: pytest test POSTs to `/api/v1/websites` with no header → 401 with `code: admin_ui.unauthenticated`; with the right header → 200. Verifies **AC-9**.
- Static serve: pytest test with `SERVE_ADMIN_UI=true` and a stub `dist/index.html` asserts GET `/websites` returns the SPA HTML and GET `/api/v1/websites` still returns JSON. Verifies **AC-10**.
- Empty state: Websites endpoint returns `[]`; the UI renders the empty state card and no table rows. Component test (Vitest + Testing Library). Verifies **AC-6**.

## Build plan

Skateboard order: thinnest shippable whole first (one route, auth, one real list), then widen. Six build milestones; each ends on a shippable state so a reviewer can pull and run.

1. **Backend auth stub, config, log redaction** (satisfies **AC-9**, **AC-18** backend half): add `settings.ADMIN_API_KEY` (pydantic validator: strip, reject empty, require length `>= 16`), `settings.SERVE_ADMIN_UI` (default `false`), and `settings.ADMIN_UI_DIST_PATH` (default `frontend/dist`), register the `admin_ui.unauthenticated` error code and the `AdminUIUnauthenticated(PlatformError)` class in `src/app/core/errors/`, write the `require_api_key` dependency in `src/app/core/auth/api_key.py` (uses `hmac.compare_digest`, raises `AdminUIUnauthenticated` on fail), wire it into the `/api/v1` router group except `/api/v1/_meta/error-codes`, extend the startup assertion in `src/app/core/startup_state.py` so `ADMIN_API_KEY` is required at startup, add `x-api-key` and `authorization` to the structlog request logging middleware header deny list.
2. **Frontend scaffold and bootstrap docs** (satisfies **AC-1**, **AC-11**, **AC-13**, **AC-15**, **AC-17**): `pnpm init` under `frontend/`, add Vite + React 19 + TypeScript 7 strict + Biome 2 + Husky + lint staged, write the Vite proxy config covering `/api`, `/health`, `/docs`, `/redoc`, `/openapi.json`, scaffold `.nvmrc` (`22`) and `packageManager` field pinned exactly to `pnpm@10.13.0`, add `pnpm lint` / `typecheck` / `test` / `e2e` / `build` / `gen:api` scripts, add `.env.local.example`, install Tailwind 4 (CSS first config) and run `shadcn init` with the Zinc neutral palette, add the README "first time setup" section documenting `corepack enable && corepack prepare pnpm@10.13.0 --activate`.
3. **API client, Problem Details, auth shell** (satisfies **AC-2**, **AC-3**, **AC-4**, **AC-8**, **AC-16**, **AC-19**): generate `frontend/src/api/schema.d.ts` via `pnpm gen:api`, write the shared `apiFetch` wrapper around `openapi-fetch` (injects `X-API-Key`, parses `application/problem+json` into `ApiError`, maps `errors[].loc` to RHF `setError` when a form context is passed, routes unmapped errors to toast, triggers the gated single shot 401 redirect only when `authStore.isSignedIn` was `true`), add the `authStore` (Zustand, synchronous hydration from `localStorage` at module load, `isHydrated` flag, `signIn()` resets the redirecting flag, `router.subscribe('onLoad')` also resets it), build `/login` with React Hook Form + Zod (probe `GET /api/v1/websites?limit=1` before storing the key; on 401 show inline "Key rejected"), wire TanStack Router with a protected `beforeLoad` that gates on `isHydrated === true` and redirects to `/login` with the current path as `redirect` (whitelisted via `^/[a-zA-Z0-9/_-]*$`, fallback `/websites`).
4. **Layout, theme, routing shell** (satisfies **AC-5**, **AC-14**): build the `AppShell` (sidebar + header), add shadcn Button / Card / Table / Sonner / DropdownMenu / Separator primitives, add the `themeStore` and `ThemeProvider` with light/dark/system support, add the sign out action.
5. **Real screens plus placeholders** (satisfies **AC-6**, **AC-7**): wire `/websites` and `/targets` with TanStack Query loaders against the existing endpoints (list columns typed from the generated schema, no hand mirrored field names, empty state card for no rows), add the static `/workflows` and `/executions` placeholder routes, add the top level route error boundary that renders `ApiError.code` / `.title` / `.detail` / `.correlation_id` plus Retry.
6. **Tests, pre commit, production serve** (satisfies **AC-10**, **AC-11**, **AC-12**, **AC-13**, **AC-18** frontend half): add Vitest + Testing Library config and the component tests above, add the Playwright smoke test with a `page.route` key redaction interceptor so trace artifacts never carry the key, add the Husky `pre commit` hook (lint staged + `biome check --fix`), add the FastAPI SPA router (registered AFTER every API/health/docs/redoc/openapi route, 404s for reserved prefixes, serves `index.html` only on `Accept: text/html`, dedicated `/assets/` `StaticFiles` mount) behind `SERVE_ADMIN_UI`, update `README.md`; `AGENTS.md` pointer updates are left to `/sync`.

## Consequences

**Positive**:
- One repo, one PR per cross cutting change. Backend contract changes travel with their UI consumer.
- Full type safety end to end. `openapi-typescript` catches a wrong field name at build time, before a request flies.
- No CORS to configure, in development or production. Same origin everywhere.
- shadcn's copy in model means Feature 10's workflow configuration editor and Feature 11's execution browser can tune primitives in place without library forks.
- A single `apiFetch` wrapper is the only path to the backend, so Problem Details parsing, correlation id surfacing, and auth injection all live in one place.
- Feature 26 later swaps the auth mechanism (session cookie, OAuth, whatever) without touching the shell's `authStore` boundary.

**Negative / tradeoffs**:
- Adds a Node toolchain to a Python only project. Contributors now need Node LTS 22 and Corepack (`corepack enable` ships with Node). First time setup is a one liner, documented in the README.
- API key in `localStorage` is a known XSS exposure. Acceptable because the admin UI runs no third party scripts and this is a stub for Feature 26; must be documented in the README and must not survive to production exposure. Header redaction (log deny list) and Playwright trace redaction partially contain the blast radius.
- Two build steps (uv for backend, pnpm for frontend) and two lint tools (ruff, Biome). Mirrored discipline, double the setup.
- Dark mode on day one costs some upfront work on CSS variables, but is cheaper than a sweep later across Feature 10/11.
- TanStack Router is less common than React Router; the extra Agent Skill partially offsets the learning curve but recruiting a React dev familiar with it is harder.
- `openapi-typescript` generation runs against a live backend (`localhost:8000/openapi.json`), which means a developer must boot uvicorn before regenerating types. Flagged for a potential offline script in Follow up.

**Neutral**:
- Three new backend settings (`ADMIN_API_KEY`, `SERVE_ADMIN_UI`, `ADMIN_UI_DIST_PATH`), one new error code (`admin_ui.unauthenticated`), one new startup assertion.
- `frontend/dist/` is a build artifact, gitignored. `frontend/src/api/schema.d.ts` is generated but checked in (so diffs are reviewable and CI can detect drift).
- Feature 28 (container image and CI) will later add `pnpm install && pnpm build` to the Docker multi stage image and the pipeline; nothing in this spec writes CI config.

## Follow-up

- [ ] Install the picked community skills (the registry CLI was not reachable at spec authoring time): `shadcn-ui/ui` (shadcn skill), `deckardger/tanstack-agent-skills` (`tanstack-query-best-practices`, `tanstack-start-best-practices`), `pproenca/dot-skills` (`react-hook-form`), `haydenbleasel/ultracite` (Biome config), `antfu/skills` (`vitest`), `anthropics/skills` (`webapp-testing`). Suggested command per repo: `npx -y skills add <owner>/<repo> -y`. Verify the registry hits before installing; the discovery subagent could not reach WebSearch during spec authoring and the hits may need manual confirmation.
- [ ] After skills are installed, add a nested `frontend/AGENTS.md` enumerating the above skills and the frontend stack conventions (`/audit` or `/sync` owns this write; `/architect` does not touch `AGENTS.md`).
- [ ] Add a `pnpm gen:api:offline` script that reads a committed snapshot of `openapi.json` so types can be regenerated without booting uvicorn.
- [ ] Feature 26 (authN / authZ and API keys) must replace the `require_api_key` stub without changing the UI's `authStore` boundary; call this out when designing Feature 26.
- [ ] Feature 28 (container image and CI pipeline) must add a Node stage that runs `pnpm install && pnpm build` and copies `frontend/dist/` into the final image, plus `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm e2e` to CI.
- [ ] Consider adding a `pnpm` catalog or dependency pinning tool later if Feature 28 needs reproducible frontend builds in CI; out of scope for this spec.
- [ ] The declined skills (`pproenca/dot-skills@zod`, `antfu/skills@pnpm`) belong in `AGENTS.md` under a `## Declined` note so later `/architect` / `/audit` runs do not re offer them.
