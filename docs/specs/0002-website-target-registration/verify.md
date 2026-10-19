# Verify: website & target registration · spec 0002 · updated 2026-10-19

_Steps derived from spec 0002 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## Commands (hit the running API with `curl`; export `BASE=http://127.0.0.1:8000/api/v1`)

- [ ] `curl -sS -X POST $BASE/websites -H 'content-type: application/json' -d '{"host":"Example.COM:443","display_name":"Example"}'` → `201`; response body `host` is `example.com`; `id` present; `status=active` → AC-1, AC-3
- [ ] `curl -sS -X POST $BASE/websites/$WID/targets -H 'content-type: application/json' -d '{"url":"HTTPS://Example.COM:443/p/1#top","label":"Product 1"}'` → `201`; `url` is `https://example.com/p/1` → AC-2, AC-3
- [ ] `curl -sS -X POST $BASE/websites -H 'content-type: application/json' -d '{"host":"EXAMPLE.com","display_name":"Dup"}'` → `409 duplicate_website` with `existing_id` and `canonical_host` extension fields → AC-4
- [ ] `curl -sS -X POST $BASE/websites/$WID/targets -H 'content-type: application/json' -d '{"url":"https://example.com/p/1","label":"Dup"}'` → `409 duplicate_target` with `existing_id` and `canonical_url` → AC-4
- [ ] `curl -sS -X POST $BASE/websites/$WID/targets -H 'content-type: application/json' -d '{"url":"https://other.com/x","label":"Mismatch"}'` → `422 host_mismatch` → AC-5
- [ ] Mark site `inactive`, then `curl -sS -X POST $BASE/websites/$WID/targets ...` → `422 website_inactive` → AC-6
- [ ] `curl -sS -X POST $BASE/websites/<soft-deleted-id>/targets ...` → `404` → AC-6
- [ ] `curl -sS -X POST $BASE/websites/$WID/targets -H 'content-type: application/json' -d '{"url":"ftp://example.com/x","label":"Bad"}'` → `422` (scheme rejected, `code=validation_error`) → AC-7
- [ ] `curl -sS "$BASE/websites?page_size=201"` → `422` → AC-7
- [ ] Oversize body (>1 MB) → `413` (middleware) → AC-7
- [ ] `curl -sS "$BASE/websites?status=all"` returns `active` + `inactive` rows; `?status=active` returns only `active`; neither returns soft-deleted → AC-8
- [ ] `curl -sS "$BASE/websites/$WID/targets"` on an `inactive` parent still lists targets; on a soft-deleted parent returns `404` → AC-8
- [ ] `curl -sS "$BASE/websites/<unknown-id>"` → `404` → AC-9
- [ ] `curl -sS -X PATCH $BASE/websites/$WID -H 'content-type: application/json' -d '{"host":"other.com"}'` → `422 immutable_field` → AC-10
- [ ] `curl -sS -X PATCH $BASE/targets/$TID -H 'content-type: application/json' -d '{"url":"https://example.com/other"}'` → `422 immutable_field` → AC-10
- [ ] Empty-body PATCH returns `200` with the current resource → AC-10
- [ ] `curl -sS -X DELETE $BASE/websites/$WID` → `204`; subsequent `GET $BASE/targets/$TID` → `404`; a second `DELETE` → `204` (idempotent) → AC-11
- [ ] After `DELETE`, `POST $BASE/websites` with the same `host` returns `201` with a fresh `id` → AC-12
- [ ] Every 4xx response is `application/problem+json`, has a stable `code`, and includes `correlation_id` → AC-13

## Value sourcing coverage (exercise each row of the spec's Value sourcing table)

- [ ] `host` canonicalization: `Example.COM:443` → `example.com` (strips default port, lowercases)
- [ ] `url` canonicalization: `HTTPS://Example.COM:443/a/./b/../c#frag` → `https://example.com/a/c` (lowercases scheme + host, drops default port, resolves dot segments, drops fragment)
- [ ] IDN host: `Bücher.example` on POST stores as `xn--bcher-kva.example` → AC-3
- [ ] `id`: UUIDv7 (time ordered); two POSTs 1 s apart produce ids whose byte prefix sorts in order
- [ ] `status` default `active`; `created_at`/`updated_at` server-side (UTC, trailing `Z` serialization)
- [ ] `correlation_id` extension on every error echoes the inbound `X-Request-ID` when provided
- [ ] 409 duplicate response `existing_id` and `canonical_url` match the row returned by a plain `GET`

## Acceptance-criteria coverage

- AC-1 · POST website · AC-2 · POST target · AC-3 · canonicalization · AC-4 · dedup 409 · AC-5 · host match 422 · AC-6 · parent state (inactive 422, soft-deleted 404) · AC-7 · validation (schemes, length, pagination, body size) · AC-8 · list pagination + status filter · AC-9 · get single + soft-deleted 404 · AC-10 · PATCH mutable + immutable field · AC-11 · DELETE cascade + idempotent · AC-12 · re-register after delete · AC-13 · Problem Details envelope
