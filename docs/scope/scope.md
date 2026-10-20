# Scope: Agentic AI Web Scraping Platform

A backend platform that registers websites and target URLs, runs reusable scraping workflows over HTTP, prefers deterministic extraction, and uses LLMs only to discover, repair, or validate configurations. Serves product teams that need structured catalog data from many sites, with provenance and traceable executions.

**Build approach:** Skateboard (ship the thinnest usable whole first, then grow it slice by slice).
**Workflow:** Beta (after `/develop` → `/check verify`, then `/test`). The project default level of rigor. `/architect` is the recommended first stop for a feature with a real decision, but skippable when you already know the build. Any feature can carry its own tag (e.g. `· GA`) to do more or less.

_These are recommendations to keep your build orderly, not requirements. Skip anything that does not fit: if you already know how to build a feature, use `/develop` and skip `/architect`. You decide when a feature is `done`._

_Heads up: there is no root `AGENTS.md` yet. Run `/audit` as the first step so later skills have real project context (it is Feature 2 below)._

## At a glance

| # | Feature | Phase | Status |
|---|---------|-------|--------|
| A | Legacy ADK/Gemini agent | Reference | existing |
| 1 | Stack & architecture | Foundation | done |
| 2 | Coding standards & tooling | Foundation | in-progress |
| 3 | Data model (MVP entities) | Foundation | done |
| 4 | Website & target registration | Slice 1 (MVP) | in-progress (tested, awaiting done) |
| 5 | Workflow configuration & versioning | Slice 1 (MVP) | in-progress |
| 6 | Deterministic HTML extraction (static) | Slice 1 (MVP) | in-progress |
| 7 | Workflow execution endpoint (sync) | Slice 1 (MVP) | planned |
| 8 | Structured errors & health endpoints | Slice 1 (MVP) | planned |
| 9 | Admin UI foundation | Slice 2 (Admin UI) | planned |
| 10 | Workflow configuration screens | Slice 2 (Admin UI) | planned |
| 11 | Execution browser | Slice 2 (Admin UI) | planned |
| 12 | Structured logging & correlation | Slice 3 (Observability) | planned |
| 13 | Metrics & operational dashboard | Slice 3 (Observability) | planned |
| 14 | Langfuse agent tracing scaffold | Slice 3 (Observability) | planned |
| 15 | LLM provider abstraction & prompt versioning | Slice 4 (Agentic AI) | planned |
| 16 | Agent-assisted workflow discovery | Slice 4 (Agentic AI) | planned |
| 17 | Deterministic-first execution with agent fallback | Slice 4 (Agentic AI) | planned |
| 18 | Product entity & provenance | Slice 5 (Catalog) | planned |
| 19 | Deterministic product deduplication | Slice 5 (Catalog) | planned |
| 20 | Retries, timeouts, circuit breakers | Slice 6 (Reliability) | planned |
| 21 | Rate limiting & responsible crawling | Slice 6 (Reliability) | planned |
| 22 | Browser automation adapter (JS-rendered) | Slice 7 (Rendering) | planned |
| 23 | Job queue & worker pool | Slice 8 (Async) | planned |
| 24 | Embeddings & semantic search | Slice 9 (Semantic) | planned |
| 25 | Feedback capture & evaluation harness | Slice 10 (Feedback) | planned |
| 26 | AuthN / AuthZ & API keys | Slice 11 (Security) | planned |
| 27 | SSRF controls & agent guardrails | Slice 11 (Security) | planned |
| 28 | Container image & CI pipeline | Slice 12 (Delivery) | planned |
| 29 | Cloud deployment (GCP) | Deferred | planned |

## Brownfield enrollment

### A. Legacy ADK/Gemini agent · existing
Kept for reference. The current `web_scraping/` package is a Google ADK agent orchestrating sub-agents for product verification. It will be superseded by the new FastAPI platform; useful as a source of prompt and evaluation know-how. code in `web_scraping/`

## Foundations

### 1. Stack & architecture · done
Decide the backend stack, database, migrations, project layout, and local dev shape, then scaffold a runnable project so every later slice builds on real structure.
**Done when:** the stack is recorded in a spec, the empty scaffold boots locally, and `GET /health/live` returns 200.
- [x] Decide the stack (spec): `/architect stack & architecture`
- [x] Scaffold from the decision: `/develop stack & architecture`
- [x] Verify it: `/check verify stack & architecture`
- [x] Test it: `/test stack & architecture`
Spec [0001](../specs/0001-stack-and-architecture/index.md) · code in `./src/app/`

### 2. Coding standards & tooling
Capture conventions and tooling into root `AGENTS.md`, then install lint, format, type-check, and pre-commit enforcement so later work stays consistent.
**Done when:** root `AGENTS.md` exists and reflects the real stack, and lint/format/type-check run clean on the scaffold.
- [x] Capture conventions + tooling choices: `/audit`
- [x] Install the tooling: `/develop coding standards & tooling`
- [x] Verify it: `/check verify coding standards & tooling`
- [x] Test it: `/test coding standards & tooling` _(skipped: no testable surface; the gates themselves are the test)_
code in `./` (root `AGENTS.md`, `pyproject.toml`, `.pre-commit-config.yaml`)

### 3. Data model (MVP entities)
Core entities every MVP feature depends on: Website, TargetURL (both specified by spec 0002), ScrapingWorkflow, WorkflowVersion, Execution, ExecutionResult. ExtractionRule is embedded as JSONB inside `workflow_versions.config` rather than its own table. Covers migration strategy (one per slice), audit fields, lifecycle enums, FK policies, and concurrency rules.
**Done when:** the MVP data model is pinned in spec 0003; ORM models and the `WorkflowConfig` Pydantic validator exist in `src/app/domains/`; the error-code registry module is in place; later slice migrations (features 5, 7) conform to the spec exactly.
- [x] Design it (spec): `/architect data model (MVP entities)`
- [ ] Build it: `/develop data model (MVP entities)`
  - [x] ORM models for workflows and executions in `src/app/domains/{workflows,executions}/models.py` plus shared enums (satisfies AC-2, AC-3, AC-4, AC-6, AC-7, AC-9, AC-10, AC-12, AC-14)
  - [x] `WorkflowConfig` Pydantic validator with `extra='allow'` in `src/app/domains/workflows/config.py` (satisfies AC-5, AC-13)
  - [x] Repository protocol stubs with `with_deleted=False` seams in `src/app/domains/{workflows,executions}/repository.py` (satisfies AC-2, AC-6, AC-20)
  - [x] Error-code registry module in `src/app/core/errors/execution_codes.py` (satisfies AC-17)
- [x] Verify it: `/check verify data model (MVP entities)`
- [x] Test it: `/test data model (MVP entities)`
Spec [0003](../specs/0003-data-model-mvp/index.md)

## Slice 1: Deterministic workflow MVP

### 4. Website & target registration
Register allowed websites and target URLs through the API, with validation and canonicalization, so workflows can bind to known targets.
**Done when:** `POST /websites` and `POST /targets` create and list records, duplicate URLs are canonicalized, and invalid inputs return structured 4xx errors.
- [x] Design it (spec): `/architect website & target registration`
- [x] Build it: `/develop website & target registration`
  - [x] Migration for `websites` + `target_urls` with partial unique indexes
  - [x] Domain model (ORM + `CanonicalHost` / `CanonicalURL` value objects + repository)
  - [x] Service layer (duplicate, host-match, parent-state, immutable-field invariants)
  - [x] Router (POST + GET list + GET single for websites and targets)
  - [x] PATCH + DELETE (soft-delete with cascade) + Problem Details error mapping
- [x] Verify it: `/check verify website & target registration`
- [x] Test it: `/test website & target registration`
Spec [0002](../specs/0002-website-target-registration/index.md) · code in `src/app/domains/websites/` + `src/app/api/v1/websites.py` + `migrations/versions/202610191000_add_websites_and_target_urls.py`

### 5. Workflow configuration & versioning
Define a reusable scraping workflow with typed parameters, extraction rules (container + fields + selectors + transforms), and immutable versions.
**Done when:** workflows are created, versioned, retrieved, and validated against a schema; versions are immutable after creation.
- [x] Design it (spec): `/architect workflow configuration & versioning`
- [x] Build it: `/develop workflow configuration & versioning`
  - [x] Alembic migration + repository groundwork + `WorkflowErrorCode` registry extension (satisfies AC-14, AC-15, AC-16)
  - [x] Workflow CRUD service + router (POST + GET list + GET single + PATCH + soft DELETE with in-flight gate) (satisfies AC-1, AC-2, AC-3, AC-4, AC-5)
  - [x] Version create and edit (POST draft + list + get + PATCH draft + hard DELETE draft, with coherence validation) (satisfies AC-6, AC-7, AC-8, AC-9, AC-10, AC-17)
  - [x] Publish and archive lifecycle actions (atomic publish transaction + archive refusal on current) (satisfies AC-11, AC-12)
  - [x] Problem Details error mapping across every endpoint (satisfies AC-13)
- [x] Verify it: `/check verify workflow configuration & versioning`
- [x] Test it: `/test workflow configuration & versioning`
Spec [0004](../specs/0004-workflow-configuration-versioning/index.md) · code in `src/app/domains/workflows/` + `src/app/api/v1/workflows.py` + `migrations/versions/202610200900_add_workflows_and_versions.py`
**Considerations (test gaps worth revisiting):**
- AC-6 one-shot retry on `(workflow_id, version_number)` races: reachable only by simulating a lost race (monkeypatch `next_version_number`); add a dedicated service-level test if feature 7 or 10 exposes concurrent draft creation in practice.
- AC-11 concurrent-publish contention: needs two sessions and real `SELECT ... FOR UPDATE` ordering; the suite covers the superseded-draft path sequentially (`publish same draft twice → 409 version_conflict`). Add a true two-session test when a load scenario appears.
- AC-14 Alembic round-trip (`upgrade → downgrade -1 → upgrade`): a migration-level test, not in the API suite; defer to `/check verify` or a focused migration test alongside feature 7's migration.
- AC-16 / AC-17 at the repository layer: exercised through HTTP paths; a pure-repo unit set would duplicate the API suite for this slice.
- Repository short-circuit on `has_in_flight_executions`: `to_regclass` branch is unreachable now that `executions` ships with this test setup; keep for the pre-feature-7 world and drop once feature 7 is in.

### 6. Deterministic HTML extraction (static)
Fetch static HTML, apply configured selectors and transforms, and emit structured JSON matching the workflow's output schema. No LLM in the path.
**Done when:** given a fixture page and a workflow, the extractor produces the expected structured output; missing fields, bad selectors, and empty results return structured errors.
- [x] Design it (spec): `/architect deterministic HTML extraction (static)`
- [x] Build it: `/develop deterministic HTML extraction (static)`
  - [x] Preconditions: extend `WorkflowConfig` with `fields[*].required`, add `FetchErrorCode` + `ExtractionErrorCode` enums, add `jsonschema` and `respx` deps, add six `EXTRACTION_HTTP_*` settings (satisfies AC-4, AC-9, AC-10, AC-13, AC-14)
  - [x] Fetch and parse core: scaffold `src/app/domains/extraction/` + `import-linter` contract, implement `HttpFetcher` (shared lifespan `httpx.AsyncClient`, HTTP/2, timeouts, redirect cap, streamed body cap, content type gate, charset resolution), implement `HtmlParser` over selectolax (satisfies AC-1, AC-4, AC-5, AC-6)
  - [x] Extraction pipeline: `Extractor` with container iteration and per field selector + transform pipeline, full transform set, type coercion for `integer | decimal | boolean | url`, `OutputSchemaValidator` using `jsonschema` draft 2020-12 (satisfies AC-7, AC-8, AC-9, AC-10, AC-11)
  - [x] Service composition and preview endpoint: `ExtractionService.run(...)` gating on `pagination`, structlog events plus metrics wrapper stub, `POST /api/v1/workflows/{workflow_id}/versions/{id}/preview` with target URL resolution against `target_urls` and Problem Details error mapping (satisfies AC-1, AC-2, AC-3, AC-12, AC-15, AC-16, AC-17, AC-18)
  - [x] Fixture suite and golden file tests under `tests/fixtures/extraction/` covering every transform, every error code, and the preview endpoint's status axes (satisfies AC-19)
- [ ] Verify it: `/check verify deterministic HTML extraction (static)`
- [ ] Test it: `/test deterministic HTML extraction (static)`
Spec [0005](../specs/0005-deterministic-html-extraction/index.md) · code in `src/app/domains/extraction/` + `src/app/api/v1/extraction.py` + `src/app/core/observability/metrics.py`
**Considerations (follow-ups left for later work):**
- Publish-time validation of `fields[*].type` and `fields[*].transforms` against the extraction registry (spec 0005 step 1 / AC-9 / AC-10 follow-up): run-time is the backstop today; wire the registry into feature 5's `_coerce_config` once a workflow needs it.
- `output_schema` double-duty: feature 5's coherence check wants every field name as a top-level key, but `jsonschema` metaschema rejects reserved keywords (`title`, `type`, ...) as top-level non-string values. Workflows avoid those field names today; capture a cleaner shape (e.g. nested `properties`) when the collision bites.
- Pre-existing `tests/test_workflows_repository.py` references `WorkflowVersionRepository` (consolidated into `WorkflowRepository` in feature 5). The file fails to import; rewrite or delete alongside feature 7's work.

### 7. Workflow execution endpoint (sync) · needs a decision
`POST /workflows/{id}/execute` runs a workflow against a target URL, persists an Execution record, and returns the structured result synchronously.
**Done when:** an end-to-end request returns `completed` with data and metadata (duration, items extracted) for a fixture, and failures are persisted with status `failed` and an error reason.
- [ ] Design it (spec): `/architect workflow execution endpoint (sync)`

### 8. Structured errors & health endpoints
A single error contract across the API, plus `GET /health/live` and `GET /health/ready` for operators.
**Done when:** every error path returns the shared error schema (code, message, details, correlation id); readiness checks DB connectivity.
- [ ] Design it (spec): `/architect structured errors & health endpoints`

## Slice 2: Admin UI

### 9. Admin UI foundation · needs a decision
Pick the UI stack and ship a minimal shell (navigation, auth-aware layout, design primitives) that later screens plug into.
**Done when:** the UI boots locally, authenticates against the API (even with a dev key), and renders empty-state screens for workflows and executions.
- [ ] Design it (spec): `/architect admin UI foundation`

### 10. Workflow configuration screens · needs a decision
UI to register websites and targets, create and edit workflow versions, and preview extraction output on a sample URL.
**Done when:** a user can create a workflow end-to-end from the UI and run a preview that returns the extracted sample.
- [ ] Design it (spec): `/architect workflow configuration screens`

### 11. Execution browser · needs a decision
Browse executions with filters (workflow, status, time range), open a run to see its input, output, errors, and timings.
**Done when:** the list paginates, filters work, and a run detail view renders JSON output, error reasons, and timing.
- [ ] Design it (spec): `/architect execution browser`

## Slice 3: Observability

### 12. Structured logging & correlation · needs a decision
JSON logs across the API, workers, and extractors with a correlation id propagated per request and per execution.
**Done when:** every API request and execution emits start/complete/error log events sharing a correlation id; log levels are configurable per module.
- [ ] Design it (spec): `/architect structured logging & correlation`

### 13. Metrics & operational dashboard · needs a decision
Expose core metrics (request rate, latency percentiles, error rate, extraction success rate, per-domain throttling) and render an operational view in the admin UI.
**Done when:** metrics are collected via a documented endpoint, the dashboard shows p50/p95 latency and error rate over the last hour, and the panel is linkable from a run detail.
- [ ] Design it (spec): `/architect metrics & operational dashboard`

### 14. Langfuse agent tracing scaffold · needs a decision
Wire a Langfuse (or equivalent) client behind an interface so later agent calls automatically record traces, prompt versions, token usage, and cost estimates.
**Done when:** a dummy agent call produces a Langfuse trace with model, prompt id, tokens, and latency; the client is a no-op when creds are absent.
- [ ] Design it (spec): `/architect langfuse agent tracing scaffold`

## Slice 4: Agentic AI integration

### 15. LLM provider abstraction & prompt versioning · needs a decision
A provider-agnostic LLM client, structured output / tool-calling support, and versioned prompt templates stored in the DB.
**Done when:** a prompt template is created, versioned, and invoked via the client; swapping provider only requires config.
- [ ] Design it (spec): `/architect LLM provider abstraction & prompt versioning`

### 16. Agent-assisted workflow discovery · needs a decision
Given a sanitized HTML sample and target intent, an agent proposes a candidate workflow configuration (selectors, fields, transforms) that is validated against fixtures before persistence.
**Done when:** the agent produces a valid candidate workflow for a fixture, validation gates persistence, and rejected candidates surface a clear reason.
- [ ] Design it (spec): `/architect agent-assisted workflow discovery`

### 17. Deterministic-first execution with agent fallback · needs a decision
On execution, use the verified deterministic workflow when available; otherwise run agent-assisted discovery, validate, approve, and persist a new version. Never call an LLM when a verified config exists.
**Done when:** executions log which path ran (deterministic vs agent-assisted), and repeat runs on the same target reuse the verified config without an LLM call.
- [ ] Design it (spec): `/architect deterministic-first execution with agent fallback`

## Slice 5: Product catalog

### 18. Product entity & provenance · needs a decision
Persist normalized product records (name, brand, description, price, currency, identifiers) with full provenance back to the execution and raw values.
**Done when:** executions can emit products linked to a source URL, and a product record carries raw and normalized values plus the execution id that produced it.
- [ ] Design it (spec): `/architect product entity & provenance`

### 19. Deterministic product deduplication · needs a decision
Identity strategy using source identifiers, canonical URLs, brand + model, and normalized names; distinguish exact duplicates from variants.
**Done when:** feeding duplicates of a product produces one canonical record with multiple sources; a variant stays distinct.
- [ ] Design it (spec): `/architect deterministic product deduplication`

## Slice 6: Reliability

### 20. Retries, timeouts, circuit breakers · needs a decision
Classify retryable vs non-retryable failures; add bounded retries with jitter, explicit timeouts, and circuit breakers per external dependency.
**Done when:** simulated 429/5xx responses retry with backoff, non-retryable errors fail fast, and a tripped breaker stops hammering the upstream.
- [ ] Design it (spec): `/architect retries, timeouts, circuit breakers`

### 21. Rate limiting & responsible crawling · needs a decision
Per-domain concurrency and request budgets, polite request pacing, and (where applicable) respect for robots directives.
**Done when:** concurrent executions against the same domain stay under a configurable budget and the system refuses disallowed scopes.
- [ ] Design it (spec): `/architect rate limiting & responsible crawling`

## Slice 7: JS-rendered pages

### 22. Browser automation adapter · needs a decision
A browser rendering adapter behind the same extraction interface so workflows can run against JS-rendered pages when needed.
**Done when:** a workflow flagged `render: browser` extracts correctly from a dynamic fixture; static workflows still use the HTTP path.
- [ ] Design it (spec): `/architect browser automation adapter`

## Slice 8: Asynchronous processing

### 23. Job queue & worker pool · needs a decision
Introduce async execution: `POST execute` enqueues a job (202 Accepted), workers run it, results are polled via `GET /executions/{id}`. Covers idempotency, visibility, poison messages, and cancellation.
**Done when:** long-running workflows no longer block the API, workers process from the queue, and cancellation + retry behavior is testable.
- [ ] Design it (spec): `/architect job queue & worker pool`

## Slice 9: Semantic search

### 24. Embeddings & semantic search · needs a decision
Embeddings for products and workflow configurations with model + version tracked; retrieval combines deterministic filters with vector similarity and re-ranking.
**Done when:** semantically similar products are returned with scores, embeddings record model/version, and reuse of a verified config is suggested for a similar target.
- [ ] Design it (spec): `/architect embeddings & semantic search`

## Slice 10: Feedback & evaluation

### 25. Feedback capture & evaluation harness · needs a decision
Capture explicit and implicit feedback (ratings, corrections, re-extractions) and run versioned evaluation fixtures to compare prompt and model versions over time.
**Done when:** a feedback event persists against an execution, and the eval harness scores a prompt version against a fixed dataset.
- [ ] Design it (spec): `/architect feedback capture & evaluation harness`

## Slice 11: Security hardening · GA

### 26. AuthN / AuthZ & API keys · needs a decision · GA
Real authentication, authorization, per-key rate limits, and secrets management. A minimal API-key gate from the Admin UI onward is folded into Slice 2; this feature promotes it to production grade.
**Done when:** API keys are scoped and revocable, admin actions are authorized, and secrets never land in logs.
- [ ] Design it (spec): `/architect authN / authZ & API keys`

### 27. SSRF controls & agent guardrails · needs a decision · GA
Block internal IPs and metadata endpoints at fetch time, validate URL schemes, enforce agent tool permissions, token budgets, and prompt-injection defenses.
**Done when:** scraping an internal address is refused; agent prompts carry structured output enforcement and bounded iterations; injected instructions in page content do not change agent behavior in tests.
- [ ] Design it (spec): `/architect SSRF controls & agent guardrails`

## Slice 12: Delivery

### 28. Container image & CI pipeline · needs a decision
Reproducible multi-stage container image, non-root runtime, health checks, and a CI pipeline running lint, type-check, tests, and dependency scanning.
**Done when:** CI runs green on push, builds a container, and the container boots locally with the same behavior as the dev scaffold.
- [ ] Design it (spec): `/architect container image & CI pipeline`

## Deferred
Out of scope for the current build pass, kept so the plan stays honest.
- **29. Cloud deployment (GCP)**: Cloud Run + Cloud SQL + queues + secret manager + Terraform. Only after local is validated. · needs a decision
- **Multi-tenant organizations**: data isolation per org, roles, invitations · needs a decision
- **Multi-region deployment**: active-active or active-passive · needs a decision
- **Advanced recommendation / matching**: cross-site product graph beyond deterministic + similarity · needs a decision
- **Public developer API & docs portal**: external developer surface · needs a decision

## Legend

**The decision box.** Every feature carries exactly one, the sub-task whose label ends with `(spec)`. Its wording varies (`Design it (spec)` normally, `Decide the stack (spec)` on Stack & architecture), so skills locate it by that `(spec)` suffix, never by an exact label. Every other box is an execution box and `/architect` never ticks one.

**Feature lifecycle**: the scope updates as a feature moves; each row is what it shows and who sets it:

| State | Set by | The feature shows |
|---|---|---|
| `planned` · needs a decision | `/scope` | one box: `Design it (spec): /architect <feature>` |
| `in-progress` (designed) | **`/architect` at spec capture** | `Design it` ticked; spec linked; `Build it: /develop <feature>` + **2 to 5 milestones**; the tier's closing boxes (`Verify it` for Beta, `Test it` for Beta); any surfaced follow-up enrolled |
| `in-progress` (building) | `/develop` | milestone sub-boxes tick one by one; code pointer filled |
| `in-progress` (verified) | `/check verify` | `Build it` + milestones ticked; `Verify it` ticked |
| `done` | **you, when you decide it is** (any skill sets it when you say so); `/sync` reconciles | boxes you ran ticked, skipped ones marked skipped; `/test` is the suggested point to call it done at Beta; `/sync` captures conventions |

- **Next step** = the first unticked box (always a command or a tracked milestone).
- **needs a decision** = run `/architect` first; otherwise straight to `/develop` (or `/audit` for standards & tooling). The tag drops once the spec is captured.
- **Atomic build tasks live in the spec's `## Build plan`, not here**: the scope carries only the milestone rollup.
- **Status** `planned` → `in-progress` → `done`, plus `existing` (pre-workflow) and `dropped` (de-scoped, kept for history).
- **Workflow tier tag** beside a heading (e.g. `· GA`) sets that one feature's rigor above or below the project default (Beta); no tag inherits the default.
- **Workflow** (header line) is the project default, what runs after `/develop`: **Beta** = `/check verify` then `/test`. A feature tagged `· GA` adds a fresh-model `/check review` and `/document`.
- **Pointer line** (`spec <n> · code in <path>`): the spec link added by `/architect`, the code path by `/develop`.
