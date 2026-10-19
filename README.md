# Agentic AI Web Scraping Platform

A backend platform that registers websites and target URLs, runs reusable scraping workflows over HTTP, prefers deterministic extraction, and uses LLMs only to help discover, repair, or validate configurations (never on the hot path when a verified configuration exists).

- Scope lives in `docs/scope/scope.md` (one row per feature, ordered by phase).
- Decisions live in `docs/specs/` (`0001-stack-and-architecture.md` is the foundation; every later spec builds on top).
- This README documents the scaffold shipped by Scope Feature 1. It is intentionally short; `AGENTS.md` (added by Scope Feature 2 via `/audit`) will carry the conventions.

## Status

- Scaffold: FastAPI app with health endpoints, correlation IDs, Problem Details errors, structured logging, pydantic-settings config, async SQLAlchemy skeleton, Alembic set up (no migrations yet), Docker Compose for Postgres.
- Next: `/audit` captures conventions into root `AGENTS.md`, then Feature 3 adds the first data model and migration.

## Requirements

- Python 3.12.x (pinned in `pyproject.toml`)
- [uv](https://docs.astral.sh/uv/) 0.9+
- Docker and Docker Compose (for the local Postgres)

## Install

```bash
uv sync --extra dev
```

Create your local env file:

```bash
cp .env.example .env
```

## Run

Start Postgres in the background:

```bash
docker compose up -d postgres
```

Run the app on the host (hot reload for dev):

```bash
uv run uvicorn app.main:app --reload
```

Then:

```bash
curl -s http://127.0.0.1:8000/api/v1/health/live
# {"status":"ok"}

curl -i http://127.0.0.1:8000/api/v1/health/ready
# 200 with {"status":"ok","database":true} once Postgres is up
```

OpenAPI docs: `http://127.0.0.1:8000/api/v1/docs` (dev only).

## Test

```bash
uv run pytest
```

The scaffold ships five smoke tests covering the health endpoints, correlation ID echo, Problem Details on unknown routes, and the 1 MB request-size cap. Feature 3 introduces a session-scoped `testcontainers` Postgres fixture when the first models land.

## Lint, format, type check

```bash
uv run ruff check src tests
uv run ruff format src tests
uv run mypy src
```

Install pre-commit once:

```bash
uv run pre-commit install
```

## Project layout

```
src/app/
  main.py               # app factory, middleware wiring, lifespan
  core/
    config.py           # pydantic-settings (env-driven)
    logging.py          # structlog setup, JSON in prod / pretty in dev
    database.py         # async engine, request-scoped session, shared Metadata + naming_convention
    errors.py           # Problem Details error contract + handlers
  api/v1/
    router.py           # aggregates v1 routes under /api/v1
    health.py           # /health/live, /health/ready
  domains/              # per-domain modules land here as Scope Slices 1-10 ship
  infrastructure/       # cache, queues, llm, observability land here as their slices ship

migrations/             # Alembic (env.py async, YYYYMMDDHHMM slug template)
tests/                  # pytest-asyncio + httpx AsyncClient
docker-compose.yml      # Postgres 16 only; app runs on host
docs/
  scope/scope.md        # ordered feature plan
  specs/0001-*.md       # foundation stack spec
legacy/                 # Prior Google ADK/Gemini agent, kept for reference
```

## Conventions pinned by spec 0001

See `docs/specs/0001-stack-and-architecture.md` for the full list. Highlights every later feature spec can rely on:

- UUIDv7 primary keys everywhere.
- `TIMESTAMPTZ` columns, UTC-only, timezone-aware datetimes end to end.
- Soft delete on `websites` and `workflows`; executions and results immutable.
- Request-scoped async SQLAlchemy session via `Depends(get_session)`, `expire_on_commit=False`, explicit `selectinload` for related rows.
- snake_case JSON, ISO-8601 UTC datetimes with `Z`, `Decimal` for money.
- RFC 7807 Problem Details error contract (`application/problem+json`, `correlation_id` extension).
- `X-Request-ID` correlation header, bound to structlog contextvars.
- `/api/v1/...` route prefix; cursor pagination for executions and products, offset for small admin lists.
- `import-linter` contract: a `domains/x` module may import only `core` and its own package.

## Legacy agent

The previous Google ADK + Gemini product-verification agent lives under `legacy/`. It is kept for prompt and evaluation know-how until Scope Slice 4 (Agentic AI integration) lands equivalent functionality; it is not installed by this project's dependencies.
