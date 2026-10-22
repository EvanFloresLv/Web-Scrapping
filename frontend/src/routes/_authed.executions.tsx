import { useQueries, useQuery } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { z } from 'zod'

import { queryKeys } from '@/api/queryKeys'
import type { components } from '@/api/schema'
import { DataTable, type DataTableColumn } from '@/components/data-table'
import { EmptyState } from '@/components/empty-state'
import { FilterBar, FilterField, ResetFiltersButton } from '@/components/filter-bar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { type ApiError, apiFetch } from '@/lib/api'

/**
 * Executions browser list route (spec 0010 M3, M4).
 *
 * Cursor pagination (spec 0010 AC-2) instead of offset: forward only, so
 * the toolbar only shows Next (and a cursor-aware "earlier page" bookmark
 * is the operator's hand to roll back). URL-synced search params parsed
 * via Zod (AC-7) fall back to defaults on invalid input.
 */

type ExecutionListResponse = components['schemas']['ExecutionListResponse']
type ExecutionListItem = components['schemas']['ExecutionListItem']
type WorkflowRead = components['schemas']['WorkflowRead']
type WebsiteRead = components['schemas']['WebsiteRead']
type TargetRead = components['schemas']['TargetRead']

const statusOptions = ['pending', 'running', 'completed', 'failed'] as const
type ExecutionStatus = (typeof statusOptions)[number]

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const
type PageSize = (typeof PAGE_SIZE_OPTIONS)[number]

/** URL params for the executions list (spec 0010 AC-3, AC-7). */
const executionsSearchSchema = z.object({
  cursor: z.string().optional().catch(undefined),
  page_size: z
    .union([z.literal(25), z.literal(50), z.literal(100)])
    .catch(50 as PageSize)
    .default(50 as PageSize),
  status: z
    .union(statusOptions.map((s) => z.literal(s)) as never)
    .optional()
    .catch(undefined) as z.ZodType<ExecutionStatus | undefined>,
  workflow_id: z.string().uuid().optional().catch(undefined),
  target_url_id: z.string().uuid().optional().catch(undefined),
  website_id: z.string().uuid().optional().catch(undefined),
  correlation_id: z.string().min(1).optional().catch(undefined),
  created_from: z.string().optional().catch(undefined),
  created_to: z.string().optional().catch(undefined),
  with_deleted: z
    .union([
      z.literal(true),
      z.literal(false),
      z.literal('true').transform(() => true),
      z.literal('false').transform(() => false),
    ])
    .catch(false)
    .default(false),
})

type ExecutionsSearch = z.infer<typeof executionsSearchSchema>

const EXECUTIONS_DEFAULTS: ExecutionsSearch = {
  cursor: undefined,
  page_size: 50,
  status: undefined,
  workflow_id: undefined,
  target_url_id: undefined,
  website_id: undefined,
  correlation_id: undefined,
  created_from: undefined,
  created_to: undefined,
  with_deleted: false,
}

function toQueryString(filters: ExecutionsSearch): string {
  const params = new URLSearchParams()
  params.set('page_size', String(filters.page_size))
  if (filters.cursor) params.set('cursor', filters.cursor)
  if (filters.status) params.set('status', filters.status)
  if (filters.workflow_id) params.set('workflow_id', filters.workflow_id)
  if (filters.target_url_id) params.set('target_url_id', filters.target_url_id)
  if (filters.website_id) params.set('website_id', filters.website_id)
  if (filters.correlation_id) params.set('correlation_id', filters.correlation_id)
  if (filters.created_from) params.set('created_from', filters.created_from)
  if (filters.created_to) params.set('created_to', filters.created_to)
  if (filters.with_deleted) params.set('with_deleted', 'true')
  return params.toString()
}

export const Route = createFileRoute('/_authed/executions')({
  validateSearch: (search) => executionsSearchSchema.parse(search),
  component: ExecutionsPage,
})

function ExecutionsPage() {
  const filters = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })

  const update = (next: Partial<ExecutionsSearch>) => {
    // Any filter change resets the cursor (we jump to the newest page).
    const changedFilter = Object.keys(next).some((k) => k !== 'cursor' && k !== 'page_size')
    navigate({
      search: (prev) => ({
        ...prev,
        ...next,
        ...(changedFilter ? { cursor: undefined } : {}),
      }),
    })
  }

  const list = useQuery<ExecutionListResponse, ApiError>({
    queryKey: queryKeys.executions.list(filters),
    queryFn: ({ signal }) =>
      apiFetch<ExecutionListResponse>(`/api/v1/executions?${toQueryString(filters)}`, {
        signal,
      }),
    // Spec 0010 AC-10: auto refresh only while an in-flight row is visible.
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      return items.some((r) => r.status === 'pending' || r.status === 'running') ? 3000 : false
    },
  })

  const items = list.data?.items ?? []

  // Spec 0010 AC-8: resolve each row's parent workflow name via a batched
  // `useQueries` fan-out over the unique workflow_ids on the page. Cached
  // workflow rows (from a prior visit to /workflows) are reused instantly.
  const uniqueWorkflowIds = Array.from(new Set(items.map((r) => r.workflow_id)))
  const workflowQueries = useQueries({
    queries: uniqueWorkflowIds.map((id) => ({
      queryKey: queryKeys.workflows.detail(id),
      queryFn: ({ signal }: { signal?: AbortSignal }) =>
        apiFetch<WorkflowRead>(`/api/v1/workflows/${id}`, { signal, silent: true }),
      staleTime: 60_000,
      retry: false,
    })),
  })
  const workflowById = new Map<string, WorkflowRead | undefined>()
  uniqueWorkflowIds.forEach((id, i) => {
    workflowById.set(id, workflowQueries[i]?.data)
  })

  const activeWebsites = useQuery<components['schemas']['PaginatedList_WebsiteRead_'], ApiError>({
    queryKey: queryKeys.websites.list({ status: 'active', page_size: 200 }),
    queryFn: ({ signal }) =>
      apiFetch(`/api/v1/websites?page=1&page_size=200&status=active`, { signal }),
    staleTime: 60_000,
  })

  // When a workflow filter is set, scope the target picker to that workflow's
  // active targets (spec 0010 AC-9). Load via the workflow's cached website_id.
  const scopedWorkflow = filters.workflow_id ? workflowById.get(filters.workflow_id) : undefined
  const scopedTargets = useQuery<components['schemas']['PaginatedList_TargetRead_'], ApiError>({
    queryKey: ['websites', scopedWorkflow?.website_id, 'targets', { status: 'active' }],
    queryFn: ({ signal }) =>
      apiFetch(
        `/api/v1/websites/${scopedWorkflow?.website_id}/targets?status=active&page_size=200`,
        { signal },
      ),
    enabled: !!scopedWorkflow?.website_id,
    staleTime: 60_000,
  })

  const columns: DataTableColumn<ExecutionListItem>[] = [
    {
      key: 'status',
      header: 'Status',
      cell: (row) => <StatusBadge status={row.status as ExecutionStatus} />,
    },
    {
      key: 'workflow',
      header: 'Workflow',
      cell: (row) => {
        const wf = workflowById.get(row.workflow_id)
        return (
          <Link
            to="/workflows/$workflowId/overview"
            params={{ workflowId: row.workflow_id }}
            className="text-sm font-medium text-primary hover:underline"
          >
            {wf?.name ?? (
              <span className="font-mono text-xs text-muted-foreground">
                {row.workflow_id.slice(0, 8)}…
              </span>
            )}
          </Link>
        )
      },
    },
    {
      key: 'items',
      header: 'Items',
      cell: (row) => <span className="tabular-nums text-sm">{row.items_extracted}</span>,
    },
    {
      key: 'duration',
      header: 'Duration',
      cell: (row) =>
        row.duration_ms == null ? (
          <span className="text-muted-foreground text-sm">—</span>
        ) : (
          <span className="tabular-nums text-sm">{row.duration_ms} ms</span>
        ),
    },
    {
      key: 'started',
      header: 'Started',
      cell: (row) =>
        row.started_at ? (
          <span className="text-sm text-muted-foreground">
            {new Date(row.started_at).toLocaleString()}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: 'open',
      header: '',
      className: 'w-16 text-right',
      cell: (row) => (
        <Link
          to={`/executions/${row.id}` as never}
          className="text-sm text-primary hover:underline"
        >
          Open
        </Link>
      ),
    },
  ]

  const emptyFilterCount =
    (filters.status ? 1 : 0) +
    (filters.workflow_id ? 1 : 0) +
    (filters.target_url_id ? 1 : 0) +
    (filters.website_id ? 1 : 0) +
    (filters.correlation_id ? 1 : 0) +
    (filters.created_from ? 1 : 0) +
    (filters.created_to ? 1 : 0) +
    (filters.with_deleted ? 1 : 0)

  const empty = (
    <EmptyState
      title={emptyFilterCount > 0 ? 'No executions match these filters.' : 'No executions yet.'}
      description={
        emptyFilterCount > 0
          ? 'Clear the filters to see every run, or widen the time window.'
          : 'Run a workflow (POST /api/v1/workflows/{id}/execute) and this list fills up.'
      }
      action={
        emptyFilterCount > 0
          ? {
              label: 'Reset filters',
              onClick: () => navigate({ search: EXECUTIONS_DEFAULTS }),
            }
          : undefined
      }
    />
  )

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Executions</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every past run of every workflow, newest first.
          </p>
        </div>
      </header>

      <FilterBar
        actions={<ResetFiltersButton onReset={() => navigate({ search: EXECUTIONS_DEFAULTS })} />}
      >
        <FilterField label="Workflow" htmlFor="workflow-filter">
          <select
            id="workflow-filter"
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            value={filters.workflow_id ?? ''}
            onChange={(e) =>
              update({
                workflow_id: e.target.value || undefined,
                target_url_id: undefined,
              })
            }
          >
            <option value="">All workflows</option>
            {/*
             * Workflow combobox: for M3 we populate from the active websites
             * list plus any workflow already in the current page's cache,
             * since there is no `/api/v1/workflows` top level list endpoint
             * (spec 0009 Follow-up). Operators pick an id from the browser's
             * URL today; a full picker lands when the top level list exists.
             */}
            {Array.from(workflowById.entries())
              .filter(([, w]) => !!w)
              .map(([id, w]) => (
                <option key={id} value={id}>
                  {w!.name}
                </option>
              ))}
          </select>
        </FilterField>

        <FilterField label="Status" htmlFor="status-filter">
          <select
            id="status-filter"
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            value={filters.status ?? ''}
            onChange={(e) =>
              update({ status: (e.target.value || undefined) as ExecutionStatus | undefined })
            }
          >
            <option value="">All</option>
            {statusOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </FilterField>

        <FilterField label="Target" htmlFor="target-filter">
          <select
            id="target-filter"
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            value={filters.target_url_id ?? ''}
            onChange={(e) => update({ target_url_id: e.target.value || undefined })}
            disabled={!filters.workflow_id}
          >
            <option value="">
              {filters.workflow_id ? 'All targets' : 'Pick a workflow first'}
            </option>
            {(scopedTargets.data?.items ?? []).map((t: TargetRead) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </FilterField>

        <FilterField label="Website" htmlFor="website-filter">
          <select
            id="website-filter"
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            value={filters.website_id ?? ''}
            onChange={(e) => update({ website_id: e.target.value || undefined })}
          >
            <option value="">All websites</option>
            {(activeWebsites.data?.items ?? []).map((w: WebsiteRead) => (
              <option key={w.id} value={w.id}>
                {w.display_name}
              </option>
            ))}
          </select>
        </FilterField>

        <FilterField label="Correlation id" htmlFor="correlation-filter">
          <Input
            id="correlation-filter"
            placeholder="paste a correlation id"
            value={filters.correlation_id ?? ''}
            onChange={(e) => update({ correlation_id: e.target.value || undefined })}
            className="h-9 w-56"
          />
        </FilterField>

        <FilterField label="From" htmlFor="from-filter">
          <Input
            id="from-filter"
            type="datetime-local"
            value={toLocalInputValue(filters.created_from)}
            onChange={(e) => update({ created_from: fromLocalInput(e.target.value) })}
            className="h-9"
          />
        </FilterField>

        <FilterField label="To" htmlFor="to-filter">
          <Input
            id="to-filter"
            type="datetime-local"
            value={toLocalInputValue(filters.created_to)}
            onChange={(e) => update({ created_to: fromLocalInput(e.target.value) })}
            className="h-9"
          />
        </FilterField>

        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-input"
            checked={filters.with_deleted}
            onChange={(e) => update({ with_deleted: e.target.checked })}
          />
          Include deleted
        </label>
      </FilterBar>

      {list.isError ? (
        <div
          className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
          role="alert"
        >
          <strong>{list.error.title ?? 'Failed to load'}:</strong>{' '}
          {list.error.detail ?? list.error.message}
          {list.error.correlationId ? (
            <span className="ml-2 text-xs opacity-80">
              (correlation {list.error.correlationId})
            </span>
          ) : null}
        </div>
      ) : null}

      <DataTable
        columns={columns}
        rows={items}
        rowKey={(r) => r.id}
        isLoading={list.isLoading}
        isError={list.isError}
        errorMessage={list.error?.detail ?? undefined}
        empty={empty}
      />

      <CursorPaginationBar
        pageSize={filters.page_size}
        hasPrev={!!filters.cursor}
        nextCursor={list.data?.next_cursor ?? null}
        onNext={(cursor) => update({ cursor })}
        onReset={() => update({ cursor: undefined })}
        onPageSize={(page_size) => update({ page_size, cursor: undefined })}
      />
    </div>
  )
}

function StatusBadge({ status }: { status: ExecutionStatus }) {
  const styles: Record<ExecutionStatus, string> = {
    pending: 'bg-muted text-muted-foreground',
    running: 'bg-blue-500/15 text-blue-900 dark:text-blue-200',
    completed: 'bg-green-500/15 text-green-900 dark:text-green-200',
    failed: 'bg-destructive/15 text-destructive',
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles[status]}`}
    >
      {status}
    </span>
  )
}

function CursorPaginationBar({
  pageSize,
  hasPrev,
  nextCursor,
  onNext,
  onReset,
  onPageSize,
}: {
  pageSize: PageSize
  hasPrev: boolean
  nextCursor: string | null
  onNext: (cursor: string) => void
  onReset: () => void
  onPageSize: (next: PageSize) => void
}) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <p className="text-muted-foreground">
        Cursor pagination: forward only. Bookmark the URL to come back later.
      </p>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-muted-foreground">
          <span>Rows</span>
          <select
            className="h-8 rounded-md border border-input bg-background px-2 text-sm"
            value={pageSize}
            onChange={(e) => onPageSize(Number(e.target.value) as PageSize)}
          >
            {PAGE_SIZE_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <Button variant="outline" size="sm" onClick={onReset} disabled={!hasPrev}>
          Newest page
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => nextCursor && onNext(nextCursor)}
          disabled={!nextCursor}
        >
          Next
        </Button>
      </div>
    </div>
  )
}

function toLocalInputValue(iso: string | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fromLocalInput(local: string): string | undefined {
  if (!local) return undefined
  // Interpret as the operator's local time; the backend accepts ISO-8601
  // and treats a missing offset as the local one anyway.
  return new Date(local).toISOString()
}
