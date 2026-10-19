# 0002. Website and target URL registration

**Date**: 2026-10-19
**Status**: In Progress

## Summary

This feature stands up the `websites` and `target_urls` domain in the FastAPI monolith so operators can register the sites you intend to scrape and the specific URLs within them. Websites are identified by a canonicalized host (lowercase, IDN safe); target URLs live under exactly one website and must share its host. Duplicate submissions are rejected after canonicalization with a `409 Conflict`, so the catalog stays clean before any workflow runs against it.

## Context

The platform binds reusable scraping workflows to known targets, and nothing downstream (workflow configuration, deterministic extraction, execution) can land without an addressable set of websites and URLs. Today the `src/app/domains/websites/` package is empty. The scope row (Feature 4) sets the minimum bar: `POST /websites`, `POST /targets`, listing, canonicalized duplicates, and structured 4xx errors.

Four forces shape the design:

1. **Catalog hygiene over user convenience.** Scraping cost (bandwidth, politeness budget, human review of failed configs) is paid per registered target, so a loose definition of "the same URL" is expensive. Canonicalization is a load bearing invariant, not a UX nicety.
2. **Clear ownership of a URL.** Later slices (workflow execution, product provenance) will reference `target_urls.id` and need to assume a target points at one website. Scoping targets under a website by host match prevents mixups.
3. **Modular monolith discipline.** This is the first real domain under `src/app/domains/`; it sets the shape later domains (workflows, executions, extraction) copy. Keep it small, boring, and recognizable.
4. **Open prerequisite.** Feature 3 (MVP data model) is still `needs a decision` in the scope. Rather than wait, this spec fully specifies the two tables it owns; Feature 3 will cover only the entities no slice feature owns, or roll into an umbrella.

> ⚠️ Premise note: the scope row talks about "target URL" as if it were one shape; the staged interview confirmed the simple shape (one concrete page per row with a label and a status). Templates and URL patterns are deliberately deferred to the workflow-configuration slice, where they belong. The spec therefore commits to concrete URLs only.

> ⚠️ Premise note: `0001-stack-and-architecture` pins soft delete on `websites` and keeps `executions` immutable; it does not pin soft delete on `target_urls`. This spec adds soft delete on `target_urls` for symmetry and for the website-level cascade. Flagged so later specs do not re-litigate it.

## Requirements

**User stories**

- As a platform operator, I want to register a website so that later workflows can bind to it.
- As a platform operator, I want to register one or more target URLs under a website so that workflows have concrete pages to extract from.
- As a platform operator, I want duplicate URL submissions to be rejected or deduped so that the catalog does not drift.
- As a platform operator, I want to list, inspect, rename, and deactivate websites and targets so that the catalog can be curated over time.
- As a platform operator, I want invalid input to fail with a clear, structured error so that I can correct and retry.

**Acceptance criteria** (the contract `/develop` builds to and `/check verify` checks)

- **AC-1**: `POST /api/v1/websites` with `{host, display_name}` creates a website, returns `201 Created` with the full resource (including `id`, `status=active`, timestamps), persists the host in canonical form (lowercase, IDN punycode).
- **AC-2**: `POST /api/v1/websites/{website_id}/targets` with `{url, label}` creates a target under that website, returns `201 Created` with the full resource, persists the URL in canonical form.
- **AC-3**: Canonicalization rules applied to every URL and host (RFC 3986 section 6 syntax-based normalization plus feature-specific rules): lowercase the scheme, lowercase the host, IDN punycode normalize the host, strip default port (`:80` for http, `:443` for https), drop fragment, resolve dot-segments in the path (`/a/./b/../c` → `/a/c`), reject any userinfo component (`user:pass@`), reject non-`http`/`https` schemes with `422`. Path, query, and percent-encoding are preserved as submitted (no case folding of path, no query sorting, no query stripping). Canonicalization is idempotent: an already-punycode host (`xn--…`) and an already-canonical URL pass through unchanged.
- **AC-4**: Submitting an already-registered website (same canonical host) or an already-registered target (same canonical URL under the same website) returns `409 Conflict` as RFC 7807 Problem Details, with `code=duplicate_website` or `code=duplicate_target` and the existing resource's `id` and canonical URL in the response body.
- **AC-5**: A target whose canonical host does not match its parent website's host is rejected with `422 Unprocessable Entity`, Problem Details, `code=host_mismatch`.
- **AC-6**: Submitting a target under a website that is soft-deleted returns `404 Not Found` (the website is invisible to the API); submitting under a website whose `status=inactive` returns `422 Unprocessable Entity` with `code=website_inactive`.
- **AC-7**: Input validation: `host` ≤ 253 chars and, after canonicalization (which strips any `:port`), a syntactically valid DNS hostname (labels 1..63 chars, overall ≤ 253, letters/digits/hyphens/dots, no leading/trailing hyphen per label); `url` ≤ 2048 chars and syntactically a valid absolute URL with scheme `http` or `https`; `display_name` and `label` each 1–200 chars; `page` ≥ 1 and `page_size` 1..200. Violations return `422` Problem Details with field-level details (`code=validation_error` for Pydantic rejections, `code=invalid_pagination` for pagination violations). A request body larger than 1 MB is rejected with `413` by the middleware pinned in spec 0001.
- **AC-8**: `GET /api/v1/websites` and `GET /api/v1/websites/{id}/targets` return offset-paginated lists (default page size 50, max 200, per spec 0001). Default filter: `status=active` only. `?status=all` includes `inactive`. Soft-deleted rows are never returned. `GET /api/v1/websites/{id}/targets` works regardless of the parent website's `status` (an `inactive` parent still lists its targets); it returns `404` only if the parent is missing or soft-deleted.
- **AC-9**: `GET /api/v1/websites/{id}` and `GET /api/v1/targets/{id}` return the single resource or `404 Not Found` (also used for soft-deleted rows).
- **AC-10**: `PATCH /api/v1/websites/{id}` accepts `display_name` and `status`; `PATCH /api/v1/targets/{id}` accepts `label` and `status`. `host` and `url` are immutable; attempting to set them returns `422` with `code=immutable_field`. A `status` value outside the enum returns `422 validation_error`. An empty-body PATCH is a no-op and returns `200` with the current resource. PATCH on a soft-deleted resource returns `404`. Re-activation (`status: active`) of an `inactive` resource is allowed; re-activation does not change `deleted_at`.
- **AC-11**: `DELETE /api/v1/websites/{id}` soft-deletes the website (sets `deleted_at = now()`) and, in the same transaction, soft-deletes every one of its `target_urls`. `DELETE /api/v1/targets/{id}` soft-deletes a single target. Idempotent: deleting an already-deleted resource returns `204 No Content`.
- **AC-12**: After soft-delete, the host (resp. `(website_id, url)`) becomes available for re-registration (via the partial unique index); a new `POST` succeeds and creates a new row with a new `id`.
- **AC-13**: Every error response uses `application/problem+json`, carries a per-domain stable `code` enum value, and includes the `correlation_id` extension field (per spec 0001).

## Options considered

### Option 1: Native domain module, stdlib canonicalization, nested routes (chosen)

A dedicated `src/app/domains/websites/` module with its own router mounted at `/api/v1/websites`, a `CanonicalURL` value object built on `urllib.parse` + `idna`, two tables (`websites`, `target_urls`) with partial unique indexes, and nested routes for target creation. Business invariants (host match, parent state) enforced in a service layer; schema invariants (uniqueness, FK) enforced in Postgres.

**Pros**
- Boring, matches the module shape pinned by 0001 (first domain sets the template).
- Zero new dependencies; stdlib handles URL parsing cleanly on Python 3.12.
- Partial unique indexes let soft-delete + re-registration coexist without application-level checks.

**Cons**
- `CanonicalURL` logic is non-trivial (fragment, default ports, IDN); needs its own unit tests.
- Host-match invariant is enforced in the service layer, not the schema; a buggy service could violate it. Mitigated by a tightly scoped test suite.

### Option 2: Flat routes, URL template support, JSONB metadata

One `/api/v1/targets` endpoint that takes `website_id` in the body, with `target_urls.url` as a template (`https://example.com/products/{sku}`) and a JSONB `metadata` column for free-form tags.

**Pros**
- One endpoint instead of two.
- Future-flexible: downstream workflows could expand templates against a seed list.

**Cons**
- Templates and metadata are workflow concerns, not registration concerns; the model would mix two layers of responsibility.
- Validating "is this a URL" against a template requires substitution rules this spec would have to define, prematurely.
- Postponing templates to the workflow slice costs nothing today and keeps this spec small.

### Option 3: Registrable-domain grouping with PSL

Group `www.example.com` and `shop.example.com` under one `example.com` website row by resolving the registrable domain via the Public Suffix List.

**Pros**
- Cleaner mental model for multi-subdomain sites.

**Cons**
- Adds a PSL dependency and a monthly refresh problem (the list drifts).
- A real registration mistake like `www.exxample.com` would silently register under `exxample.com`; the operator wanted exact.
- Can be added later as a non-breaking read-side feature; the schema does not have to decide today.

## Decision

**Chosen option**: Option 1: Native domain module, stdlib canonicalization, nested routes.

Websites are identified by a canonicalized `host`; target URLs are nested under one website and must share its host; duplicates (post-canonicalization) are rejected with `409 Conflict`; soft delete is cascaded from website to targets in the service layer.

**Implementation skills**: `fastapi` (`fastapi/fastapi`, `.claude/skills/fastapi/`) · `sqlalchemy-alembic-expert-best-practices-code-review` (`wispbit-ai/skills`, `.claude/skills/sqlalchemy-alembic-expert-best-practices-code-review/`) · `python-testing-patterns` (`wshobson/agents`, `.claude/skills/python-testing-patterns/`) · `modern-python` (`trailofbits/skills`, `.claude/skills/modern-python/`)

## Rationale

Option 1 wins because the four forces in Context pull the same way. Spec 0001 pinned a modular-monolith shape with per-domain modules; this is the first real domain, so the shape it establishes becomes the shape every later domain copies. Stdlib `urllib.parse` plus `idna` (also stdlib on Python 3.12) covers every canonicalization rule the acceptance criteria need without pulling in `yarl` or `rfc3986`, both of which solve problems this feature does not have. Partial unique indexes (`UNIQUE … WHERE deleted_at IS NULL`) are a standard Postgres pattern that lets the same host be re-registered after a soft delete without application-level pre-checks or ghost-row collisions.

Option 2's template support was rejected because it blurs the registration/execution boundary 0001 was careful to establish; templates belong in the workflow-configuration spec (Feature 5), where expansion rules can be designed once rather than guessed twice. Option 3's PSL grouping was rejected on the "boring choice" test: the operator asked for exact hosts, no production problem exists today, and this is reversible later as a read-side feature.

The host-match invariant (AC-5) is deliberately enforced in the service layer, not the schema, because expressing it as a DB check constraint would require a trigger or a redundant denormalized column. The feature test suite covers the invariant, and no third-party writer touches these tables.

## Feature design

**Data model sketch**

`websites`
| Column | Type | Constraints |
|---|---|---|
| `id` | `uuid` | PK, UUIDv7 generated application-side |
| `host` | `text` | NOT NULL, canonical form, partial UNIQUE `(host) WHERE deleted_at IS NULL` |
| `display_name` | `text` | NOT NULL, CHECK length 1..200 |
| `status` | `text` | NOT NULL, CHECK `status IN ('active','inactive')`, default `'active'` |
| `created_at` | `timestamptz` | NOT NULL, server default `now()` |
| `updated_at` | `timestamptz` | NOT NULL, server default `now()`, maintained by SQLAlchemy `onupdate` |
| `deleted_at` | `timestamptz` | NULL |

`target_urls`
| Column | Type | Constraints |
|---|---|---|
| `id` | `uuid` | PK, UUIDv7 |
| `website_id` | `uuid` | NOT NULL, FK → `websites(id)` ON DELETE RESTRICT, indexed |
| `url` | `text` | NOT NULL, canonical form, CHECK length 1..2048 |
| `label` | `text` | NOT NULL, CHECK length 1..200 |
| `status` | `text` | NOT NULL, CHECK `status IN ('active','inactive')`, default `'active'` |
| `created_at` | `timestamptz` | NOT NULL, server default `now()` |
| `updated_at` | `timestamptz` | NOT NULL, SQLAlchemy `onupdate` |
| `deleted_at` | `timestamptz` | NULL |

Indexes on `target_urls`:
- `UNIQUE (website_id, url) WHERE deleted_at IS NULL` (dedup + list-under-website)
- `INDEX (website_id)` (plain FK index, covers soft-deleted scans)

Relationship: `websites` 1 — N `target_urls`.

**State transitions**

Website and target each move: `active ⇄ inactive` (via `PATCH … {status}`); either reaches `deleted` via `DELETE` (sets `deleted_at`). Delete is terminal from the API's perspective (idempotent). Deleting a website also sets `deleted_at` on every one of its targets in the same transaction. The partial unique index allows a new row with the same host (resp. `(website_id, url)`) after a delete.

```
            PATCH status                DELETE
  active ───────────────▶  inactive  ─────────────▶  (soft-deleted, 404 to API)
            ◀───────────────
            PATCH status
```

**API surface**

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/api/v1/websites` | `POST` | `host:str` (req, 1..253), `display_name:str` (req, 1..200) | `id`, `host`, `display_name`, `status`, `created_at`, `updated_at` | none (slice) | `409 duplicate_website`, `422` on validation |
| `/api/v1/websites` | `GET` | `page:int` (opt, default 1), `page_size:int` (opt, default 50, max 200), `status:str` (opt, `active`\|`inactive`\|`all`, default `active`) | `items[]`, `total`, `page`, `page_size` | none | `422` on bad pagination |
| `/api/v1/websites/{id}` | `GET` | `id:uuid` (path) | website resource | none | `404` if missing or soft-deleted |
| `/api/v1/websites/{id}` | `PATCH` | `display_name:str` (opt), `status:str` (opt) | updated website resource | none | `404`, `422 immutable_field` if `host` present |
| `/api/v1/websites/{id}` | `DELETE` | `id:uuid` (path) | — (204) | none | — (idempotent) |
| `/api/v1/websites/{website_id}/targets` | `POST` | `url:str` (req, 1..2048, http/https), `label:str` (req, 1..200) | target resource | none | `404` if website missing/soft-deleted, `422 website_inactive`, `422 host_mismatch`, `409 duplicate_target`, `422` on validation |
| `/api/v1/websites/{website_id}/targets` | `GET` | `page`, `page_size`, `status` (same semantics as websites) | paginated list of targets | none | `404` if website missing/soft-deleted, `422` on bad pagination |
| `/api/v1/targets/{id}` | `GET` | `id:uuid` (path) | target resource | none | `404` |
| `/api/v1/targets/{id}` | `PATCH` | `label:str` (opt), `status:str` (opt) | updated target resource | none | `404`, `422 immutable_field` if `url` present |
| `/api/v1/targets/{id}` | `DELETE` | `id:uuid` (path) | — (204) | none | — (idempotent) |

All responses JSON, snake_case; datetimes ISO-8601 with `Z`; UUIDs as strings. Error responses are `application/problem+json` per spec 0001 (fields: `type`, `title`, `status`, `detail`, `code`, `correlation_id`; and for `409` responses, `existing_id` and `canonical_url` extension fields).

Per-domain error `code` enum (seed): `duplicate_website`, `duplicate_target`, `host_mismatch`, `website_inactive`, `immutable_field`, `invalid_pagination`, plus the shared `validation_error` for Pydantic rejections. The 1 MB request-body limit (middleware pinned by spec 0001) returns `413 Payload Too Large` with its own stable code at the middleware layer; no domain code is minted here.

**Duplicate detection flow**: the service does one `SELECT … WHERE canonical_key = ? AND deleted_at IS NULL` before insert for the common case; a race-induced `IntegrityError` on the partial unique index is caught, the row is re-read with the same `SELECT`, and the response is rendered as `409` with `existing_id` and `canonical_url` from that row. Never retry the insert on `IntegrityError`.

**Value sourcing**

| Action | Value produced / displayed | Source |
|---|---|---|
| `POST /websites` | `host` (canonical, bare DNS label, no `:port`) | Input `host`, run through `CanonicalHost.from_str()` (lowercase, IDN punycode, strip any trailing `:port` whether default or not, reject invalid DNS). The stored host carries no port; host-match against a target URL compares `CanonicalURL.host` only. |
| `POST /websites` | `id` | Application-generated UUIDv7 produced by `src/app/core/ids.py::new_id()`, implemented using `uuid_utils` (`uv add uuid-utils`). `uuid.uuid7` does not exist on Python 3.12. |
| `POST /websites` | `status` | Default `'active'` (DB default) |
| `POST /websites` | `created_at`, `updated_at` | Server-side `now()` (DB default + SQLAlchemy `onupdate`) |
| `POST /targets` | `url` (canonical) | Input `url`, run through `CanonicalURL.from_str()` (lowercase host, strip default port, drop fragment, IDN punycode, preserve scheme) |
| `POST /targets` | host-match check | Compare `CanonicalURL.host` with the parent `websites.host` (DB row looked up by path `website_id`) |
| `POST /targets` | parent-state check | `websites.deleted_at` and `websites.status` of the parent row |
| `409` duplicate response | `existing_id`, `canonical_url` | Row returned by the unique-violation lookup (`SELECT id, host | url FROM … WHERE … AND deleted_at IS NULL`) |
| `GET` list | `total` | `SELECT count(*)` with the same filter as the main query |
| Any error | `correlation_id` | Request-scoped structlog contextvar bound by the `asgi-correlation-id` middleware (per 0001) |
| Any response | `created_at`, `updated_at` serialization | ISO-8601 with trailing `Z`, UTC (per 0001 convention) |

**Key invariants**

- Canonical form is the only form stored for `websites.host` and `target_urls.url`; the service never writes a non-canonical value.
- `target_urls.url`'s host equals `websites.host` for its parent, for every live row.
- `(host) WHERE deleted_at IS NULL` is unique on `websites`; `(website_id, url) WHERE deleted_at IS NULL` is unique on `target_urls`.
- If `websites.deleted_at IS NOT NULL`, every one of its `target_urls` also has `deleted_at IS NOT NULL`.
- `host` on `websites` and `url` on `target_urls` are immutable after creation.
- `status ∈ {'active','inactive'}` (DB CHECK).

**Security model**

- No authn/authz in this slice; endpoints are open on localhost by assumption. Real API-key auth is pinned to Slice 11 (Feature 26), with a minimal dev-key gate arriving with the Admin UI slice.
- No regulated data: hosts and URLs are not PII and carry no secrets.
- SSRF controls (preventing registration of internal IPs or metadata hosts) are out of scope here; they are Feature 27 and will add a URL validator in front of this one. This spec deliberately does not pre-empt that work; validation here is syntactic plus canonicalization only.

**Configuration required**

- None. All behavior is covered by existing settings pinned in 0001 (DB URL, pagination defaults, request-body cap, correlation-ID middleware).

**Critical test scenarios**

- Happy path website: `POST /websites {host: "Example.COM:443"}` returns `201` with `host: "example.com"`; `GET /websites/{id}` returns the same canonical form. Verifies **AC-1**, **AC-3**.
- Happy path target: under an active website, `POST /websites/{id}/targets {url: "HTTPS://Example.COM:443/p/1#top"}` returns `201` with `url: "https://example.com/p/1"`. Verifies **AC-2**, **AC-3**.
- Duplicate website: second `POST` with the same (differently-cased) host returns `409 duplicate_website` with the first row's `id`. Verifies **AC-4**.
- Duplicate target: second `POST` with the same URL under the same website returns `409 duplicate_target`. Verifies **AC-4**.
- Host mismatch: target `url` host does not equal the parent website's host → `422 host_mismatch`. Verifies **AC-5**.
- Parent inactive: target `POST` under an `inactive` website → `422 website_inactive`. Verifies **AC-6**.
- Parent soft-deleted: target `POST` under a soft-deleted website → `404 Not Found`. Verifies **AC-6**.
- Validation: oversize `url` (>2048), non-http scheme (`ftp://`), empty `display_name` → `422` with field errors. Verifies **AC-7**.
- Pagination defaults: `GET /websites` with 60 active rows returns 50 items, `page_size=50`, `total=60`; `?page_size=201` → `422`. Verifies **AC-8**.
- Status filter: `GET /websites?status=active` excludes inactive rows; `?status=all` includes them; soft-deleted never appear. Verifies **AC-8**.
- Immutable field: `PATCH /websites/{id} {host: "other.com"}` → `422 immutable_field`. Verifies **AC-10**.
- Cascade delete: `DELETE /websites/{id}` sets `deleted_at` on the website and all its `target_urls` atomically; a subsequent `GET /targets/{tid}` returns `404`. Verifies **AC-11**.
- Delete idempotency: deleting an already-deleted website returns `204`. Verifies **AC-11**.
- Re-registration after delete: delete a website, `POST /websites` with the same host succeeds with a fresh `id`. Verifies **AC-12**.
- Problem Details envelope: any 4xx response has `application/problem+json`, a stable `code`, and `correlation_id`. Verifies **AC-13**.

## Build plan

Skateboard order: one migration establishes the whole target data model, then the smallest usable whole (create + read) ships first, then the mutations round out the slice. The scope row's `Done when` is cleared at step 5; steps 6–7 complete the acceptance-criteria contract above.

1. **Migration** `YYYYMMDDHHMM_add_websites_and_target_urls.py`: both tables, both partial unique indexes, FK index on `target_urls.website_id`, CHECK constraints on `status`, length checks on text columns. Satisfies **AC-1**, **AC-2**, **AC-4**, **AC-7**, **AC-11**, **AC-12**.
2. **Domain model** in `src/app/domains/websites/` (SQLAlchemy ORM `Website`, `TargetURL`; `CanonicalHost` and `CanonicalURL` value objects; repository with `create`, `get_by_id`, `list_by_filter`, `update`, `soft_delete`, `cascade_soft_delete_targets`). Satisfies **AC-1**, **AC-2**, **AC-3**, **AC-11**, **AC-12**.
3. **Service layer** `WebsiteService` and `TargetService` enforcing: duplicate → `DuplicateError`, host mismatch → `HostMismatchError`, parent soft-deleted → `NotFoundError`, parent `inactive` → `WebsiteInactiveError`, immutable-field attempt → `ImmutableFieldError`. Satisfies **AC-4**, **AC-5**, **AC-6**, **AC-10**.
4. **Pydantic schemas** `WebsiteCreate/Read/Update`, `TargetCreate/Read/Update`, `PaginatedList[T]` with strict length and format validators (`AnyHttpUrl` constrained to `http`/`https`, hostname regex, max lengths). Satisfies **AC-7**.
5. **Router** `src/app/api/v1/websites.py` with the full endpoint table above (POST + GET list + GET single for both resources). Wire into `api/v1/router.py`. This is the Skateboard milestone that clears the scope row's `Done when`. Satisfies **AC-1**, **AC-2**, **AC-8**, **AC-9**, **AC-13**.
6. **Mutation endpoints**: PATCH and DELETE on both resources, with the service invariants above. Satisfies **AC-10**, **AC-11**, **AC-12**.
7. **Error mapping**: register exception handlers in `core/errors.py` so each domain exception renders a Problem Details response with its stable `code` and the `correlation_id` extension. Satisfies **AC-4**, **AC-5**, **AC-6**, **AC-10**, **AC-13**.

## Consequences

**Positive**
- The first domain under `src/app/domains/` lands with a shape later domains can copy: value objects for canonical primitives, repository + service split, Pydantic schemas at the edge, Problem Details errors.
- Canonicalization is centralized in one value object; later slices (workflow binding, dedup, provenance) can trust the invariant without re-validating.
- Partial unique indexes let soft-delete and re-registration coexist cleanly, without application-level pre-checks or `TRUNCATE`-after-delete gymnastics.

**Negative / tradeoffs**
- The host-match invariant is enforced in the service layer, not the schema. A direct DB write that bypassed the service could create an inconsistent row. Mitigated by: no third-party writers, and a test asserting the invariant.
- `CanonicalURL` is now a load bearing piece of code that every later domain depends on. A bug in it (e.g. stripping a query param that is actually meaningful on some site) is a cross-cutting bug.
- Soft delete on `target_urls` was not pinned by 0001 and is added here; later slices (executions referencing a target) must remember the "soft-deleted targets stay joinable for history" rule.
- No idempotency key on `POST`; concurrent duplicate creates rely on the DB unique index to produce `409`. Acceptable for an internal catalog with low write rate.

**Neutral**
- No new third-party dependencies; `urllib.parse` and `idna` are stdlib on 3.12.
- The API deliberately omits authn/authz; Slice 11 will add it in front of these routers without changing the handlers.
- UUIDv7 generation uses whatever helper 0001's scaffold adopted (if 0001 did not land one, this feature adds a tiny `core/ids.py`; it is a one-time cost, not a new convention).

## Follow-up

- [x] Feature 3 (MVP data model) is now designed as spec [0003](0003-data-model-mvp/index.md): it took path (a), the umbrella shape, and references this spec for `websites` and `target_urls` while specifying the four workflow/execution tables itself.
- [ ] Confirm 0001's scaffold shipped a UUIDv7 generator in `src/app/core/`. If present, reuse it in step 2 of the Build plan instead of adding `core/ids.py` + the `uuid-utils` dependency.
- [ ] Flag to Feature 27 (SSRF controls): a URL validator layer will sit in front of `TargetService`; this spec's canonicalization is syntactic only. Make sure Feature 27's spec names the composition order (SSRF validation → canonicalization → service).
- [ ] Flag to Feature 7 (workflow execution): executions reference `target_urls.id`; decide at that point whether a soft-deleted target can still be referenced historically (likely yes, via a join that ignores `deleted_at` for read).
- [ ] Spec 0001 pinned soft delete on `websites` and `workflows` but did not mention `target_urls`. This spec extends the pattern. Consider a one-line update to 0001's "Soft delete" bullet when `/sync` next runs.
