# 0005. Deterministic HTML extraction (static) — rationale

Decision record for [`index.md`](index.md). `/develop` does not read this file.

## Context

The platform's premise is that LLMs discover, repair, or validate configuration; the hot path for a known good workflow stays deterministic. Slice 1 (the MVP) is the thinnest usable whole for that premise: register a target, build a workflow, run it, see the output. Feature 6 is the "run it" piece and sits between the two already shipped specs:

- [0003](../0003-data-model-mvp/index.md) pins the `WorkflowConfig` shape (`container_selector`, `fields[{name, selector, transforms, type}]`, `output_schema`, optional `pagination`), reserves two error prefixes for this feature (`fetch.*` and `extraction.*`), and says every slice ships its own Alembic migration (this slice ships none, because it has no new tables).
- [0004](../0004-workflow-configuration-versioning/index.md) ships `WorkflowConfig` validation at write time (field name uniqueness + output schema coverage), so the extractor can trust the shape of what it reads.

Feature 7 (the executor endpoint) ships right after feature 6 and persists `executions` and `execution_results` rows around the same extraction call. So feature 6 must expose its logic as an in process service, not only as an HTTP endpoint. The scope row also asks for a preview path so operators and the admin UI (feature 10) can run a draft version against a target without writing to the DB.

Forces at play:

- **Stack is already pinned**: Python 3.12, httpx (HTTP/2), selectolax, structlog, pydantic-settings. No stack decision to make.
- **No LLM on the hot path**: feature 6 is pure Python; features 15 to 17 add the agent fallback later.
- **Operational safety is not optional at this stage**: a bad config pointed at a slow target can hang a worker; a huge response can exhaust memory. Hard timeouts and a body cap must land in the first slice, even though retries, rate limiting, and SSRF are their own slices.
- **The error vocabulary is load bearing**: the agent repair paths (features 15 to 17) will key off `error_code`, and the execution browser (feature 11) will filter on it. Stable codes have to land now, not later.
- **Skateboard delivery**: the thinnest usable whole first. Pagination is a known future dimension but doubles the fetch surface area; defer it.

## Options considered

### Option 1: Service module + non persistent preview endpoint; CSS only; `httpx` + `selectolax` + `jsonschema`; pagination deferred

An `ExtractionService` library consumed by both the preview endpoint and (later) feature 7's execution endpoint. CSS selectors only via selectolax. One shared `httpx.AsyncClient` with hard timeouts and a streamed body cap. `jsonschema` for the `output_schema` run time gate. Two new error prefix enums. Pagination refused at run time with a stable code.

**Pros**:

- Thinnest usable whole: a draft workflow can be previewed on day one; feature 7 is a persistence shell on day two.
- Error vocabulary is complete for Slice 1 (features 6, 7, 11) and ready for Slice 4 (features 15 to 17).
- No new DB table, no migration, one additive `WorkflowConfig` field (`required: bool = true`), fully forward compatible per [0003](../0003-data-model-mvp/index.md) AC-5.
- Reuses every library already in the stack; adds only `jsonschema` (runtime, pure Python) and `respx` (dev).

**Cons**:

- Pagination is a known gap; a published workflow version with `pagination` configured cannot run until the pagination slice ships.
- CSS only cannot address XPath only patterns; a page that needs an XPath axis has to wait for a selector language extension spec.
- No SSRF controls; the host allow list is enforced indirectly through target registration (feature 2). Fine while access is operator only, needs feature 27 before any multi tenant posture.

### Option 2: Library only, no preview endpoint

Ship only the `ExtractionService` module. Feature 7 is the first HTTP user; the admin UI preview waits for feature 7 to be done.

**Pros**:

- One less endpoint to ship in this slice.
- Fewer routes to touch when SSRF controls land (feature 27 only needs to wrap feature 7's call site).

**Cons**:

- No path for operators to try a draft before publish; the only way to see the extractor at work is to publish and run. Publishing a bad version to try it is the wrong workflow.
- Admin UI (feature 10) ends up blocked on feature 7 for its preview button; the two features become coupled when they do not have to be.

### Option 3: Pagination included; multi fetch in the first slice

Follow `next_selector` up to `max_pages` as part of this feature.

**Pros**:

- A category workflow can run end to end on day one.

**Cons**:

- Doubles the fetch surface area (per page error isolation, partial result decisions, back pressure between pages) in the slice that is supposed to be the thinnest usable whole.
- Encourages a workflow design that leans on pagination before deterministic rate limiting lands (feature 21). A loop of 50 fetches without pacing is exactly the behaviour feature 21 is meant to prevent.
- The "defer and refuse at run time" posture is reversible (any later slice can add it); including it now is harder to roll back without breaking configs.

### Option 4: CSS + XPath selector language, lxml alongside selectolax

Accept `xpath:...` prefixed selectors, parse with lxml.

**Pros**:

- Covers XPath axes selectolax does not expose (preceding sibling, following, ancestor by text content).

**Cons**:

- A second parser means two code paths, two error vocabularies, two sets of performance characteristics (lxml is C level, selectolax is C level, but their trees differ).
- The MVP catalog pages observed so far are CSS addressable; adding a second language now is paying a maintenance cost for a hypothetical use case.
- Any extension can be done later as its own spec, triggered by a real workflow that needs it.

## Rationale

**Option 1** wins because it maps precisely onto the Skateboard delivery approach pinned in `AGENTS.md`: the first task delivers the thinnest usable whole (fetch + extract + validate + return + preview endpoint), and every other dimension (pagination, retries, SSRF, rate limiting, metrics backend, XPath) is a later slice with a clear owner (features 20, 21, 27, 13, and a future selector extension spec respectively). The service + endpoint split means feature 7 becomes a persistence shell around a solved problem, which is the shape the data model spec [0003](../0003-data-model-mvp/index.md) anticipated.

Choosing CSS only (over Option 4) is a deliberate boring technology call: selectolax is already in the stack, it is Lexbor backed (fast), and every static catalog page observed in the project today is CSS addressable. A second selector language is reversible later; locking in two parsers now is harder to walk back.

Deferring pagination (over Option 3) keeps the first slice honest. A workflow version can carry a `pagination` document today (per [0003](../0003-data-model-mvp/index.md) AC-5) but running it fails with `extraction.pagination_unsupported`; the gap is visible, not hidden. This also means feature 21 (rate limiting) can land before the first multi fetch workflow ships, which is the right ordering.

Choosing a preview endpoint (over Option 2) solves two problems at once: operators get an iteration loop before publish, and the admin UI (feature 10) stops being coupled to feature 7. The endpoint is non persistent so the extra attack surface is limited to "fetching a registered target URL", which is already what feature 7 will do once it lands.

The engineer's answers on the smaller calls (observability vocabulary, testing fixture layout, error code set, SSRF deferral) were accepted as recommended. They are explicit in the AC list so they can be challenged at the final confirmation panel rather than buried.

## Options considered: smaller calls (settled by the architect)

- **Observability**: structlog events keyed off the extraction phases plus a thin metrics wrapper that feature 13 will swap behind the same interface. Reason: a Prometheus or OTEL dep in Slice 1 is premature; the wrapper is one file, has one interface, and swaps cleanly later.
- **Testing**: HTML fixtures under `tests/fixtures/extraction/<site_slug>/<case>.html`, `respx` for HTTP stubs, golden file comparisons against `.expected.json` siblings. Reason: `respx` is the stock httpx mock, zero network tests, and the golden file pattern makes a regression obvious in a diff.
- **Error codes**: enumerated per AC-14, split by prefix (`fetch.*` vs `extraction.*`) to match the agent repair paths' decision axis. Reason: the prefixes were already reserved by [0003](../0003-data-model-mvp/index.md) AC-17; the list here is the first concrete population.
- **SSRF**: deferred to feature 27 explicitly, with a note that target registration is the only guard until it lands. Reason: feature 27 is tagged GA in the scope header and pulling it forward would push the first slice past its intended size.
