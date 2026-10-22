import { json as cmJson } from '@codemirror/lang-json'
import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import CodeMirror from '@uiw/react-codemirror'
import { ChevronDown, ChevronRight, Copy } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { queryKeys } from '@/api/queryKeys'
import type { components } from '@/api/schema'
import { EmptyState } from '@/components/empty-state'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { type ApiError, apiFetch } from '@/lib/api'

/**
 * Execution detail route (spec 0010 M5, AC-11, AC-12, AC-13).
 *
 * Three sections: a header (status + timings + correlation id), a metadata
 * grid with cross links to workflow / website / target, and the error block
 * when status is failed. Below those, an items Table / Raw JSON tabs with
 * Copy JSON, and a collapsed Config pane (CodeMirror read only) backed by
 * the WorkflowVersion GET.
 */

type ExecutionResponse = components['schemas']['ExecutionResponse']
type ExecutionBody = components['schemas']['ExecutionBody']
type WorkflowRead = components['schemas']['WorkflowRead']
type WorkflowVersionRead = components['schemas']['WorkflowVersionRead']
type ExecutionItem = components['schemas']['ExecutionItem']

export const Route = createFileRoute('/_authed/executions_/$executionId')({
  validateSearch: () => ({}),
  component: ExecutionDetailPage,
})

function ExecutionDetailPage() {
  const { executionId } = Route.useParams()
  const navigate = useNavigate()

  const detail = useQuery<ExecutionResponse, ApiError>({
    queryKey: queryKeys.executions.detail(executionId),
    queryFn: ({ signal }) =>
      apiFetch<ExecutionResponse>(`/api/v1/executions/${executionId}`, { signal }),
    refetchInterval: (query) => {
      const status = query.state.data?.execution.status
      return status === 'pending' || status === 'running' ? 3000 : false
    },
  })

  const execution = detail.data?.execution
  const items = detail.data?.items ?? []

  const workflow = useQuery<WorkflowRead, ApiError>({
    queryKey: execution ? queryKeys.workflows.detail(execution.workflow_id) : ['workflows', 'none'],
    queryFn: ({ signal }) =>
      apiFetch<WorkflowRead>(`/api/v1/workflows/${execution!.workflow_id}`, {
        signal,
        silent: true,
      }),
    enabled: !!execution,
    staleTime: 60_000,
    retry: false,
  })

  if (detail.isError) {
    const notFound = detail.error.status === 404
    return (
      <div className="p-6">
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            navigate({
              to: '/executions',
              search: {
                page_size: 50,
                status: undefined,
                with_deleted: false,
                cursor: undefined,
                workflow_id: undefined,
                target_url_id: undefined,
                website_id: undefined,
                correlation_id: undefined,
                created_from: undefined,
                created_to: undefined,
              },
            })
          }
        >
          ← Back to executions
        </Button>
        <div
          className="mt-4 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
          role="alert"
        >
          <strong>{detail.error.title ?? 'Failed to load'}:</strong>{' '}
          {detail.error.detail ?? detail.error.message}
          {detail.error.correlationId ? (
            <span className="ml-2 text-xs opacity-80">
              (correlation {detail.error.correlationId})
            </span>
          ) : null}
          {notFound ? <p className="mt-1">The execution may have been removed.</p> : null}
        </div>
      </div>
    )
  }

  if (!execution) {
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <nav>
        <Link
          to="/executions"
          search={{
            page_size: 50,
            status: undefined,
            with_deleted: false,
            cursor: undefined,
            workflow_id: undefined,
            target_url_id: undefined,
            website_id: undefined,
            correlation_id: undefined,
            created_from: undefined,
            created_to: undefined,
          }}
          className="text-sm text-muted-foreground hover:underline"
        >
          ← Back to executions
        </Link>
      </nav>

      <Header execution={execution} />

      <MetadataGrid execution={execution} workflow={workflow.data} />

      {execution.status === 'failed' ? <ErrorBlock execution={execution} /> : null}

      <ItemsSection execution={execution} items={items} />

      <ConfigPane workflowId={execution.workflow_id} versionId={execution.workflow_version_id} />
    </div>
  )
}

function Header({ execution }: { execution: ExecutionBody }) {
  const copyCorrelation = async () => {
    await navigator.clipboard.writeText(execution.correlation_id)
    toast.success('Correlation id copied.')
  }
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="flex items-center gap-3 text-2xl font-semibold">
          <StatusBadge status={execution.status} />
          <span className="font-mono text-base text-muted-foreground">
            {execution.id.slice(0, 8)}…
          </span>
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {execution.started_at ? (
            <>Started {new Date(execution.started_at).toLocaleString()}</>
          ) : (
            'Not started'
          )}
          {execution.finished_at ? (
            <>
              {' · Finished '}
              {new Date(execution.finished_at).toLocaleString()}
            </>
          ) : null}
          {execution.duration_ms != null ? <> · {execution.duration_ms} ms</> : null}
          {' · '}
          {execution.items_extracted} item{execution.items_extracted === 1 ? '' : 's'}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Link
          to="/metrics"
          search={{ workflow_id: execution.workflow_id }}
          className="rounded-md border px-3 py-1.5 text-xs font-medium text-primary hover:bg-accent"
        >
          View metrics
        </Link>
        <span className="text-xs text-muted-foreground">correlation</span>
        <code className="rounded-md border bg-muted px-2 py-1 font-mono text-xs">
          {execution.correlation_id}
        </code>
        <Button
          variant="outline"
          size="icon"
          onClick={copyCorrelation}
          aria-label="Copy correlation id"
        >
          <Copy className="h-4 w-4" />
        </Button>
      </div>
    </header>
  )
}

function MetadataGrid({
  execution,
  workflow,
}: {
  execution: ExecutionBody
  workflow: WorkflowRead | undefined
}) {
  return (
    <section className="grid grid-cols-1 gap-4 rounded-md border p-4 md:grid-cols-3">
      <Field label="Workflow">
        <Link
          to="/workflows/$workflowId/overview"
          params={{ workflowId: execution.workflow_id }}
          search={{}}
          className="text-sm text-primary hover:underline"
        >
          {workflow?.name ?? execution.workflow_id}
        </Link>
      </Field>
      <Field label="Website">
        {workflow?.website_id ? (
          <Link
            to="/websites/$websiteId"
            params={{ websiteId: workflow.website_id }}
            search={{ page: 1, page_size: 50, with_deleted: false }}
            className="text-sm text-primary hover:underline"
          >
            Open website
          </Link>
        ) : (
          <span className="text-sm text-muted-foreground">—</span>
        )}
      </Field>
      <Field label="Target URL id">
        <code className="font-mono text-xs text-muted-foreground">{execution.target_url_id}</code>
      </Field>
      <Field label="Version id">
        <code className="font-mono text-xs text-muted-foreground">
          {execution.workflow_version_id}
        </code>
      </Field>
      <Field label="Created">
        <span className="text-sm text-muted-foreground">
          {new Date(execution.created_at).toLocaleString()}
        </span>
      </Field>
    </section>
  )
}

function ErrorBlock({ execution }: { execution: ExecutionBody }) {
  return (
    <section className="rounded-md border border-destructive/40 bg-destructive/10 p-4" role="alert">
      <div className="flex items-center gap-2">
        <code className="rounded-md border border-destructive/40 bg-background px-2 py-0.5 font-mono text-xs text-destructive">
          {execution.error_code ?? 'error'}
        </code>
        <span className="text-sm font-semibold text-destructive">Run failed</span>
      </div>
      {execution.error_message ? (
        <p className="mt-2 text-sm text-destructive">{execution.error_message}</p>
      ) : null}
      <p className="mt-2 text-xs text-muted-foreground">
        Fuller error_details live in the structured logs keyed by correlation id (
        <code className="font-mono">{execution.correlation_id}</code>).
      </p>
    </section>
  )
}

function ItemsSection({ execution, items }: { execution: ExecutionBody; items: ExecutionItem[] }) {
  const [tab, setTab] = useState<'table' | 'json'>('table')
  const columnKeys = Array.from(
    new Set(items.flatMap((it) => Object.keys(it.payload as Record<string, unknown>))),
  )
  const copyJson = async () => {
    await navigator.clipboard.writeText(JSON.stringify(items, null, 2))
    toast.success('Items JSON copied.')
  }

  if (items.length === 0 && execution.status === 'completed') {
    return (
      <section>
        <h2 className="mb-2 text-lg font-semibold">Items</h2>
        <EmptyState
          title="No items extracted."
          description="The run completed but produced no rows. Check that the container selector matches the target page."
        />
      </section>
    )
  }
  if (items.length === 0) {
    return null
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Items ({items.length})</h2>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-md border">
            <button
              type="button"
              onClick={() => setTab('table')}
              className={`px-3 py-1 text-sm ${tab === 'table' ? 'bg-muted' : ''}`}
            >
              Table
            </button>
            <button
              type="button"
              onClick={() => setTab('json')}
              className={`px-3 py-1 text-sm ${tab === 'json' ? 'bg-muted' : ''}`}
            >
              Raw JSON
            </button>
          </div>
          <Button variant="outline" size="sm" onClick={copyJson}>
            <Copy className="mr-1 h-4 w-4" /> Copy JSON
          </Button>
        </div>
      </div>

      {tab === 'table' ? (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">#</TableHead>
                {columnKeys.map((key) => (
                  <TableHead key={key}>{key}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((it) => {
                const payload = it.payload as Record<string, unknown>
                return (
                  <TableRow key={it.item_index}>
                    <TableCell className="tabular-nums text-muted-foreground">
                      {it.item_index}
                    </TableCell>
                    {columnKeys.map((key) => (
                      <TableCell key={key} className="text-sm">
                        {renderCell(payload[key])}
                      </TableCell>
                    ))}
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      ) : (
        <CodeMirror
          value={JSON.stringify(items, null, 2)}
          height="320px"
          extensions={[cmJson()]}
          readOnly
          basicSetup={{ lineNumbers: true }}
        />
      )}
    </section>
  )
}

function ConfigPane({ workflowId, versionId }: { workflowId: string; versionId: string }) {
  const [open, setOpen] = useState(false)
  const version = useQuery<WorkflowVersionRead, ApiError>({
    queryKey: queryKeys.workflows.versions.detail(workflowId, versionId),
    queryFn: ({ signal }) =>
      apiFetch<WorkflowVersionRead>(`/api/v1/workflows/${workflowId}/versions/${versionId}`, {
        signal,
        silent: true,
      }),
    enabled: open,
    staleTime: 60_000,
    retry: false,
  })

  return (
    <section className="rounded-md border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 p-3 text-left text-sm hover:bg-muted/50"
      >
        <span className="flex items-center gap-2">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          <span className="font-semibold">Config that ran</span>
          {version.data ? (
            <span className="text-xs text-muted-foreground">
              v{version.data.version_number} · {version.data.status}
            </span>
          ) : null}
        </span>
      </button>
      {open ? (
        version.isLoading ? (
          <div className="p-3 text-sm text-muted-foreground">Loading…</div>
        ) : version.isError ? (
          <div className="p-3 text-sm text-destructive">
            Could not load the version: {version.error.detail ?? version.error.message}
          </div>
        ) : version.data ? (
          <div className="border-t">
            <CodeMirror
              value={JSON.stringify(version.data.config, null, 2)}
              height="280px"
              extensions={[cmJson()]}
              readOnly
              basicSetup={{ lineNumbers: true }}
            />
          </div>
        ) : null
      ) : null}
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <div className="mt-1">{children}</div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: 'bg-muted text-muted-foreground',
    running: 'bg-blue-500/15 text-blue-900 dark:text-blue-200',
    completed: 'bg-green-500/15 text-green-900 dark:text-green-200',
    failed: 'bg-destructive/15 text-destructive',
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-sm font-medium ${styles[status] ?? ''}`}
    >
      {status}
    </span>
  )
}

function renderCell(value: unknown): React.ReactNode {
  if (value == null) return <span className="text-muted-foreground">—</span>
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return <code className="font-mono text-xs">{JSON.stringify(value)}</code>
}
