# 0009. Workflow configuration screens — Rationale

## Context

Spec 0008 shipped the admin UI shell: a React 19 single page app under `frontend/` with TanStack Router + Query, Zustand, React Hook Form + Zod, shadcn/ui, Tailwind 4, Vite, strict TypeScript, and `openapi-typescript`-generated types. It landed one real list screen (`/websites`), placeholders for `/targets`, `/workflows`, and `/executions`, auth via API key, and a shared `apiFetch` wrapper that parses Problem Details into `ApiError` and maps 422 `errors[].loc` entries to React Hook Form `setError`.

The backend already exposes everything this feature needs. Spec 0002 defines websites and nested target URLs with full CRUD. Spec 0004 defines workflows and their immutable, versioned configurations, with draft / published / archived lifecycle, atomic publish-with-auto-archive, and the full set of lifecycle refusal codes (`workflow.has_in_flight_executions`, `workflow.version_conflict`, `workflow.version_is_current`, `workflow.version_not_draft`, `workflow.version_not_published`, `workflow.inactive`). Spec 0005 defines the Preview endpoint on a version against a target URL with structured fetch and extraction error codes.

What is missing is the operator surface: the scope row for Feature 10 says `done when a user can create a workflow end-to-end from the UI and run a preview that returns the extracted sample`. Without this feature, an operator has to use curl to set up a scrape; with it, Slice 2 is complete and Feature 11 (Execution browser) can land on the same shell.

The forces at play:
- The shell is already decided. This spec builds on it; it does not re-decide the stack.
- The backend is already decided. This spec consumes specs 0002, 0004, 0005 verbatim; no new endpoint is added.
- Spec 0004 AC-9 pins full-config PATCH on drafts (not merge). The editor save model must honor that or create a semantic mismatch.
- Spec 0004's lifecycle has three load-bearing 409 refusals (`version_conflict`, `version_is_current`, `has_in_flight_executions`) that must each have a specific UI remediation, not a generic error.
- The workflow version config is a mostly-structured JSON document (`container_selector`, `fields[]`, `output_schema`, optional `pagination`) with `output_schema` free-form enough that a fully structured editor would lock operators out of valid configs.
- The feature spans five screen areas (Websites, Targets, Workflows, Versions, Preview). Done naively, that is five independent patterns; done well, it establishes the shell conventions Feature 11 reuses.

## Options considered

### Option 1: Single-spec, five-area build on the existing shell (chosen)

One spec covering Websites CRUD + Targets CRUD + Workflows CRUD + Versions (list + lifecycle) + Preview, inside the shell shipped by spec 0008. Lists share one URL-synced search param pattern. Create and edit happen in shadcn Sheets off the list. Destructive deletes on Websites and Workflows require typing the name in an AlertDialog; destructive deletes on Targets and draft Versions use a plain confirm. The workflow detail is a tabbed nested route (`Overview | Versions | Preview`). The version editor is a sub-route at `/workflows/:id/versions/:vid` with a split layout: structured form on the left (container_selector + repeatable fields rows + two CodeMirror JSON panes), Preview panel on the right. Save is full-config PATCH; dirty state gates both navigation (via `useBlocker`) and Preview (so operators never preview stale state). Non-draft versions render read-only.

**Pros**:
- One spec matches the scope row's `done when` end-to-end definition; no partial Slice 2 to reconcile later.
- Establishes shell conventions (list / Sheet / detail-tabs / split-editor / Problem Details rendering) that Feature 11 and later admin screens reuse.
- Full-config PATCH mirrors spec 0004 AC-9 exactly; no new semantic edge case to debug.
- The split-pane editor keeps the edit-preview-publish loop on one screen.
- Dirty-gated Preview prevents the "I previewed and it works, why does it fail live" class of confusion.

**Cons**:
- A sizable spec (six milestones, 20 ACs). Review and build take longer than a thin skateboard.
- The `/workflows` list has to stitch results client-side when no `website_id` filter is set, because spec 0004 only exposes nested list; a workaround until a top-level list endpoint lands.
- The structured + raw-JSON hybrid editor is a two-mode UX; some operators will miss that `output_schema` is JSON.

### Option 2: Umbrella spec with child specs per area

A directory spec with three child specs: registration (Websites + Targets), workflow authoring (Workflows + Versions + Editor + Lifecycle), and preview. Each child a buildable chunk with its own acceptance criteria and build plan.

**Pros**:
- Each area can be reviewed and shipped independently; smaller cognitive load per PR.
- Mirrors the "umbrella + children" shape already in use for data model (spec 0003) and some larger decisions.

**Cons**:
- The five areas are tightly coupled: the editor needs a workflow which needs a website; preview needs a target URL under the workflow's website. Independent sign-off is less of a win than it looks.
- Three specs' overhead (three Contexts, three Options sections, three cross-references to specs 0002, 0004, 0005) with no decision diversity to justify the split.
- Loses the single "shell convention established here" story; three specs each establish a slice of it.

### Option 3: Minimum skateboard — Workflows + one draft + Preview only

Build only the Workflows list, workflow create/edit/delete, a single-draft-version editor, and Preview. Keep Websites/Targets screens as read-only. Operators would continue to register websites and targets via curl.

**Pros**:
- Smallest shippable; fastest to the preview loop.
- Defers Website / Target CRUD UX decisions until a user actually asks for them.

**Cons**:
- Breaks the scope row's intent (`register websites and targets, create and edit workflow versions, and preview`). Requires curl for a basic setup flow, which contradicts spec 0008's "the backend data is really there" user story.
- No lifecycle actions on versions (publish, archive) means the "end-to-end" story stops at a draft; the operator can preview but never publishes, and the backend's `current_version_id` story stays uninspected.
- Postpones establishing the Sheet / Detail / Lifecycle conventions that Feature 11 reuses, so Feature 11 would re-decide them.

### Option 4: Full-structured editor (no raw JSON escape hatch)

Build a fully structured form for every part of `WorkflowConfig`, including a dedicated UI for `output_schema` (property name, type, required toggle, nested properties).

**Pros**:
- Nicest UX for non-technical operators.
- No JSON editing anywhere; no risk of a syntactically-invalid config.

**Cons**:
- `output_schema` is JSON Schema draft 2020-12 per spec 0005. Full-coverage UI for arbitrary JSON Schema is a product in itself (nested properties, `oneOf`, `allOf`, `patternProperties`, …) and risks locking out valid schemas the backend accepts.
- Doubles the editor build cost for a Beta slice.
- Still needs a JSON escape hatch for `pagination` extras (spec allows `extra='allow'`). Half the complexity for all the limitation.

## Rationale

Option 1 is the recommended build because the scope row is explicit about end-to-end (`a user can create a workflow end-to-end from the UI and run a preview`), the backend endpoints are already in place, and the shell conventions established here are a one-time cost that Feature 11 and later admin screens all reuse.

Option 2 (umbrella) was rejected because the five areas are tightly coupled through the editor's data flow: an editor needs a workflow, which needs a website, which needs targets for Preview. Splitting into child specs would spread one coherent build across three documents without decision diversity to justify it; each child would read mostly like a cross-reference to the others.

Option 3 (skateboard) was rejected because it leaves half the scope row intent unmet (Websites / Targets CRUD) and would re-introduce the "touch curl to set up a scrape" friction that spec 0008 explicitly moved away from. The feature size concern it addresses is real but is better handled by milestones inside Option 1 (six shippable states, not one big-bang PR) than by cutting the feature.

Option 4 (full-structured) was rejected on operational grounds. `output_schema` is JSON Schema and must stay JSON Schema; a bespoke form over it is a mini product that would either lock out valid schemas or sprawl into a general JSON Schema editor. The hybrid (structured form for the known parts, CodeMirror for the free-form parts) matches the actual shape of the data: `container_selector` and `fields[]` are structured, `output_schema` and `pagination` are declarative JSON. The two-mode UX cost is mitigated by inline guidance text and client-side coverage warnings; it is a smaller cost than the "editor cannot save my valid schema" bug class.

Within Option 1, the two load-bearing sub-decisions were:

- **Save model: explicit Save with full-config PATCH, dirty indicator, discard confirm.** Mirrors spec 0004 AC-9 exactly, so no merge semantics to invent; keeps the operator in control; and makes dirty-gating Preview trivial (the gate is the RHF `dirty` flag). Auto-save was rejected because it would race with the backend's one-shot retry on `version_conflict` during publish and would hide the "did my change land?" moment the operator needs. Local-only edits until Publish was rejected because a browser refresh would discard in-progress work.

- **Preview inside the editor, not a separate route.** The edit → save → preview → iterate loop is the whole value of this feature; a separate route would double the navigation and encourage a stale-config-in-another-tab anti-pattern. A standalone deep-linkable preview URL is deferred to Follow-up; nobody asked for one in the interview.

- **CodeMirror 6 over Monaco for the JSON pane.** ~100 KB gzipped vs ~2 MB, actively maintained, good JSON highlighting and linting, works well in split panels. Monaco's richer autocomplete is overkill for a `WorkflowConfig` document. A plain textarea was rejected because the operator will be editing JSON frequently enough that bracket matching and highlighting pay for themselves.

- **Destructive-delete UX: type-to-confirm for Websites and Workflows, plain confirm for Targets and draft Versions.** Soft delete is non-reversible via the API (specs 0002 and 0004), and a deleted website cascades to its targets. Type-to-confirm matches the blast radius; draft versions are hard-deletable and low-stakes.

- **Workflow detail as tabbed nested routes.** Keeps the URL honest (`/workflows/:id/overview` vs `/workflows/:id/versions`), lets a browser back take the operator back to the previous tab, and gives TanStack Router a clean place to put per-tab search params.

Spec 0004 Follow-up explicitly asked this spec to call out that draft config editing is full-replace, not merge. That is honored at AC-11 and AC-12, and in the editor's build task (milestone 5).
