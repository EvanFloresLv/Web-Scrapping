# 0001. Stack and architecture — rationale

Reasoning, options, and context for the decision in [`index.md`](index.md). Not read during a build; `/develop` skips this file.

## Context

> ⚠️ Premise note: the legacy `web_scraping/` package is a Google ADK agent (an LLM native product research tool) that is strongly coupled to Gemini and does not share the data model or deterministic path this platform needs. You picked `Replace it (greenfield feel)` in `/scope`. This spec treats the platform as greenfield; the legacy agent stays only as a reference for prompt and evaluation know how until the new platform catches up on that surface, then it can be removed. State this as a Follow-up so the removal is tracked, not forgotten.

The platform must execute a registered scraping workflow over HTTP, return structured JSON, persist what ran and what came out, and grow into agent assisted configuration, product catalog, async execution, semantic search, and feedback over the slices in `docs/scope/scope.md`. The MVP is deterministic (no LLM in the extraction path); AI is additive, behind an interface, and billed for separately.

Forces that shape the choice:
- You chose local first (Docker Compose, uv), Beta workflow depth (verify + test after `/develop`), and a modular monolith. You explicitly asked for AI only when needed and deterministic by default.
- There is no git repo, no root `AGENTS.md`, and no `docs/specs/` yet; the next scope row (Feature 2) runs `/audit` to capture conventions. That is the moment to codify the tooling choices made here.
- The data model will grow: workflows and versions, executions and results, products with provenance, embeddings. A single database engine that handles JSONB (JSON stored natively) and vector search later (pgvector, a PostgreSQL extension for vectors) is a strong constraint.
- Scraping is network bound and spiky. The framework must be async native so one process can hold many open connections cheaply.
- The team is small (one engineer today, with AI assistance). Operational complexity costs more than framework elegance; boring and widely known beats new and clever.
- Later slices (observability, async workers, agent integration, security hardening) must not require a rewrite. The shape here should absorb them, not fight them.

Not deciding this now means every later feature spec restarts the stack conversation.

## Options considered

### Option 1: Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 async · Alembic · PostgreSQL 16 · uv · structlog · pytest + testcontainers · Docker Compose for data stores · modular monolith (recommended)

The widely used async Python backend stack of 2026. Every piece is proven, documented, and has a large community. Postgres handles relational data today, JSONB for workflow configs, and pgvector when semantic search lands. The modular monolith keeps the deployable count at one until evidence forces a split.

**Pros**:
- Boring, well understood pieces at every layer; faster to learn and operate at 2am.
- Native async end to end (FastAPI, httpx, SQLAlchemy 2); fits scraping's network bound profile.
- Single database engine covers relational, JSONB, full text search, and later vectors.
- `uv` keeps installs and lockfile fast, and replaces several older tools (pip + pip-tools + venv + often Poetry) with one.
- Matches the master prompt and the legacy codebase's language; no ecosystem jump.

**Cons**:
- Python itself is single threaded per process; CPU bound stages (parsing many large pages at once) need multiple workers or process pools later.
- SQLAlchemy 2 async has a learning curve for engineers used to the older synchronous API.
- `uv` is newer than Poetry; the Python packaging landscape has churned several times in the last few years and could churn again.

### Option 2: Python 3.12 · Litestar · msgspec · SQLAlchemy 2 async · Alembic · PostgreSQL · uv · structlog · pytest · Docker Compose · modular monolith

Same shape, swap FastAPI for Litestar (another modern async Python framework with built in dependency injection and plugin layers) and Pydantic for msgspec (a very fast serialization library).

**Pros**:
- Cleaner built in dependency injection and controller model than FastAPI.
- msgspec is extremely fast for serialization.

**Cons**:
- Smaller community than FastAPI; fewer tutorials, fewer third party integrations, more time spent reading source.
- Mixing msgspec with Pydantic in the same project (likely when LLM clients and pydantic-ai arrive) creates two schema systems.
- Loses the alignment with the master prompt and the Python docs the team is likely to read first.

### Option 3: Python 3.12 · Django 5 (async views) · DRF · Django ORM · Postgres · modular monolith

Use Django's batteries included platform (ORM, admin, migrations, auth, middleware) with async views.

**Pros**:
- Admin out of the box (useful for Slice 2's workflow config UI shortcut).
- Mature migrations and ORM; least surprise for a traditional web team.
- Lots of production heritage.

**Cons**:
- Async in Django is still a bolt on; mixing sync ORM calls with async views causes subtle event loop blocking that is hard to debug.
- Django opinions (apps layout, settings module, management commands) fight the domain oriented module layout you want.
- Admin is a UI shortcut, not a product grade admin; you still build the real Admin UI in Slice 2.

### Option 4: Node.js 22 · Fastify · Prisma · PostgreSQL · pnpm · modular monolith

Walk away from Python and build the platform on Node.

**Pros**:
- Single runtime that is natively async and genuinely good at network concurrency.
- First class TypeScript types across API, DB, and client.

**Cons**:
- The LLM, scraping, and data science ecosystems you will reach for (pydantic-ai, Langfuse SDKs, BeautifulSoup / selectolax / Playwright Python, numpy, embeddings) are richer in Python; you would spend time bridging.
- Losing the legacy agent as reference and the legacy team's muscle memory.
- No alignment with the master prompt's named stack.

## Rationale

Three forces from Context point here. First, the deterministic by default execution model needs real relational storage (workflow versions, executions, results, products, provenance) and JSONB for workflow configs; a mature RDBMS does both without a second data store, and the later vector slice reuses the same engine (pgvector). Second, scraping is network bound and spiky; FastAPI plus httpx plus SQLAlchemy 2 async let one process hold many open sockets cheaply, which matters as soon as a workflow fans out across a page's product cards. Third, the team is small and the Beta workflow depth means every feature pays for verify and test; boring, widely documented pieces reduce the "what does this error mean" tax at every step.

On the specific calls inside the stack: `selectolax` beats BeautifulSoup for the extractor because the extractor runs on every request and C backed selectors are an order of magnitude faster at scale; the master prompt's richer parsing can be reached for later via `lxml` behind the same interface. `uv` is picked over Poetry because the install and lockfile speed show up on every CI run and every onboarding; the risk (newer tool) is bounded by its drop in compatibility with standard `pyproject.toml`. `structlog` beats loguru because structured JSON logs with per request and per execution context are needed from Slice 3, and structlog's contextvars integration slots cleanly into the async model. `testcontainers` beats a shared dev Postgres because workflow versioning and migrations will touch schema often; integration tests that lie because they ran against stale state cost more than the extra seconds of container startup. The decision to keep the app running locally with uv (not inside Compose) is deliberate: hot reload and debugger attach are worth more in daily dev than one command onboarding, and Compose still handles Postgres so parity does not drift.

RFC 7807 Problem Details (a standard JSON shape for API errors) is picked for errors because every slice adds endpoints and keeping one shared shape across them is cheaper than aligning handwritten shapes later. FastAPI's native `Depends` is enough DI for a modular monolith; a formal DI container is overkill until the module count grows past comfort. Cursor pagination on executions and products is chosen now because adding it later is the kind of migration nobody wants to run on live data.

The one place where the engineer's apparent preference needs calling out: the master prompt lists Clean Architecture, Hexagonal Architecture, and DDD among the principles. This spec picks a modular monolith with domain oriented modules, not hexagonal ports and adapters up front. Reason: ports and adapters are useful when adapters swap often (storage, provider, transport); here we expect PostgreSQL to stay, FastAPI to stay, and the LLM provider layer to be the one real adapter boundary (Slice 4 already decides it). Pulling ports around every domain today buys abstraction we are not spending; let the module boundaries carry structure, and introduce an adapter interface at a layer only when a second real implementation shows up.

## References

**Project sources**:
- `docs/scope/scope.md`: Feature 1 (Stack and architecture) is the parent scope row for this spec; Features 4 through 8 depend on these picks.
- The master prompt in the `/scope` run (the "MASTER PROMPT, Agentic AI Web Scraping Platform" argument) names FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL and Docker Compose as the baseline, which this spec adopts.
- The legacy `web_scraping/` package (Google ADK agent) in the repository root: used as evidence of the current Python language and parsing/LLM habits.

**Practices and standards**:
- Monolith first, extract services only when a measured bottleneck or team ownership boundary forces it.
- A relational database is the right default for ~95% of products; reach for a specialized store only when the pattern genuinely demands one.
- ORM for CRUD, raw SQL for reporting and complex joins.
- RFC 7807 Problem Details for a standardized API error contract.
- Boring, widely known technology beats new and clever unless a specific constraint forces otherwise.
- Local first before cloud: validate the system end to end on a laptop before paying for managed services.
