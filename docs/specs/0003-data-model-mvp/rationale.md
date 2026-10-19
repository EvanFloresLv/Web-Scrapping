# 0003. Data model (MVP entities) — Rationale

Decision record for spec [0003](index.md). Read this when you want the why; `/develop` reads only `index.md`.

## Context

Spec [0001](../0001-stack-and-architecture/index.md) settled the stack and the module layout but deliberately left the data shape of every domain to the slice features that would own them. Spec [0002](../0002-website-target-registration.md) then designed `websites` and `target_urls` in full as the first real domain. The remaining MVP entities (`scraping_workflows`, `workflow_versions`, `executions`, `execution_results`) are the shape every other slice depends on: slice 1 (features 5, 6, 7) reads and writes all four, slice 2 (features 10, 11) builds the admin UI on top of them, slice 3 (features 12, 13) instruments them, and slice 5 (feature 18) joins back into `execution_results` for product provenance. If each slice invented its own shape as it designed, the first spec to land would set the shape and every later spec would either copy it or supersede it. Scope feature 3's `Done when` captures this exact risk: "entities and relationships support slices 1 through 3 without a breaking migration."

Four forces shape the decision:

1. **Design once, build many.** Settling the shape of a workflow, a version, and an execution in one spec means the next three slice design conversations are pure service and router walks. The alternative (each slice re litigates the model) multiplies interview cost and risks drift.
2. **History must stay joinable.** Executions and their results are the raw material for provenance (feature 18), the operational dashboard (feature 13), and the execution browser (feature 11). A design that lets a parent delete remove history makes those features impossible without a soft delete graveyard the queries have to remember.
3. **Workflow versions are the thing that runs, not the workflow.** A workflow "my product detail scraper" is a stable name; what actually runs against a page is a specific, immutable configuration. Conflating them (one row, mutable config) means every execution's provenance links to the current state of the config, not the state that produced the result; a bug fix to the config retroactively "changes" every past execution's lineage.
4. **The config is read whole, written whole.** A `workflow_versions.config` is read exactly once per execution (by the extractor) and written exactly once per version. Nothing joins into individual rules; the admin UI edits a config as a whole document. A row per rule serves no read path and costs a join on every execution.

The scope row explicitly lists seven entities (Website, TargetURL, ScrapingWorkflow, WorkflowVersion, ExtractionRule, Execution, ExecutionResult). This spec collapses ExtractionRule into `workflow_versions.config` (force 4) and references spec 0002 for the first two, leaving four tables to design here.

## Options considered

### Option 1: Umbrella data model spec that pins every MVP entity as a cohesive target; each slice ships its own migration (chosen)

One spec specifies every MVP table (new or already specified by [0002](../0002-website-target-registration.md) by reference), with its columns, indexes, FKs, and lifecycle. Slice features (5, 6, 7) build their migrations against the pinned shape and may not change it without superseding this spec. Spec 0002 continues to own `websites` and `target_urls`; feature 5 owns the migration for `scraping_workflows` and `workflow_versions`; feature 7 owns the migration for `executions` and `execution_results`.

**Pros**
- Design conversation for each slice shrinks to "what endpoints does this slice add" because the model is already settled.
- Each slice migration remains independently revertible, which keeps the Skateboard delivery discipline the project chose.
- `/develop` for later slices reads one small focused spec plus this one, not a growing union of shape fragments.

**Cons**
- Front loads design before any slice build has exposed a real pain point. Mitigated because the shape of a scraping workflow and an execution record is well understood from the legacy ADK agent reference and from how scraper platforms typically model this.
- An unforeseen slice requirement (e.g. feature 15's prompt versioning wanting to piggyback on `workflow_versions`) forces a supersede rather than an in slice adjustment. Acceptable: supersede is cheap when the only consumers are two slice specs.

### Option 2: Narrow data model spec (only entities no slice feature owns)

This spec would specify only `extraction_rules` (and maybe the audit convention) and defer `scraping_workflows`, `workflow_versions`, `executions`, `execution_results` into their respective slice specs. Feature 5 would design workflow and version; feature 7 would design execution and result.

**Pros**
- Each slice owns the shape it uses; no cross spec coupling to coordinate.
- Smaller scope for feature 3 itself.

**Cons**
- Features 5 and 7 would each have to design cross cutting concerns (audit, FK policy, cascade semantics) independently; they would almost certainly diverge. The ADR history would then look like two half specs that have to be reconciled by a third.
- The scope row's `Done when` ("support slices 1 through 3 without a breaking migration") can only be guaranteed by a coherent view of all tables at once. A piecemeal design cannot promise that.
- Spec 0002's own Follow-up explicitly asks this spec to "either (a) become an umbrella that references this spec for those two tables, or (b) narrow its scope." Option 2 is the (b) path and the engineer picked (a).

### Option 3: Umbrella split into child specs (0003a workflows, 0003b executions)

A directory with the umbrella `index.md` listing children, plus `0003-workflows.md` for the workflow shape and `0003-executions.md` for the execution shape, each a self sufficient child spec.

**Pros**
- Maps 1:1 to the two migrations that will ship (one per slice), so each slice has one child spec to read.
- Easier to supersede one half without touching the other.

**Cons**
- The MVP data model is one cohesive decision, not two independent sub decisions. The lifecycle, FK policy, audit convention, and cascade behavior apply to all four tables uniformly; splitting them pretends they are independent.
- Two files to maintain where one serves. The structure buys optionality that is unlikely to be exercised (one half is far more likely to grow new columns than to be superseded wholesale).
- Adds a `## Structure` manifest and child spec plumbing for no information gain.

## Rationale

Option 1 wins because the four forces in Context pull the same way. Force 1 (design once, build many) is only served by one spec that fully pins the shape; Options 2 and 3 both leave gaps that the next slice has to fill. Force 2 (history must stay joinable) is a cross cutting policy (RESTRICT on FKs, CASCADE only from execution to its results, soft delete only on the mutable aggregate root); pinning it in one place is how it stays uniform. Force 3 (version is what runs) is why `scraping_workflows` and `workflow_versions` are split, and the `current_version_id` pointer is a single FK lookup rather than a derived `MAX(version_number) WHERE status='published'` (which costs an aggregate on the hottest read path and makes the "which version is live" question a scan instead of a lookup). Force 4 (config is read whole, written whole) is why extraction rules are embedded in JSONB rather than normalized into their own table.

The chosen migration strategy ("one migration per entity cluster, shipped with its slice") is a deliberate trade: this spec gives up the "one atomic migration" guarantee the scope row originally envisioned, in exchange for keeping each slice independently revertible (a core Skateboard property). The `Done when` revision in Follow-up names this trade explicitly so a future reader does not try to reconcile the two phrasings.

The `executions.status='pending'` state is kept even though feature 7's sync executor will never leave an execution in it. Removing it would force a schema migration when feature 23 (async queue) lands. Carrying one unused enum value through MVP is strictly cheaper than migrating later.

Soft delete on `scraping_workflows` extends the pattern [0002](../0002-website-target-registration.md) added to `target_urls`. Spec 0001 pinned soft delete on `websites` and `workflows` (not `target_urls`); 0002 added `target_urls`; this spec now extends it formally. The convention is "soft delete on mutable catalog aggregates, immutable append only tables for history." That one line should land in 0001 at the next `/sync` run (noted in Follow-up).

The decision explicitly out of scope: products, embeddings, retention, authn/authz. The products entity is scope feature 18 (slice 5), out of MVP. Retention needs a window size the project has not scoped. Authn/authz is slice 11. Mentioning them in Consequences keeps future readers from assuming this spec forgot about them.
