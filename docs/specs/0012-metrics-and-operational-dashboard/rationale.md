# 0012 — Rationale

The decision record for the metrics & operational dashboard spec. `/develop` does not read this file; it is the "why", kept out of the build-time context.

## Context

Spec 0001 pinned the stack and spec 0011 standardised structured logging and correlation, so every HTTP request, execution, and extraction already emits a JSON event with a correlation id. What is still missing is the time-series side of operational visibility: a response to "is the system healthy right now, and if not, where". The scope row names five metric families (request rate, latency percentiles, error rate, extraction success rate, per-domain throttling) and a dashboard that shows p50/p95 latency and error rate over the last hour, linkable from a run detail.

Three forces shape this decision:

- **Operational reality on day 180**: there is no SRE, no Prometheus server, no Grafana. The feature has to be useful without that stack, so an in-process + Postgres design is the only credible path for an MVP.
- **Stack reuse**: the project already runs on FastAPI + SQLAlchemy + Postgres, with a React 19 + TanStack + Radix admin SPA. Any new tool must earn its weight; adding a time-series database or a Prometheus deployment for a slice-3 feature is not justified at this scale.
- **Scope row commitments are real but minimal**: "last hour", "p50/p95 latency and error rate", "linkable from a run detail". The build must hit those exactly, no more, no less; percentile accuracy at the 99.9th and horizontal fleet-scale correctness are not promised yet.

Not deciding here would leave operators flying blind in staging and production: no view of request latency, no way to spot a slow workflow, no empirical check on the error-rate claims the logging feature just made observable.

## Options considered

### Option 1: In-process `prometheus-client` + Postgres `metric_minute` aggregation + Recharts dashboard (chosen)

Collect metrics in-process with the `prometheus-client` library (histograms + counters), flush them every 15 seconds to a `metric_minute` Postgres table keyed by minute bucket + metric + labels, serve a JSON query API, render four Recharts panels in a new `/metrics` tab of the admin SPA.

**Pros**:
- Zero new infrastructure. Postgres is already the primary store.
- `prometheus-client` is the industry-standard Python collector; a `/metrics` scrape endpoint can be added later with zero re-instrumentation.
- Pre-aggregated bucket rows stay bounded in size and queryable with plain SQL.
- End-to-end typed: FastAPI OpenAPI → `openapi-fetch` → TanStack Query → Recharts.
- The dashboard is self-contained; operators do not need a Grafana login or a new browser tab for an at-a-glance health check.

**Cons**:
- Six-bin histograms give approximate percentiles; the 99.9th percentile is a sketch, not a true value.
- Horizontally scaled deployments produce concurrent upserts into the same rows. The sum semantics make this correct but adds brief write amplification.
- Postgres outage longer than the buffer cap (default 15 minutes) drops data.

### Option 2: Raw metric events table + `percentile_cont` SQL

A `metric_event` table with `(ts, metric_name, labels, value)` rows written per observation; the query API computes percentiles via `percentile_cont(0.95) WITHIN GROUP (ORDER BY value)`.

**Pros**:
- Exact percentiles; no interpolation error.
- Simplest schema (one row per observation).
- No in-memory bucketing; the DB is the truth.

**Cons**:
- Linear growth with traffic. At 100 req/s on four metric families, the table grows ~34 million rows per day, needing an aggressive retention policy and partition management.
- A DB write per HTTP request burns latency even with batched inserts.
- Does not scale to the "scrape endpoint later" story; prometheus-client would still be needed on top for that.

### Option 3: Prometheus server scrape + Grafana dashboard (full standard stack)

Expose a `/metrics` endpoint in the FastAPI app, run a Prometheus server to scrape it, run Grafana for the dashboard, embed the Grafana panel in the admin UI via an iframe or screenshot API.

**Pros**:
- The standard, battle-tested observability pipeline. Scales to any team, any fleet.
- Grafana does the chart building and alerting work for us.
- Operators who know Prometheus feel at home.

**Cons**:
- Three new services to deploy, run, and keep patched (Prometheus, Grafana, optionally AlertManager).
- Dashboard embedding either breaks the single-admin-key auth model (iframe + separate Grafana auth) or forces a backend proxy.
- Massive overkill for a Skateboard slice on a project with no SRE and no existing Prometheus footprint.

### Option 4: Both: in-process `prometheus-client` AND Postgres aggregation AND Prometheus scrape endpoint

Everything in Option 1, plus expose the registry at `/metrics` for an external scraper.

**Pros**:
- Future-proofs for the day an SRE joins and wants a real Prometheus deployment.
- Dashboard still works today without external infra.

**Cons**:
- One more API surface to document, auth, and test for no immediate value.
- A scraper typically does not carry an API key, so adds a new auth decision (CIDR allowlist, separate token, or unauthenticated).
- "Future-proofing" that nobody asked for is a cost today.

## Rationale

Option 1 wins because it is the smallest step that hits the scope row's acceptance criteria without inventing problems that don't exist yet:

- **Operational reality**: an in-process library + a Postgres table is one new dep and one new table; a Prometheus deployment is a service to run, patch, and page on.
- **Stack reuse**: `prometheus-client` is Python-standard and plays with the FastAPI lifespan the same way the shared httpx client already does; Postgres is already the primary store; Recharts is the industry-standard React chart library that matches the Radix + Tailwind component language of the existing SPA.
- **Thin slice correctness**: the data model (minute buckets + 6 histogram bins) is exactly big enough for "p50/p95 over the last hour". Scaling to 7-day retention or 1-hour buckets is a schema addition, not a rewrite.

Option 2 was close. The raw-event schema is simpler and gives exact percentiles. But the growth curve becomes a problem the moment the project sees real traffic, and keeping prometheus-client out means a later `/metrics` scrape endpoint needs a parallel instrumentation layer. The chosen option gets both the bounded table and the scrape-ready registry.

Option 3 is the right answer at scale; it's the wrong answer at Skateboard tier. The infrastructure cost is paid before any value is delivered. Nothing in Option 1 prevents a later move to Option 3: the same instruments feed either path.

Option 4 is Option 1 plus a surface no one needs yet. The Follow-up list captures it, so turning it on later is a one-task change, not a redesign.

**On the chosen defaults** (the RECOMMEND items in the design conversation):

- **Histogram bins at 0.05 / 0.1 / 0.25 / 0.5 / 1 / 5 seconds**: covers typical web request latencies at useful resolution with six columns. Faster traffic (<50 ms) collapses into the first bin, which is honest; slower traffic (>5 s) is already a problem the operator wants to see.
- **Flush every 15 seconds**: four writes per minute per unique label set is low write pressure. Smaller intervals risk hammering Postgres; larger intervals delay signal.
- **7-day retention**: enough history for a Monday morning "did Friday's deploy regress anything" check; not so much that the table balloons. Env-tunable up to 90 days.
- **15-minute buffer cap**: long enough to ride through a routine Postgres restart or a brief network blip; short enough that memory stays bounded at a handful of MB per worker.
- **Linear interpolation inside the matching bin**: the standard Prometheus-style approximation; good enough for operator dashboards; stops short of claims about `p99.9`.
- **No feature flag**: a subsystem that only runs in production drifts. In-process collection is cheap enough to always run; the dashboard is admin-gated.

**On the scope row's throttling counter**: the row names "per-domain throttling" but no throttle feature exists yet. The chosen approach is to scaffold the counter (`throttle_events_total` with a `website_host` label) so a future throttle feature just bumps it; this keeps the dashboard panel inventory honest about what the data layer promises.

## References

No References section: the engineer opted for `No references, keep it clean` in the References consent panel. The reasoning above stands on the project context and standard practice; readers can look up `prometheus-client`, Recharts, and `percentile_cont` by name.
