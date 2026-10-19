# 0001. Stack and architecture for the Agentic AI Web Scraping Platform

**Date**: 2026-10-16
**Status**: Accepted

## Summary

You are building a Python backend platform (a web server plus workers over time) that registers websites, runs reusable scraping workflows, and uses large language models (LLMs: AI that generates text, selectors, or code on request) only to help configure or repair extraction, never on the hot path when a known good configuration exists. The stack is Python 3.12 with FastAPI (a modern Python web framework), Pydantic v2 (data validation), SQLAlchemy 2 with Alembic (database access and schema migrations) on PostgreSQL 16, packaged with uv (a fast Python package manager), run locally with Docker Compose, and shaped as a modular monolith (one deployable app with clear internal module boundaries you can split later only when evidence demands it). This is a foundation spec; every later feature spec builds on top of these picks.

## Decision

**Chosen option**: Option 1: Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 async · Alembic · PostgreSQL 16 · uv · structlog · pytest + testcontainers · Docker Compose for data stores · modular monolith.

This is the stack you build on, and the shape (modular monolith with domain oriented modules under `src/app/domains/`) you keep until a measured scaling need forces a split.

**Implementation skills**: `fastapi` (`fastapi/fastapi`, `.claude/skills/fastapi/`) · `sqlalchemy-alembic-expert-best-practices-code-review` (`wispbit-ai/skills`, `.claude/skills/sqlalchemy-alembic-expert-best-practices-code-review/`) · `modern-python` (`trailofbits/skills`, `.claude/skills/modern-python/`) · `uv-package-manager` (`wshobson/agents`, `.claude/skills/uv-package-manager/`) · `python-testing-patterns` (`wshobson/agents`, `.claude/skills/python-testing-patterns/`) · `multi-stage-dockerfile` (`github/awesome-copilot`, `.claude/skills/multi-stage-dockerfile/`)

## Rationale

Reasoning, options considered, and context: see [`rationale.md`](rationale.md).

## Proposed stack

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.12+ | Matches legacy agent, strongest scraping and LLM ecosystem, aligns with master prompt. |
| Runtime | CPython | Default; PyPy ruled out until a measured CPU bottleneck justifies it. |
| Architecture shape | Modular monolith with domain oriented modules | One deployable, clear internal boundaries, extract services only when evidence demands. |
| Project layout | `src/app/{api/v1,core,domains/{websites,workflows,executions,extraction,products,agents},infrastructure/{db,http,llm,cache,queues}}/main.py` plus `tests/` at repo root | Module boundaries mirror the architecture decision; `src/` layout avoids accidental imports from the repo root. |
| Web framework | FastAPI | Native Pydantic v2, auto OpenAPI, large community, async first. |
| ASGI server | uvicorn (dev and prod) | Standard FastAPI pairing; keep one tool until perf evidence demands otherwise. |
| Validation / schemas | Pydantic v2 (and pydantic-settings for config) | De facto in the FastAPI world; same models serve API and workflow configs. |
| Primary database | PostgreSQL 16 | ACID, JSONB for workflow configs, full text search, pgvector for Slice 9, master prompt alignment. |
| ORM | SQLAlchemy 2.x (async) | Mature async, survives raw SQL for complex queries, matches the master prompt. |
| Migrations | Alembic | Canonical SQLAlchemy pairing. |
| HTTP client | httpx | Async native, HTTP/2, same client in app and tests. |
| HTML parser | selectolax (default) | C backed CSS selectors, fast at scale; lxml can be added behind the same interface later when a workflow needs XPath. |
| Packaging / env | uv | Fast installs, lockfile, workspace support, standard `pyproject.toml`. |
| Config | pydantic-settings reading `.env` locally, env vars in deployed envs | Typed, validates on startup, one way to read config everywhere. |
| Logging | structlog, JSON in deployed envs, pretty in dev | Structured JSON logs with per request and per execution context from day one. |
| Correlation IDs | `asgi-correlation-id` middleware bound to structlog contextvars | Propagates `X-Request-ID` and binds it into every log line. |
| Testing | pytest + pytest-asyncio + httpx `AsyncClient` + `testcontainers` for Postgres | Covers unit, integration, API contract, e2e; real Postgres in integration avoids SQLite drift. |
| Dependency injection | FastAPI `Depends` + a small factories module per domain | Enough for a modular monolith; no DI container until the module count demands it. |
| API error contract | RFC 7807 Problem Details, extended with `code` and `correlation_id` | Standardized across every endpoint from the start. |
| API versioning | `/api/v1/...` prefix on every route | One version today, prefix leaves room for v2 without rewriting routers. |
| Pagination | Cursor based for executions and products; offset for small admin lists (websites, workflows) | Cursor avoids drift on hot lists; offset is simpler for tiny lookups. |
| Lint / format / type | ruff (lint + format) + mypy in strict mode | ruff for both linting and formatting (one tool); mypy strict project wide. |
| Pre commit | pre-commit framework running ruff, mypy, and hygiene hooks | Enforced on every commit. |
| Local dev containers | Docker Compose for Postgres (and later Redis); app runs on the host with uv | Fast reload loop, reproducible data stores. |
| Container image (prod) | Multi stage Dockerfile, non root user, `uvicorn` entrypoint | Slim image, least privilege. |
| CI | Hooked into Slice 12 feature spec; expect lint + mypy + pytest + build on push | Not part of this spec; recorded here so later slices do not debate it. |
| LLM provider abstraction | A thin interface in `src/app/infrastructure/llm/`; the concrete provider is decided by Slice 4 (Feature 15 spec) | Keep this foundation provider agnostic; no model name is baked in here. |
| Observability (metrics + agent traces) | Decided in Slice 3 (Features 12 to 14); scaffolding reserves `src/app/infrastructure/observability/` | Keep this spec about the foundation; do not pre bake tool names. |

Each row is a hard constraint for later specs: a feature spec may add behavior inside a layer but may not swap a layer without superseding this spec.

## Conventions pinned here

These are small, cross cutting decisions every later spec would otherwise have to re litigate. Pin them now; a later spec may override by superseding this one.

**Python and packaging**
- Python version: `3.12.x` only (not 3.13 yet). `uv.lock` is authoritative; `pyproject.toml` carries minor version pins.
- Host Python version matches the prod Dockerfile's Python; `uv` manages both so parity is automatic.

**Database identity, time, and lifecycle**
- Primary keys: UUIDv7 everywhere (sortable, cursor friendly, globally unique).
- Timestamps: `TIMESTAMPTZ` columns, UTC only, timezone aware datetimes end to end, server side `now()` defaults.
- Every table carries `created_at` and `updated_at`; `updated_at` is maintained by a trigger or SQLAlchemy event.
- Soft delete (`deleted_at TIMESTAMPTZ NULL`) on `websites` and `workflows`; executions and execution results are immutable (hard delete only by retention job, decided in a later spec).

**SQLAlchemy and Alembic**
- Session scoping: one request scoped `AsyncSession` provided via a FastAPI `Depends`; `expire_on_commit=False`; no session shared across tasks; eager loads use explicit `selectinload` to avoid lazy load I/O on an unavailable session.
- Naming convention: a standard `MetaData(naming_convention=...)` dict so Alembic autogenerate produces stable constraint and index names (prevents noisy diffs on every migration).
- Table names: plural snake_case (`workflows`, `execution_results`).
- Migrations: file names `YYYYMMDDHHMM_slug.py`; every autogenerated migration is reviewed by hand before commit; no `upgrade()` that silently drops data.
- mypy strict applies project wide; one `strict = true` in `pyproject.toml`.

**API conventions**
- JSON field casing: snake_case in both request and response bodies.
- Datetimes serialize as ISO 8601 with trailing `Z` (UTC); UUIDs serialize as strings; money uses `Decimal` end to end (never `float`); JSONB config fields reject floats where the value is money.
- API error contract: RFC 7807 Problem Details, `Content-Type: application/problem+json`, `type: "about:blank"` by default, a per domain stable `code` enum, `correlation_id` as an extension field.
- Correlation ID header: `X-Request-ID`, generated when absent, echoed in responses, bound to structlog contextvars, surfaced in Problem Details as `correlation_id`.
- Pagination: opaque base64 keyset cursor (encodes the ordering columns of the last returned row); default page size 50, max 200; offset pagination only for small admin lists (websites, workflows).
- Request body cap: 1 MB JSON (middleware rejects larger with `413`); configurable per route if a scraping-heavy slice needs more.
- httpx default timeouts: `connect=5s, read=25s, total=30s`; per workflow override allowed via the extractor interface.
- OpenAPI: title and version from app config; one tag per domain module; docs enabled in dev; prod docs exposure is deferred to the Slice 11 security spec.

**Testing**
- `pytest-asyncio` mode: `auto` (set in `pyproject.toml`).
- Testcontainers Postgres runs session scoped (one container reused across the test session) so Beta tier verify + test loops stay fast; each test gets its own transaction and rolls back.
- httpx `AsyncClient` drives the API in process using FastAPI's `app` as transport.

**Module boundaries**
- `src/app/main.py` holds the FastAPI app factory and router wiring; no business logic.
- A `domains/x` module may import only `core` and its own package; it must not import another `domains/y` directly. Cross domain calls go through a service in `core` or through an event / signal (added when needed). Enforced by `import-linter` with a contract committed in `pyproject.toml`.
- Reserved folders `infrastructure/{cache,queues,observability}` and `domains/agents` stay empty until their slice; no placeholder modules, no `TODO.md` stubs.

**Extractor seam (reserved for Feature 6 spec)**
- The deterministic extractor's internal interface (how `selectolax` and later `lxml` or a browser renderer plug in behind one call) is reserved for Feature 6's spec; this spec only mandates the seam exists.

## Consequences

**Positive**:
- Every later feature spec starts with the stack settled; conversations shrink to "what does this feature need."
- One database engine covers relational, JSON, full text, and future vector workloads.
- Fast local dev loop (app on host, Postgres in Compose) means verify and test cost stays low per feature.
- Boring choices mean lots of docs, lots of Stack Overflow, lots of pattern precedent; the LLM working alongside the engineer has strong priors.

**Negative / tradeoffs**:
- Python's GIL means CPU heavy stages (large page parsing, dense embedding math) need extra processes or thread pools, not just more async; that is a Slice 7 and Slice 9 concern this spec does not resolve.
- SQLAlchemy 2 async has sharp edges (session scoping, implicit I/O in attribute access); junior contributors will trip over them until the patterns are documented in `AGENTS.md`.
- `uv` is newer than Poetry; if it ever stalls, migrating back is possible but annoying.
- The modular monolith makes it easy to accidentally couple modules at import time; the discipline is in code review, not the framework.

**Neutral**:
- `pydantic-ai` or another typed LLM client will slot into the LLM interface in Slice 4; this spec does not pick it.
- The eventual production host (Cloud Run or similar) is a Slice 12 decision; this spec intentionally does not pick it, so local first stays honest.
- A browser automation adapter (Slice 7) will add Playwright or a headless browser; the interface for extraction is designed in Feature 6's spec to accept it without reshaping the engine.
- The Conventions pinned here section carries decisions a cross check surfaced before build (session scoping, UUIDv7, TIMESTAMPTZ UTC, snake_case JSON, cursor shape, request limits, module boundary rule, test setup); each closes a decision later specs would otherwise have to make, so Feature 2 (`/audit`) and Feature 3 (data model) can lean on them directly.

## Follow-up

- [ ] Capture the stack and conventions in root `AGENTS.md` via `/audit` (Scope Feature 2 is the entry point).
- [ ] Verify every installed agent skill with `npx skills list`; retry any missing (install batch finished in the background during `/architect`).
- [ ] Note the Postgres MCP server (gives live read access to the dev DB) and the Docker MCP server (gives live container state) for you to connect in your MCP client config when convenient; neither is required for the build.
- [ ] Decide the fate of the legacy `web_scraping/` package: already relocated to `legacy/`; delete it once Slice 4 lands and the new agent surface replaces it.
- [ ] A fresh current landscape check (web verified) was unavailable at write time (the researcher subagent failed on model access). If you want, rerun it before Scope Feature 2 to double check the packaging and framework picks are still current; the recommendations stand without it.
- [ ] Startup logging bug (`structlog.stdlib.add_logger_name` requires a stdlib logger factory) was caught at scaffold time and fixed by dropping that processor in favour of `structlog.processors.add_log_level`; captured here so the next session knows why the processor chain looks lean.
