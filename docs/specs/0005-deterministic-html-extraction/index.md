# 0005. Deterministic HTML extraction (static)

**Date**: 2026-10-19
**Status**: In Progress

## Summary

This spec is the build spec for Slice 1's extractor. It adds a service module and a preview endpoint that, given a published or draft workflow version and a registered target URL, fetches the page over HTTP, runs the configured CSS selectors and transforms with selectolax (a fast Lexbor backed HTML parser), validates each extracted item against the version's `output_schema` (treated as JSON Schema draft 2020-12), and returns the structured items or a stable error code. No LLM is in the path. Nothing is persisted; feature 7 is the endpoint that writes an `executions` row around the same service call.

## Requirements

**User stories**

- As a platform operator editing a workflow version, I want to run the extractor against a registered target URL and see the structured output without persisting anything, so that I can iterate on selectors before I publish.
- As a platform engineer building the executor (feature 7), I want one in process `ExtractionService.run(...)` that returns a structured result for both success and every failure mode, so that persisting the `executions` and `execution_results` rows is a thin wrapper around a single call.
- As a platform operator, I want a selector drift (the container matches zero elements, a required field matches zero elements, a type coercion fails, an item fails its `output_schema`) to end as a stable, non guessable error code, so that later features (the execution browser in feature 11 and the agent repair paths in features 15 to 17) can act on it.
- As a platform operator, I want fetch failures (timeout, non 2xx, body too large, wrong content type) separated from extraction failures by error prefix, so that I can tell at a glance whether the page or the selectors broke.

**Acceptance criteria** (the contract later skills check)

- **AC-1**: `src/app/domains/extraction/` ships `ExtractionService.run(workflow_version: WorkflowVersion, target_url: TargetUrl) -> ExtractionResult`. `ExtractionResult` is a value object `{status: 'completed'|'failed', items: list[dict] | None, items_count: int, duration_ms: int, error_code: str | None, error_message: str | None, error_details: list[dict] | None}`. The service does **no** DB write; it is called by this feature's preview endpoint and by feature 7's execution endpoint.
- **AC-2**: `POST /api/v1/workflows/{workflow_id}/versions/{id}/preview` with body `{target_url: str}` runs `ExtractionService.run(...)` and returns `200` with the `ExtractionResult` as JSON. The endpoint accepts any version `status` (`draft`, `published`, or `archived`); preview is a read only probe. `completed` executions carry `items`; `failed` executions carry `error_code` and `error_message` and `items=null, items_count=0`. A missing, malformed, or wrong type request body (Pydantic shape failure on `{target_url: str}`) returns `422 extraction.invalid_preview_body` (Problem Details shape per AC-16, with the Pydantic field path in `details`); never reuses feature 5's `workflow.validation_error`, which is scoped to `WorkflowConfig` validation.
- **AC-3**: The preview endpoint resolves `target_url` against `target_urls` using `(website_id = scraping_workflows.website_id, canonical_url = normalize(target_url))` filtered to live rows (`with_deleted=false`), reusing the `CanonicalURL` value object from spec [0002](../0002-website-target-registration/index.md). No match returns `404 extraction.target_not_registered` (RFC 7807, same shape as [0004](../0004-workflow-configuration-versioning/index.md) AC-13). A missing or soft deleted `workflow_id` or version returns `404 workflow_not_found` or `404 version_not_found` (reuses the codes from [0004](../0004-workflow-configuration-versioning/index.md) AC-15). A soft deleted workflow is not previewable (same posture as [0004](../0004-workflow-configuration-versioning/index.md) AC-5).
- **AC-4**: HTTP fetch runs through one shared `httpx.AsyncClient` stored on `app.state.http_client` via the lifespan context manager in `src/app/main.py`, injected into `HttpFetcher` through a `get_http_client()` FastAPI dependency in `src/app/domains/extraction/dependencies.py` (never a module level singleton, so tests can override the dependency), with HTTP/2 enabled, and the following limits enforced per call: `EXTRACTION_HTTP_CONNECT_TIMEOUT_S` (default 5), `EXTRACTION_HTTP_READ_TIMEOUT_S` (default 15), `EXTRACTION_HTTP_TOTAL_TIMEOUT_S` (default 20), `EXTRACTION_HTTP_MAX_BODY_BYTES` (default 10_000_000, enforced by streaming the response and aborting past the cap), `EXTRACTION_HTTP_MAX_REDIRECTS` (default 5), and a configurable `EXTRACTION_HTTP_USER_AGENT` (default `CatalogEnrichmentBot/0.1 (+https://example.com/bot)`). No retries, no backoff, no circuit breaker (feature 20 owns those; this feature fails fast). Fetch failures map to:
  - timeout at any phase → `fetch.timeout`
  - non 2xx status → `fetch.http_error` (status in details)
  - DNS or connection refused or TLS error → `fetch.connection_error`
  - redirect loop or more than max → `fetch.too_many_redirects`
  - streamed body past the cap → `fetch.body_too_large`
  - malformed or non http(s) URL after canonicalisation → `fetch.invalid_url`
- **AC-5**: The response `Content-Type` must be `text/html` or `application/xhtml+xml` (case insensitive, parameters ignored). Anything else returns `fetch.unsupported_content_type` with the received type in details. Decoding uses the `Content-Type` charset parameter when present; else `charset_normalizer` autodetect (already a transitive dep of httpx) on the first 10 KB; else UTF 8.
- **AC-6**: Selectors (`container_selector` and `fields[*].selector`) are CSS, parsed by selectolax. A selector that selectolax rejects as unparseable returns `extraction.selector_syntax_error` (the offending `fields[*].name` or the literal string `container_selector`, plus the parser message, in `error_details`). The same check is also added to `WorkflowConfig` service layer validation (feature 5) so a broken selector fails at publish time; the run time check is the backstop.
- **AC-7**: The extractor finds all nodes matching `container_selector` on the parsed document (top level, no scoping). Zero matches returns `failed` with `extraction.no_container_match`. One or more matches produces exactly one item per container node, in document order.
- **AC-8**: For each item and each `fields[*]` entry (in config order):
  1. Run the field's `selector` scoped to the container node; take the **first** matching element.
  2. Apply `transforms` in order. An `attr:<name>` transform picks that attribute off the current element in place of its text; every other transform operates on the running string. The first non `attr:` transform forces the value to the element's `text()` if it is still an element. **An element whose `text()` is the empty string is a legitimate match**; the extractor treats the field as extracted (value `""`), runs the transforms on `""`, and lets type coercion reject it if applicable (e.g. `to_decimal` on `""` → `extraction.transform_error`; `string` type on `""` → `completed` with empty string in the payload, subject to the `output_schema` gate). An empty string match is NOT treated as "field missing"; a `required=true` field whose selector matches an empty element does NOT raise `extraction.required_field_missing` (operators who want "empty is missing" can model that in `output_schema` via `minLength: 1` or wait for a future `allow_empty_field` flag spec).
  3. Coerce the result to the field's `type`.
  4. Zero matches on the field selector: if `required=true` (the default per AC-13), the whole execution ends `failed` with `extraction.required_field_missing` (field name in `error_details`); if `required=false`, the item's payload holds `null` for that field and the extractor continues.
  5. Transform failure (unknown transform name, regex compile error, `to_decimal` on a non numeric string, etc.) ends the execution `failed` with `extraction.transform_error` (field name, transform, reason in `error_details`).
  6. Type coercion failure ends the execution `failed` with `extraction.type_coercion_error` (field name, declared type, offending value in `error_details`).
- **AC-9**: The MVP transform set shipped by this feature:
  - **Text normalizers** (no args): `strip`, `collapse_whitespace`, `lower`, `upper`.
  - **Attribute pickers**: `attr:<name>` (e.g. `attr:href`, `attr:data-sku`); picks the attribute off the matched element instead of its text; must be the FIRST transform in the pipeline if used.
  - **Numeric and money parsers**: `to_int`, `to_decimal` (optional locale arg: `to_decimal:en` for `1,234.56` or `to_decimal:de` for `1.234,56`; default `en`); `strip_currency` (removes `$`, `€`, `£`, `¥`, `¢` and any surrounding whitespace).
  - **Regex**: `regex_extract:<pattern>` (returns group 1 if the pattern has a group, else group 0; no match raises `extraction.transform_error`), `regex_replace:<pattern>:<replacement>` (`:` inside the pattern or replacement must be escaped as `\\:`).

  Unknown transform names → `extraction.transform_error` at run time. The registry of allowed transforms lives in `src/app/domains/extraction/transforms.py` and is also used by feature 5's `WorkflowConfig` validator (added as a Follow up to [0004](../0004-workflow-configuration-versioning/index.md), see Follow up) so a bad name fails at publish time.
- **AC-10**: Allowed values for `fields[*].type`: `string | integer | decimal | boolean | url`. Coercion rules:
  - `string`: identity.
  - `integer`: `int(value)` after stripping surrounding whitespace; failure → `extraction.type_coercion_error`.
  - `decimal`: `Decimal(value)` per the project money rule from `AGENTS.md`; `float` is never used.
  - `boolean`: case insensitive match against `{true, 1, yes, on}` → `true` and `{false, 0, no, off}` → `false`; anything else → `extraction.type_coercion_error`.
  - `url`: parsed as an absolute URL; a relative URL is resolved against the page's `<base href>` if present, else against the fetched URL (post redirect).

  `WorkflowConfig` validation (feature 5) rejects any other `type` string at publish time; the run time path treats an unknown type as `extraction.type_coercion_error` for defence in depth.
- **AC-11**: After every item is extracted, each item's payload is validated against `WorkflowConfig.output_schema` as a JSON Schema draft 2020-12 document using the `jsonschema` library (added as a runtime dep). The FIRST item that fails validation ends the execution `failed` with `extraction.output_schema_mismatch` (`item_index`, the JSON pointer path of the first error, and the validator message in `error_details`); **subsequent items are NOT validated in this feature** (fail fast). A future spec may add a `validate_all` mode when feature 15 or 17 needs it for repair; captured in Follow up. An empty `output_schema` (`{}`) validates every item (JSON Schema semantics: an empty schema accepts anything); operators who want "no validation" set `{}` deliberately. The validator is instantiated once per execution so the schema compile cost is paid once.
- **AC-12**: If a workflow version carries a non null `WorkflowConfig.pagination` document, `ExtractionService.run(...)` returns `failed` with `extraction.pagination_unsupported` before fetching. Pagination will be added as its own slice.
- **AC-13**: `WorkflowConfig.fields` entries carry an optional `required: bool = true` (per [0003](../0003-data-model-mvp/index.md) AC-5 "additive only"); the extractor applies `true` by default to any field without the key, so historical `workflow_versions.config` documents keep passing. The Pydantic `Field` model is extended; no DB migration is needed because `config` is JSONB with `extra='allow'`.
- **AC-14**: The error registry `src/app/core/errors/execution_codes.py` is extended with two StrEnums shipped by this feature:
  - `FetchErrorCode`: `fetch.timeout`, `fetch.http_error`, `fetch.connection_error`, `fetch.too_many_redirects`, `fetch.body_too_large`, `fetch.unsupported_content_type`, `fetch.invalid_url`.
  - `ExtractionErrorCode`: `extraction.no_container_match`, `extraction.required_field_missing`, `extraction.type_coercion_error`, `extraction.transform_error`, `extraction.selector_syntax_error`, `extraction.output_schema_mismatch`, `extraction.pagination_unsupported`, `extraction.target_not_registered`, `extraction.invalid_preview_body`.

  Feature 7 reuses `ExtractionResult.error_code` as the value of `executions.error_code` (text column per [0003](../0003-data-model-mvp/index.md) AC-6 and AC-17).
- **AC-15**: Observability (structlog, correlation id already bound by the middleware pinned in [0001](../0001-stack-and-architecture/index.md)):
  - Events: `extraction.fetch_started`, `extraction.fetch_completed`, `extraction.parse_completed`, `extraction.item_extracted` (level `debug`, one per item), `extraction.completed`, `extraction.failed`.
  - Every event carries: `correlation_id`, `workflow_version_id`, `workflow_id`, `target_url`, `items_count` (when known), `duration_ms` (when known), `error_code` (when failed).
  - A thin metrics wrapper `src/app/core/observability/metrics.py` exposes `extraction_duration_seconds` (histogram, label `phase=fetch|parse|validate|total`) and `extraction_items_total` (counter, label `status=completed|failed`). The wrapper is a stub that writes to a Python logger today; feature 13 swaps the backend behind the same interface.
- **AC-16**: Every error response from the preview endpoint is `application/problem+json` (RFC 7807) with the shape pinned by [0004](../0004-workflow-configuration-versioning/index.md) AC-13: `{type: 'about:blank', title, status, detail, code, correlation_id, details?}`. A `200` success body is JSON (not Problem Details), using the `ExtractionResult` shape from AC-1.
- **AC-17**: No SSRF (server side request forgery, when a server fetches an internal URL on an attacker's behalf) guard ships in this feature; feature 27 owns that. The host allow list is enforced indirectly by the `(website_id, canonical_url)` lookup in AC-3, so the extractor can only fetch URLs that match a registered target under a registered website. A Follow up records this.
- **AC-18**: No new DB tables; this feature only adds the optional `required` field to `WorkflowConfig.fields` (AC-13). Feature 7 is the first feature that writes `executions` and `execution_results` rows.
- **AC-19**: Testing: HTML fixtures live under `tests/fixtures/extraction/<site_slug>/<case>.html`; HTTP calls are stubbed with `respx` (added as a dev dep) so no test hits the network. Each `completed` fixture has a `<case>.expected.json` sibling for golden file comparison. **Golden file comparison strips the non deterministic fields from the actual result before diffing** (specifically `duration_ms` and any ISO 8601 timestamp key); only `status`, `items`, `items_count`, `error_code`, `error_message`, and `error_details` are compared. The suite includes one scenario per transform in AC-9, one scenario per error code in AC-14, and one end to end preview endpoint test per status axis (`completed`, `failed/fetch.*`, `failed/extraction.*`, `404/extraction.target_not_registered`, `422/extraction.invalid_preview_body`).

## Decision

**Chosen option**: Option 1: ship an in process `ExtractionService` reused by feature 7, plus a non persistent `POST .../preview` endpoint; CSS selectors via selectolax; one `httpx.AsyncClient` with hard timeouts and a streamed body cap; `jsonschema` for the `output_schema` gate; two new error prefix enums `fetch.*` and `extraction.*`; pagination deferred.

The feature is a service and a thin HTTP wrapper that both call the same code path, so feature 7 is a persistence shell around a solved problem. The surface is intentionally the thinnest useful whole (Skateboard): fetch, parse, extract, validate, return; retries, pagination, rate limiting, SSRF, and the real metrics backend are each their own slice later.

**Implementation skills**: `fastapi` (`fastapi/fastapi`, `.claude/skills/fastapi/`) · `sqlalchemy-alembic-expert-best-practices-code-review` (`wispbit-ai/skills`, `.claude/skills/sqlalchemy-alembic-expert-best-practices-code-review/`) · `python-testing-patterns` (`wshobson/agents`, `.claude/skills/python-testing-patterns/`) · `modern-python` (`trailofbits/skills`, `.claude/skills/modern-python/`) · `uv-package-manager` (`wshobson/agents`, `.claude/skills/uv-package-manager/`)

## Rationale

Reasoning and options considered: see [`rationale.md`](rationale.md).

## Feature design

**Data model sketch**

No new tables. One additive change to the Pydantic `WorkflowConfig` model from [0003](../0003-data-model-mvp/index.md) AC-5: each entry in `fields` gains an optional `required: bool = true`. The JSONB `workflow_versions.config` column stays schema free at the DB layer; historical rows without the key read as `required=true` by default. New dependencies: `jsonschema` (runtime) and `respx` (dev).

Reused value objects: `CanonicalURL` and `CanonicalHost` from [0002](../0002-website-target-registration/index.md) (URL normalisation and the target lookup); `WorkflowConfig` from [0004](../0004-workflow-configuration-versioning/index.md) (the input to the extractor).

**State transitions**

The extractor itself is stateless. `ExtractionResult` is a terminal value with two shapes:

```
run()  ──▶  ExtractionResult(status='completed', items=[...], items_count=N, duration_ms, error_*=None)
   │
   └──▶  ExtractionResult(status='failed', items=None, items_count=0, duration_ms, error_code=<fetch.* | extraction.*>, error_message, error_details)
```

Feature 7 maps `completed` to a `completed` row in `executions` plus N rows in `execution_results`, and `failed` to a `failed` row in `executions` with `error_code` and `error_message` persisted.

**API surface**

All endpoints under `/api/v1`. Auth is open on localhost (feature 26 adds the gate). Errors are `application/problem+json` per AC-16.

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/workflows/{workflow_id}/versions/{id}/preview` | POST | `target_url: str (req)` | `200 ExtractionResult` | open | `404 workflow_not_found`, `404 version_not_found`, `404 extraction.target_not_registered`, `422 extraction.invalid_preview_body` (malformed body) |

**Internal service surface** (not an HTTP endpoint, feature 7 reuses this)

- `extraction.service.ExtractionService.run(workflow_version: WorkflowVersion, target_url: TargetUrl) -> ExtractionResult`
- `extraction.fetcher.HttpFetcher.fetch(url: CanonicalURL) -> FetchResult` (streamed body with the cap enforced)
- `extraction.parser.HtmlParser.parse(body: bytes, charset: str | None) -> selectolax.lexbor.LexborHTMLParser`
- `extraction.extractor.Extractor.extract(parsed, config: WorkflowConfig) -> list[dict]`
- `extraction.validator.OutputSchemaValidator.validate(items: list[dict], schema: dict) -> None` (raises `OutputSchemaMismatchError` with item index + JSON pointer path)

**Response schema**

`ExtractionResult` (JSON wire shape, snake case per `AGENTS.md`):

```
{
  "status": "completed" | "failed",
  "items": [ { ...payload matching output_schema... }, ... ] | null,
  "items_count": 0..N,
  "duration_ms": int,
  "error_code": "fetch.*" | "extraction.*" | null,
  "error_message": str | null,
  "error_details": [ {"field": str, "message": str} ] | null
}
```

Problem Details body for 4xx errors matches [0004](../0004-workflow-configuration-versioning/index.md) AC-13 verbatim.

**Value sourcing**

| Action | Value produced / displayed | Source |
|---|---|---|
| POST `.../preview` | `workflow_id`, `id` (version id) | Path parameters, validated against live `scraping_workflows` and `workflow_versions` rows (per [0004](../0004-workflow-configuration-versioning/index.md) AC-3, AC-8); mismatched pair returns `404 version_not_found` |
| POST `.../preview` | `target_url` resolution to a `target_urls` row | `CanonicalURL.normalize(target_url)` + lookup by `(website_id = scraping_workflows.website_id, canonical_url = ..., with_deleted=false)`; no match → `404 extraction.target_not_registered` |
| POST `.../preview` | `WorkflowConfig` to run | Read from `workflow_versions.config` for the resolved `(workflow_id, id)` pair; validated at write time by feature 5, re validated by `WorkflowConfig.model_validate(...)` on read |
| POST `.../preview` | `correlation_id` on the response | `asgi-correlation-id` middleware contextvar per [0001](../0001-stack-and-architecture/index.md) |
| POST `.../preview` | `duration_ms` | Wall clock delta measured by `ExtractionService.run(...)` from the moment it begins to the moment the terminal result is built (uses `time.perf_counter_ns()` for monotonicity, rounded to ms) |
| Fetch | `User-Agent` header on the outgoing request | `EXTRACTION_HTTP_USER_AGENT` setting (default `CatalogEnrichmentBot/0.1 (+https://example.com/bot)`); never dynamic per request |
| Fetch | Charset for decoding | `Content-Type` charset parameter if present; else `charset_normalizer` autodetect on the first 10 KB; else UTF 8 |
| Fetch | Absolute `url` for `type=url` field coercion | The page's `<base href>` if present, else the final response URL after redirects (not the originally requested URL) |
| Extract | Which element inside a container a field reads | First match of `fields[*].selector` scoped to the container element, in document order |
| Extract | A field's value when its selector matches zero elements | `null` if `fields[*].required=false`; else execution ends `failed` with `extraction.required_field_missing` (field name in `error_details`) |
| Extract | A field's `required` default when the config key is absent | `true` (per AC-13); historical configs without the key stay strict |
| Validate | `output_schema` draft | JSON Schema draft 2020-12, explicitly set when instantiating the validator (not autodetected from `$schema`) |
| Error responses | `code` | `FetchErrorCode` or `ExtractionErrorCode` StrEnum from `src/app/core/errors/execution_codes.py` (per AC-14) |
| Error responses | `type` | `about:blank` default for MVP (per [0004](../0004-workflow-configuration-versioning/index.md) AC-13 Follow up) |

**Key invariants**

- `ExtractionService.run(...)` is side effect free: no DB write, no state outside the one process, no file write. Feature 7 provides the persistence layer around it.
- Every `failed` result carries an `error_code` from `FetchErrorCode | ExtractionErrorCode`; no `failed` result is ever untyped.
- The `httpx.AsyncClient` is created once at app startup and reused for every call; per request client creation is forbidden (connection pool is the whole point).
- Response body streaming aborts strictly past `EXTRACTION_HTTP_MAX_BODY_BYTES`; a non streamed read is forbidden.
- `WorkflowConfig.pagination` not null + extractor run → always `extraction.pagination_unsupported` at the service entry, never a partial fetch.

**Security model**

- No new authn or authz; inherits the open on localhost posture of the MVP (feature 26 adds the API key gate across every endpoint).
- SSRF (server side request forgery) controls are **not** added here (feature 27 owns them). The host allow list is enforced indirectly: the preview endpoint only fetches URLs that match a registered `(website_id, canonical_url)` pair, so an attacker with API access can only hit URLs the operator already registered. Compliance scope: none for this feature.
- The fetched HTML body is kept in memory for the duration of one extraction and then discarded; it is never written to disk, never logged, never returned to the caller.
- The outgoing `User-Agent` identifies the bot and points at a contact URL (configurable), so a target site owner can request blocking without reverse engineering the traffic.

**Configuration required**

- `EXTRACTION_HTTP_CONNECT_TIMEOUT_S`: TCP + TLS handshake timeout in seconds (default `5`).
- `EXTRACTION_HTTP_READ_TIMEOUT_S`: per socket read timeout in seconds (default `15`).
- `EXTRACTION_HTTP_TOTAL_TIMEOUT_S`: total time budget per fetch in seconds (default `20`).
- `EXTRACTION_HTTP_MAX_BODY_BYTES`: max response body in bytes, enforced by streaming abort (default `10_000_000`).
- `EXTRACTION_HTTP_MAX_REDIRECTS`: max HTTP redirects to follow before raising `fetch.too_many_redirects` (default `5`).
- `EXTRACTION_HTTP_USER_AGENT`: outgoing `User-Agent` header (default `CatalogEnrichmentBot/0.1 (+https://example.com/bot)`).

All six are read by pydantic-settings and validated at startup, failing fast if invalid, per `AGENTS.md`.

**Critical test scenarios** (each maps to an acceptance criterion)

- Happy path, static catalog fixture: a two item product listing is fetched, extracted, validated, and the preview returns `200 completed` with `items_count=2` and payloads matching the `output_schema`, verifies **AC-1, AC-2, AC-7, AC-8, AC-9, AC-10, AC-11, AC-19**.
- Happy path, preview against a draft version: a `draft` version returns `200` just like a `published` one, verifies **AC-2**.
- Failure, container selector returns zero: a page with no matching container returns `failed/extraction.no_container_match`, verifies **AC-7, AC-14**.
- Failure, required field missing: a container present but one `required=true` field selector returns zero returns `failed/extraction.required_field_missing` with the field name in details, verifies **AC-8, AC-13, AC-14**.
- Failure, type coercion: a `decimal` field selector returns `"not a number"` returns `failed/extraction.type_coercion_error`, verifies **AC-8, AC-10, AC-14**.
- Failure, output schema mismatch: an item violates the schema (e.g. missing required key, wrong type) returns `failed/extraction.output_schema_mismatch` with the JSON pointer path, verifies **AC-11, AC-14**.
- Failure, pagination configured: a version with `pagination` not null returns `failed/extraction.pagination_unsupported` without a fetch, verifies **AC-12, AC-14**.
- Failure, HTTP timeout: respx stubs a 25 second response, preview returns `failed/fetch.timeout` within the total budget, verifies **AC-4, AC-14**.
- Failure, non 2xx status: respx stubs a `503`, preview returns `failed/fetch.http_error` with `status=503` in details, verifies **AC-4, AC-14**.
- Failure, body too large: respx streams a response past the cap, preview returns `failed/fetch.body_too_large`, verifies **AC-4, AC-14**.
- Failure, wrong content type: respx returns `application/json`, preview returns `failed/fetch.unsupported_content_type` with the received type in details, verifies **AC-5, AC-14**.
- Failure, unregistered target: preview with a URL whose canonical form is not a registered `target_urls` row under the workflow's website returns `404 extraction.target_not_registered`, verifies **AC-3, AC-14**.
- Transform suite: one scenario per transform in AC-9 (`strip`, `collapse_whitespace`, `lower`, `upper`, `attr:href`, `to_int`, `to_decimal:en`, `to_decimal:de`, `strip_currency`, `regex_extract`, `regex_replace`) extracts the expected value, verifies **AC-9**.
- Observability: a `completed` run emits `extraction.fetch_started`, `extraction.fetch_completed`, `extraction.parse_completed`, `extraction.completed` with correlation id, and the metrics wrapper records one `extraction_duration_seconds` sample per phase, verifies **AC-15**.
- Error shape: every error response body is RFC 7807 shaped with `code`, `correlation_id`, and `details` when applicable, verifies **AC-16**.

## Build plan

Slices by Skateboard: the first task delivers the thinnest usable whole (fetch + extract + validate + return, no transforms, no preview endpoint). Each later task thickens one dimension.

1. **Extend `WorkflowConfig`** with `fields[*].required: bool = true` in `src/app/domains/workflows/config.py` and update the feature 5 service layer validator so unknown `type` strings and bad transform names fail at publish time (not just at run time), satisfies **AC-13, AC-9, AC-10**.
2. **Extend the error registry** `src/app/core/errors/execution_codes.py` with `FetchErrorCode` and `ExtractionErrorCode` StrEnums, satisfies **AC-14**.
3. **Add dependencies**: `uv add jsonschema` (runtime) and `uv add --dev respx` (test), satisfies **AC-11, AC-19**.
4. **Add settings**: six `EXTRACTION_HTTP_*` fields on the pydantic-settings model, validated at startup, satisfies **AC-4**.
5. **Scaffold `src/app/domains/extraction/`** with `service.py`, `fetcher.py`, `parser.py`, `extractor.py`, `transforms.py`, `validator.py`, `errors.py`, `schemas.py` (`ExtractionResult` value object), and the module's `__init__.py`; add the module to the `import-linter` contracts; satisfies **AC-1**.
6. **Implement `HttpFetcher`** against one shared `httpx.AsyncClient` (built in `src/app/main.py` lifespan): HTTP/2, hard timeouts, redirect cap, streamed body with the byte cap, content type gate, charset resolution; maps every failure to a `FetchErrorCode`; satisfies **AC-4, AC-5**.
7. **Implement `HtmlParser`** over selectolax with decoded `str` input; a parser crash maps to `extraction.selector_syntax_error` at the extractor layer, satisfies **AC-6**.
8. **Implement `Extractor`** with the container iteration, per field selector + transform pipeline + type coercion (no transforms yet, only `string` type for the first slice), satisfies **AC-7, AC-8** (partial).
9. **Implement the transform pipeline** in `transforms.py`: text normalizers, attribute pickers, numeric and money parsers, regex; registry pattern so feature 5 can share the allow list, satisfies **AC-9**.
10. **Implement type coercion** for `integer`, `decimal`, `boolean`, `url` (relative URL resolution against `<base href>` or the fetched URL), satisfies **AC-10, AC-8**.
11. **Implement `OutputSchemaValidator`** using `jsonschema` draft 2020-12, instantiated once per execution; first failing item ends the run, satisfies **AC-11**.
12. **Implement `ExtractionService.run(...)`** that composes the above and gates on `WorkflowConfig.pagination` (`extraction.pagination_unsupported` early return), satisfies **AC-1, AC-12**.
13. **Add structlog events and the metrics wrapper stub** `src/app/core/observability/metrics.py`; wire the service and the fetcher to emit, satisfies **AC-15**.
14. **Add the preview router** `src/app/api/v1/extraction.py` with `POST /workflows/{workflow_id}/versions/{id}/preview`, target URL resolution via `CanonicalURL` + `target_urls` lookup, Problem Details error mapping; mount it in `src/app/api/v1/router.py`, satisfies **AC-2, AC-3, AC-16**.
15. **Write the fixture suite** under `tests/fixtures/extraction/` plus the test modules covering every scenario in `Critical test scenarios`, satisfies **AC-19** and transitively every other AC.

The data model touch (step 1) sticks to one Pydantic field addition and ships in the first task because every later task reads it. No Alembic migration (JSONB column, additive).

## Consequences

**Positive**

- Feature 7 (the executor endpoint) becomes a persistence shell around a single `ExtractionService.run(...)` call; one service, one error vocabulary, one observability pattern.
- Operators can iterate on a workflow version against a real registered target URL and see the structured output without writing to the DB; the admin UI (feature 10) has an endpoint to call for the preview button.
- Error codes separate fetch failures (`fetch.*`) from extraction failures (`extraction.*`) so the agent repair paths (features 15 to 17) can decide between "retry the fetch" and "fix the selectors" without parsing an error message.
- `WorkflowConfig` extensions here (`required`, the transform registry, the type set) stay additive, respecting the "forward compatible JSONB" rule from [0003](../0003-data-model-mvp/index.md) AC-5; no migration.

**Negative / tradeoffs**

- Pagination is a known capability in `WorkflowConfig` but refused at run time; any workflow that needs it is blocked until the pagination slice ships.
- No retries, no circuit breaker, no rate limiting; a flaky target or a strict host will produce stable `fetch.timeout` or `fetch.http_error` runs that cost one full fetch each. Feature 20 and feature 21 are the right owners, but the gap is visible in the meantime.
- No SSRF guard in this feature; a mistake in target registration (an operator typing a localhost or private IP URL into `POST /targets`) is the only line of defence until feature 27 lands.
- The CSS only selector language cannot address XPath only patterns (e.g. selecting an element by preceding sibling text, or by XPath axes selectolax does not expose); any such page needs a workflow redesign or waits for a future selector language extension spec.
- Adding `jsonschema` as a runtime dep is a new line in `pyproject.toml`; pure Python, no C deps, small cost but not zero.

**Neutral**

- The shared `httpx.AsyncClient` is a new app lifespan dependency; subsequent fetching code (future scrapers, future outbound integrations) should reuse it rather than create per request clients.
- The `src/app/domains/extraction/` module path matches the DDD convention in `AGENTS.md`; feature 15 (LLM provider abstraction) and feature 17 (agent fallback) will later wrap or call this service rather than fork it.

## Follow-up

- [ ] Pagination support (`WorkflowConfig.pagination.next_selector` + `max_pages`). Its own spec; depends on this one. File before feature 7 ships to a prod like environment, since a published config with `pagination` will fail at run time until it lands.
- [ ] XPath or shorthand selector extension (e.g. `.price @data-amount`). Only when a real workflow needs it; capture the triggering use case in the spec.
- [ ] Allow a per workflow `allow_empty: bool` on `WorkflowConfig` so operators can opt a "sometimes legitimately zero items" workflow out of `extraction.no_container_match`. Additive change; its own spec.
- [ ] Formalise the Problem Details `type` URI convention (deferred since [0004](../0004-workflow-configuration-versioning/index.md) AC-13); not blocking this feature.
- [ ] SSRF controls: feature 27 is the owner. Flagged here so the gap is visible from this spec, not only from the scope row.
- [ ] Retries, backoff, circuit breakers: feature 20.
- [ ] Rate limiting, polite pacing, robots directives: feature 21.
- [ ] Metrics backend wiring (feature 13 swaps the `src/app/core/observability/metrics.py` stub for a real Prometheus or OTEL exporter).
- [ ] `WorkflowConfig` publish time validation (feature 5) should reuse the extraction transform registry and type set so a bad name is rejected at write, not just at run. Captured in step 1 above; also note here so it is not lost if that step is deferred.
- [ ] `validate_all` mode on the `output_schema` gate (AC-11), so feature 15 / 17 (agent repair) can see every failing item in one pass instead of only the first. Additive; its own spec.
