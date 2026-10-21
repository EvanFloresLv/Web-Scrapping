# Scraping Platform Admin UI

React 19 single page app (Vite 7 + TypeScript + TanStack Router/Query +
Tailwind 4 + shadcn/ui + Biome 2). Spec: [docs/specs/0008-admin-ui-foundation](../docs/specs/0008-admin-ui-foundation/index.md).

## First time setup

```bash
# 1. Node 22 LTS (nvm, mise, or system). The .nvmrc pins the major.
nvm use

# 2. Activate the exact pnpm version pinned in `packageManager`.
corepack enable
corepack prepare pnpm@10.13.0 --activate

# 3. Install dependencies.
cd frontend
pnpm install

# 4. Boot uvicorn in another terminal (same repo root). The Vite proxy
#    (see vite.config.ts) forwards /api, /health, /docs, /redoc, /openapi.json
#    to http://localhost:8000 with no CORS.
#    Backend .env MUST have ADMIN_API_KEY set to a value you will paste
#    into the login form; the backend refuses to boot without one.
cd ..
docker compose up -d postgres
uv run uvicorn app.main:app --reload

# 5. Boot the frontend.
cd frontend
pnpm dev    # http://localhost:5173
```

If `corepack` is not on your PATH (unusual; it ships with Node), install it
with `npm install -g corepack`.

## Scripts

| Script | What it does |
|---|---|
| `pnpm dev` | Vite dev server on `http://localhost:5173` with the backend proxy. |
| `pnpm build` | Type check (`tsc --noEmit`) then build to `dist/`. |
| `pnpm preview` | Serve the built `dist/` locally. |
| `pnpm lint` | Biome check with warnings as errors. |
| `pnpm lint:fix` | Biome check + auto fix. |
| `pnpm typecheck` | `tsc --noEmit`. |
| `pnpm test` | Vitest run. |
| `pnpm test:ui` | Vitest watch. |
| `pnpm e2e` | Playwright smoke suite. |
| `pnpm gen:api` | Regenerate `src/api/schema.d.ts` from `http://localhost:8000/api/v1/openapi.json`. |

## Security note

`ADMIN_API_KEY` is a stub for Feature 26. The admin UI stores the key in
`localStorage`, which means a cross site scripting bug would leak it. The
app ships no third party scripts to keep that surface small. The backend
also redacts `x-api-key` and `authorization` from request logs, and the
Playwright trace recorder redacts the key via a `page.route` interceptor.
Do not expose this stub to the public internet.
