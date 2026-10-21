import { json as cmJson } from '@codemirror/lang-json'
import { useQuery } from '@tanstack/react-query'
import CodeMirror from '@uiw/react-codemirror'
import { Copy, Play, StopCircle } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import { queryKeys } from '@/api/queryKeys'
import type { components } from '@/api/schema'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ApiError, apiFetch } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

type TargetRead = components['schemas']['TargetRead']
type ExtractionResult = components['schemas']['ExtractionResult']

type PaginatedTargets = {
  items: TargetRead[]
  total: number
  page: number
  page_size: number
}

/**
 * Preview panel (spec 0009 AC-17, AC-18).
 *
 * Lives inside the version editor's right pane. Loads active targets for the
 * workflow's parent website, lets the operator pick one, and runs the
 * backend preview with an `AbortController` wired to Cancel. Gated on a
 * clean form, a selected target, and no in-flight request. Renders results
 * as a Table (one row per item, columns from the version's
 * `output_schema.properties`), a raw-JSON tab (CodeMirror read only), and a
 * Copy JSON button. Error path renders Problem Details with Retry.
 */
export function PreviewPanel({
  workflowId,
  versionId,
  websiteId,
  outputSchemaText,
  isDirty,
}: {
  workflowId: string
  /** Undefined on `/versions/new` before First Save; preview is gated off. */
  versionId: string | undefined
  /** Undefined while the parent workflow is still loading. */
  websiteId: string | undefined
  outputSchemaText: string
  isDirty: boolean
}) {
  const [picked, setPicked] = useState<string>('')
  const [tab, setTab] = useState<'table' | 'json'>('table')
  const [status, setStatus] = useState<'idle' | 'running'>('idle')
  const [result, setResult] = useState<ExtractionResult | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const targetsQuery = useQuery<PaginatedTargets, ApiError>({
    queryKey: queryKeys.websites.targets.list(websiteId ?? '', {
      status: 'active',
      page: 1,
      page_size: 200,
    }),
    queryFn: ({ signal }) =>
      apiFetch<PaginatedTargets>(
        `/api/v1/websites/${websiteId}/targets?status=active&page=1&page_size=200`,
        { signal },
      ),
    enabled: Boolean(websiteId),
  })

  const columns = useMemo(() => {
    try {
      const parsed = JSON.parse(outputSchemaText || '{}') as {
        properties?: Record<string, unknown>
      }
      return Object.keys(parsed.properties ?? {})
    } catch {
      return []
    }
  }, [outputSchemaText])

  const canRun =
    Boolean(versionId) &&
    picked.length > 0 &&
    !isDirty &&
    status === 'idle' &&
    !targetsQuery.isPending

  const run = async () => {
    if (!versionId) return
    setError(null)
    setResult(null)
    setStatus('running')
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const { apiKey } = useAuthStore.getState()
      const response = await fetch(
        `/api/v1/workflows/${workflowId}/versions/${versionId}/preview`,
        {
          method: 'POST',
          signal: controller.signal,
          headers: {
            'content-type': 'application/json',
            ...(apiKey ? { 'X-API-Key': apiKey } : {}),
          },
          body: JSON.stringify({ target_url: picked }),
        },
      )
      if (!response.ok) {
        let problem: unknown
        try {
          problem = await response.json()
        } catch {
          problem = { title: 'Request failed', status: response.status }
        }
        const asRecord = (problem as Record<string, unknown>) ?? {}
        throw new ApiError({
          title: (asRecord.title as string) ?? 'Request failed',
          status: response.status,
          detail: asRecord.detail as string | undefined,
          code: asRecord.code as string | undefined,
          correlation_id: asRecord.correlation_id as string | undefined,
          errors: (asRecord.errors as never[]) ?? [],
        })
      }
      const data = (await response.json()) as ExtractionResult
      setResult(data)
      setTab('table')
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // Operator cancelled; stay idle without a toast.
      } else if (err instanceof ApiError) {
        setError(err)
      } else {
        toast.error(err instanceof Error ? err.message : 'Preview failed.')
      }
    } finally {
      abortRef.current = null
      setStatus('idle')
    }
  }

  const cancel = () => {
    abortRef.current?.abort()
  }

  const copyJson = async () => {
    if (!result) return
    try {
      await navigator.clipboard.writeText(JSON.stringify(result, null, 2))
      toast.success('Copied preview JSON to clipboard.')
    } catch {
      toast.error('Could not copy to clipboard.')
    }
  }

  const runDisabledReason = !versionId
    ? 'Save first to run a preview.'
    : isDirty
      ? 'Save first; Run preview sends the server stored config.'
      : picked.length === 0
        ? 'Pick a target first.'
        : undefined

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <div className="flex flex-col gap-2">
        <Label htmlFor="preview-target">Target</Label>
        <select
          id="preview-target"
          className="h-9 rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          value={picked}
          onChange={(e) => setPicked(e.target.value)}
          disabled={targetsQuery.isPending || !websiteId}
        >
          <option value="">
            {targetsQuery.isPending ? 'Loading targets…' : 'Pick an active target…'}
          </option>
          {(targetsQuery.data?.items ?? []).map((t) => (
            <option key={t.id} value={t.url}>
              {t.label} ({t.url})
            </option>
          ))}
        </select>
        {targetsQuery.data && targetsQuery.data.total > 200 ? (
          <p className="text-xs text-muted-foreground">
            Showing first 200 of {targetsQuery.data.total} active targets.
          </p>
        ) : null}
      </div>

      <div className="flex items-center gap-2">
        {status === 'running' ? (
          <Button type="button" variant="outline" onClick={cancel}>
            <StopCircle /> Cancel
          </Button>
        ) : (
          <Button
            type="button"
            onClick={run}
            disabled={!canRun}
            title={runDisabledReason}
            aria-label="Run preview"
          >
            <Play /> Run preview
          </Button>
        )}
      </div>

      {status === 'running' ? (
        <p className="text-sm text-muted-foreground">Running preview…</p>
      ) : null}

      {error ? (
        <div
          className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
          role="alert"
        >
          <p className="font-medium">
            {error.code ? <code className="mr-1">{error.code}</code> : null}
            {error.title}
          </p>
          {error.detail ? <p className="mt-1">{error.detail}</p> : null}
          {error.correlationId ? (
            <p className="mt-1 text-xs text-muted-foreground">correlation {error.correlationId}</p>
          ) : null}
          <div className="mt-2">
            <Button type="button" variant="outline" size="sm" onClick={run} disabled={!canRun}>
              Retry
            </Button>
          </div>
        </div>
      ) : null}

      {result ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex gap-1 rounded-md border p-0.5" role="tablist">
              <Button
                type="button"
                variant={tab === 'table' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setTab('table')}
                role="tab"
                aria-selected={tab === 'table'}
              >
                Table
              </Button>
              <Button
                type="button"
                variant={tab === 'json' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setTab('json')}
                role="tab"
                aria-selected={tab === 'json'}
              >
                Raw JSON
              </Button>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">
                {result.items_count} item{result.items_count === 1 ? '' : 's'} ·{' '}
                {result.duration_ms} ms
              </span>
              <Button type="button" variant="outline" size="sm" onClick={copyJson}>
                <Copy /> Copy JSON
              </Button>
            </div>
          </div>
          {result.status === 'failed' ? (
            <div
              className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
              role="alert"
            >
              <p className="font-medium">
                {result.error_code ? <code className="mr-1">{result.error_code}</code> : null}
                {result.error_message ?? 'Extraction failed.'}
              </p>
            </div>
          ) : null}
          {tab === 'table' ? (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    {columns.length > 0 ? (
                      columns.map((c) => <TableHead key={c}>{c}</TableHead>)
                    ) : (
                      <TableHead>value</TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(result.items ?? []).length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={Math.max(1, columns.length)}
                        className="py-4 text-center text-sm text-muted-foreground"
                      >
                        No items extracted.
                      </TableCell>
                    </TableRow>
                  ) : (
                    (result.items ?? []).map((item, idx) => (
                      // Preview rows have no stable id; the index is fine
                      // for a read only one shot table.
                      // biome-ignore lint/suspicious/noArrayIndexKey: see above
                      <TableRow key={idx}>
                        {columns.length > 0 ? (
                          columns.map((c) => <TableCell key={c}>{formatCell(item[c])}</TableCell>)
                        ) : (
                          <TableCell>{JSON.stringify(item)}</TableCell>
                        )}
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          ) : (
            <CodeMirror
              value={JSON.stringify(result, null, 2)}
              height="260px"
              extensions={[cmJson()]}
              readOnly
              basicSetup={{ lineNumbers: true }}
            />
          )}
        </div>
      ) : null}
    </div>
  )
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return JSON.stringify(value)
}
