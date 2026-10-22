import { useQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { z } from 'zod'

import { queryKeys } from '@/api/queryKeys'
import { Input } from '@/components/ui/input'
import { type ApiError, apiFetch } from '@/lib/api'

/**
 * Metrics dashboard (spec 0012).
 *
 * Four panels: Request rate + latency, HTTP error rate, Extraction, and
 * Executions. Toolbar carries the window (fixed 1h for the MVP) and a
 * workflow filter (free text UUID per AC-9). Empty states + deep link
 * land in M3 and M4.
 */

type MetricPoint = {
  bucket_start: string
  count: number
  sum_value: number
  p50_ms: number | null
  p95_ms: number | null
  p99_ms: number | null
}

type MetricSeries = {
  metric: string
  labels: Record<string, string>
  points: MetricPoint[]
}

type MetricQueryResponse = {
  series: MetricSeries[]
}

const HTTP_DURATION = 'http_request_duration_seconds'
const HTTP_COUNT = 'http_requests_total'
const EXTRACTION_DURATION = 'extraction_duration_seconds'
const EXTRACTION_COUNT = 'extraction_runs_total'
const EXECUTION_DURATION = 'execution_duration_seconds'
const EXECUTION_COUNT = 'executions_total'

const ALL_METRICS = [
  HTTP_DURATION,
  HTTP_COUNT,
  EXTRACTION_DURATION,
  EXTRACTION_COUNT,
  EXECUTION_DURATION,
  EXECUTION_COUNT,
] as const

const metricsSearchSchema = z.object({
  workflow_id: z.string().uuid().optional().catch(undefined),
})

export const Route = createFileRoute('/_authed/metrics')({
  validateSearch: (search) => metricsSearchSchema.parse(search),
  component: MetricsPage,
})

function MetricsPage() {
  const { workflow_id } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const clearWorkflowFilter = () => navigate({ search: {} })

  const query = useQuery<MetricQueryResponse, ApiError>({
    queryKey: queryKeys.metrics.query([...ALL_METRICS], { window: '1h' }),
    queryFn: ({ signal }) => {
      const metricParams = ALL_METRICS.map((m) => `metric=${encodeURIComponent(m)}`).join('&')
      return apiFetch<MetricQueryResponse>(`/api/v1/metrics/query?${metricParams}`, { signal })
    },
    refetchInterval: 30_000,
    staleTime: 15_000,
  })

  const series = query.data?.series ?? []

  return (
    <div className="flex flex-col gap-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Metrics</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Operator view, last 60 minutes. Flushed once every{' '}
          <code className="rounded bg-muted px-1 text-xs">METRICS_FLUSH_INTERVAL_S</code> seconds.
        </p>
      </header>

      <Toolbar workflowId={workflow_id} onClearWorkflow={clearWorkflowFilter} />

      {query.isError ? (
        <div
          className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
          role="alert"
        >
          <strong>{query.error.title ?? 'Failed to load metrics'}:</strong>{' '}
          {query.error.detail ?? query.error.message}
          {query.error.correlationId ? (
            <span className="ml-2 text-xs opacity-80">
              (correlation {query.error.correlationId})
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel
          title="Request rate & latency"
          subtitle="Requests per minute, p50 and p95 latency, grouped by route (top 10 by volume)."
        >
          <RequestLatencyPanel series={series} isLoading={query.isLoading} />
        </Panel>
        <Panel
          title="HTTP error rate"
          subtitle="Request count stacked by status class, raw counts."
        >
          <HttpErrorPanel series={series} isLoading={query.isLoading} />
        </Panel>
        <Panel
          title="Extraction"
          subtitle={
            workflow_id
              ? 'Completed vs failed extractions + p95 duration (grouped by phase).'
              : 'Completed vs failed extractions + p95 duration, aggregated across workflows.'
          }
        >
          <ExtractionPanel
            series={series}
            isLoading={query.isLoading}
            workflowFilter={workflow_id}
          />
        </Panel>
        <Panel
          title="Executions"
          subtitle={
            workflow_id
              ? 'Throughput + p95 execution duration (filtered to one workflow).'
              : 'Throughput + p95 execution duration, aggregated across workflows.'
          }
        >
          <ExecutionsPanel
            series={series}
            isLoading={query.isLoading}
            workflowFilter={workflow_id}
          />
        </Panel>
      </div>
    </div>
  )
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border bg-card p-4 shadow-sm">
      <header className="mb-3">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-xs text-muted-foreground">{subtitle}</p>
      </header>
      {children}
    </section>
  )
}

function Toolbar({
  workflowId,
  onClearWorkflow,
}: {
  workflowId: string | undefined
  onClearWorkflow: () => void
}) {
  // Toolbar is a thin wrapper. Window is fixed to the last 60 minutes for the
  // MVP; the workflow input is a free text UUID (spec 0012 AC-9). The run
  // detail page's "View metrics" link navigates here with `?workflow_id=...`.
  const navigate = useNavigate({ from: Route.fullPath })
  return (
    <div className="flex flex-wrap items-end gap-4 rounded-md border bg-card/50 p-3">
      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium text-muted-foreground">Window</span>
        <div className="h-9 rounded-md border border-input bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          Last 60 minutes
        </div>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground" htmlFor="workflow-filter">
          Workflow id (optional)
        </label>
        <Input
          id="workflow-filter"
          placeholder="paste a workflow uuid"
          defaultValue={workflowId ?? ''}
          onBlur={(e) => {
            const next = e.currentTarget.value.trim()
            navigate({ search: next ? { workflow_id: next } : {} })
          }}
          className="h-9 w-80"
        />
      </div>
      {workflowId ? (
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
            Filter: {workflowId.slice(0, 8)}…
          </span>
          <button
            type="button"
            onClick={onClearWorkflow}
            className="text-xs text-muted-foreground hover:underline"
          >
            Clear filter
          </button>
        </div>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------------------- */
/* Panel: Request rate & latency                                             */
/* ------------------------------------------------------------------------- */

const TOP_ROUTE_CAP = 10
const ROUTE_COLORS = [
  '#2563eb',
  '#16a34a',
  '#f97316',
  '#9333ea',
  '#dc2626',
  '#0ea5e9',
  '#ca8a04',
  '#ea580c',
  '#059669',
  '#be123c',
]

function RequestLatencyPanel({
  series,
  isLoading,
}: {
  series: MetricSeries[]
  isLoading: boolean
}) {
  const durationSeries = series.filter((s) => s.metric === HTTP_DURATION)
  const countSeries = series.filter((s) => s.metric === HTTP_COUNT)
  if (isLoading) return <PanelSkeleton />
  if (countSeries.length === 0 && durationSeries.length === 0) {
    return <NoData />
  }

  const totalsByRoute = new Map<string, number>()
  for (const s of countSeries) {
    const route = s.labels.route ?? 'unmatched'
    const total = s.points.reduce((acc, p) => acc + p.count, 0)
    totalsByRoute.set(route, (totalsByRoute.get(route) ?? 0) + total)
  }
  const topRoutes = Array.from(totalsByRoute.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, TOP_ROUTE_CAP)
    .map(([route]) => route)
  const hiddenRouteCount = Math.max(0, totalsByRoute.size - topRoutes.length)

  const bucketKeys = Array.from(
    new Set([
      ...countSeries.flatMap((s) => s.points.map((p) => p.bucket_start)),
      ...durationSeries.flatMap((s) => s.points.map((p) => p.bucket_start)),
    ]),
  ).sort()

  const chartData = bucketKeys.map((bucket) => {
    const row: Record<string, number | string | null> = {
      bucket_label: shortTime(bucket),
    }
    let p50Weighted = 0
    let p95Weighted = 0
    let weight = 0
    for (const route of topRoutes) {
      const count = countSeries
        .filter((s) => (s.labels.route ?? 'unmatched') === route)
        .flatMap((s) => s.points.filter((p) => p.bucket_start === bucket))
        .reduce((acc, p) => acc + p.count, 0)
      row[route] = count
    }
    for (const s of durationSeries) {
      const point = s.points.find((p) => p.bucket_start === bucket)
      if (point?.p50_ms != null && point.count > 0) {
        p50Weighted += point.p50_ms * point.count
        weight += point.count
      }
      if (point?.p95_ms != null && point.count > 0) {
        p95Weighted += point.p95_ms * point.count
      }
    }
    row.__p50_ms = weight > 0 ? p50Weighted / weight : null
    row.__p95_ms = weight > 0 ? p95Weighted / weight : null
    return row
  })

  if (chartData.length === 0) return <NoData />

  return (
    <div className="flex flex-col gap-2">
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="bucket_label" fontSize={11} />
            <YAxis yAxisId="count" fontSize={11} allowDecimals={false} />
            <YAxis
              yAxisId="latency"
              orientation="right"
              fontSize={11}
              tickFormatter={(v: number) => `${v.toFixed(0)}ms`}
            />
            <Tooltip
              formatter={(value, name) => {
                if (value == null) return ['n/a', String(name)]
                if (name === 'p50_ms' || name === 'p95_ms') {
                  return [`${Number(value).toFixed(1)} ms`, String(name)]
                }
                return [String(value), String(name)]
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {topRoutes.map((route, i) => (
              <Line
                key={route}
                yAxisId="count"
                type="monotone"
                dataKey={route}
                name={route}
                stroke={ROUTE_COLORS[i % ROUTE_COLORS.length]}
                dot={false}
                strokeWidth={1.5}
              />
            ))}
            <Line
              yAxisId="latency"
              type="monotone"
              dataKey="__p50_ms"
              name="p50_ms"
              stroke="#111827"
              strokeDasharray="4 2"
              dot={false}
              strokeWidth={1}
            />
            <Line
              yAxisId="latency"
              type="monotone"
              dataKey="__p95_ms"
              name="p95_ms"
              stroke="#6b7280"
              strokeDasharray="4 2"
              dot={false}
              strokeWidth={1}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {hiddenRouteCount > 0 ? (
        <p className="text-xs text-muted-foreground">
          {hiddenRouteCount} route{hiddenRouteCount === 1 ? '' : 's'} hidden (showing top{' '}
          {TOP_ROUTE_CAP} by request volume).
        </p>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------------------- */
/* Panel: HTTP error rate                                                    */
/* ------------------------------------------------------------------------- */

const STATUS_CLASS_COLORS: Record<string, string> = {
  '2xx': '#16a34a',
  '3xx': '#0ea5e9',
  '4xx': '#f59e0b',
  '5xx': '#dc2626',
}

function HttpErrorPanel({ series, isLoading }: { series: MetricSeries[]; isLoading: boolean }) {
  if (isLoading) return <PanelSkeleton />
  const countSeries = series.filter((s) => s.metric === HTTP_COUNT)
  if (countSeries.length === 0) return <NoData />

  const statusClasses = ['2xx', '3xx', '4xx', '5xx'] as const
  const bucketKeys = Array.from(
    new Set(countSeries.flatMap((s) => s.points.map((p) => p.bucket_start))),
  ).sort()

  const chartData = bucketKeys.map((bucket) => {
    const row: Record<string, number | string> = { bucket_label: shortTime(bucket) }
    for (const cls of statusClasses) {
      const count = countSeries
        .filter((s) => s.labels.status_class === cls)
        .flatMap((s) => s.points.filter((p) => p.bucket_start === bucket))
        .reduce((acc, p) => acc + p.count, 0)
      row[cls] = count
    }
    return row
  })

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis dataKey="bucket_label" fontSize={11} />
          <YAxis fontSize={11} allowDecimals={false} />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {statusClasses.map((cls) => (
            <Area
              key={cls}
              type="monotone"
              dataKey={cls}
              name={cls}
              stackId="1"
              stroke={STATUS_CLASS_COLORS[cls]}
              fill={STATUS_CLASS_COLORS[cls]}
              fillOpacity={0.45}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ------------------------------------------------------------------------- */
/* Panel: Extraction                                                          */
/* ------------------------------------------------------------------------- */

const PHASE_COLORS: Record<string, string> = {
  fetch: '#2563eb',
  parse: '#16a34a',
  validate: '#9333ea',
  total: '#64748b',
}

function ExtractionPanel({
  series,
  isLoading,
  workflowFilter,
}: {
  series: MetricSeries[]
  isLoading: boolean
  workflowFilter: string | undefined
}) {
  if (isLoading) return <PanelSkeleton />
  const matches = (s: MetricSeries) =>
    workflowFilter ? s.labels.workflow_id === workflowFilter : true
  const countSeries = series.filter((s) => s.metric === EXTRACTION_COUNT).filter(matches)
  const durationSeries = series.filter((s) => s.metric === EXTRACTION_DURATION).filter(matches)
  if (countSeries.length === 0 && durationSeries.length === 0) return <NoData />

  const phases = ['fetch', 'parse', 'validate'] as const
  const bucketKeys = Array.from(
    new Set([
      ...countSeries.flatMap((s) => s.points.map((p) => p.bucket_start)),
      ...durationSeries.flatMap((s) => s.points.map((p) => p.bucket_start)),
    ]),
  ).sort()

  const chartData = bucketKeys.map((bucket) => {
    const row: Record<string, number | string | null> = { bucket_label: shortTime(bucket) }
    let completed = 0
    let failed = 0
    for (const s of countSeries) {
      const points = s.points.filter((p) => p.bucket_start === bucket)
      const sum = points.reduce((acc, p) => acc + p.count, 0)
      if (s.labels.status === 'completed') completed += sum
      if (s.labels.status === 'failed') failed += sum
    }
    row.completed = completed
    row.failed = failed

    // p95 across phases: weighted mean per phase so the eye can compare.
    for (const phase of phases) {
      let weighted = 0
      let weight = 0
      for (const s of durationSeries.filter((d) => d.labels.phase === phase)) {
        const point = s.points.find((p) => p.bucket_start === bucket)
        if (point?.p95_ms != null && point.count > 0) {
          weighted += point.p95_ms * point.count
          weight += point.count
        }
      }
      row[`${phase}_p95_ms`] = weight > 0 ? weighted / weight : null
    }
    return row
  })

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis dataKey="bucket_label" fontSize={11} />
          <YAxis yAxisId="count" fontSize={11} allowDecimals={false} />
          <YAxis
            yAxisId="latency"
            orientation="right"
            fontSize={11}
            tickFormatter={(v: number) => `${v.toFixed(0)}ms`}
          />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar yAxisId="count" dataKey="completed" stackId="x" fill="#16a34a" name="completed" />
          <Bar yAxisId="count" dataKey="failed" stackId="x" fill="#dc2626" name="failed" />
          {phases.map((phase) => (
            <Line
              key={phase}
              yAxisId="latency"
              type="monotone"
              dataKey={`${phase}_p95_ms`}
              name={`p95 ${phase}`}
              stroke={PHASE_COLORS[phase]}
              strokeDasharray="4 2"
              dot={false}
              strokeWidth={1}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ------------------------------------------------------------------------- */
/* Panel: Executions                                                         */
/* ------------------------------------------------------------------------- */

function ExecutionsPanel({
  series,
  isLoading,
  workflowFilter,
}: {
  series: MetricSeries[]
  isLoading: boolean
  workflowFilter: string | undefined
}) {
  if (isLoading) return <PanelSkeleton />
  const matches = (s: MetricSeries) =>
    workflowFilter ? s.labels.workflow_id === workflowFilter : true
  const countSeries = series.filter((s) => s.metric === EXECUTION_COUNT).filter(matches)
  const durationSeries = series.filter((s) => s.metric === EXECUTION_DURATION).filter(matches)
  if (countSeries.length === 0 && durationSeries.length === 0) return <NoData />

  const bucketKeys = Array.from(
    new Set([
      ...countSeries.flatMap((s) => s.points.map((p) => p.bucket_start)),
      ...durationSeries.flatMap((s) => s.points.map((p) => p.bucket_start)),
    ]),
  ).sort()

  const chartData = bucketKeys.map((bucket) => {
    const row: Record<string, number | string | null> = { bucket_label: shortTime(bucket) }
    const total = countSeries
      .flatMap((s) => s.points.filter((p) => p.bucket_start === bucket))
      .reduce((acc, p) => acc + p.count, 0)
    row.throughput = total

    let weighted = 0
    let weight = 0
    for (const s of durationSeries) {
      const point = s.points.find((p) => p.bucket_start === bucket)
      if (point?.p95_ms != null && point.count > 0) {
        weighted += point.p95_ms * point.count
        weight += point.count
      }
    }
    row.p95_ms = weight > 0 ? weighted / weight : null
    return row
  })

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis dataKey="bucket_label" fontSize={11} />
          <YAxis yAxisId="count" fontSize={11} allowDecimals={false} />
          <YAxis
            yAxisId="latency"
            orientation="right"
            fontSize={11}
            tickFormatter={(v: number) => `${v.toFixed(0)}ms`}
          />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line
            yAxisId="count"
            type="monotone"
            dataKey="throughput"
            name="executions/min"
            stroke="#2563eb"
            strokeWidth={1.5}
            dot={false}
          />
          <Line
            yAxisId="latency"
            type="monotone"
            dataKey="p95_ms"
            name="p95 ms"
            stroke="#6b7280"
            strokeDasharray="4 2"
            strokeWidth={1}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ------------------------------------------------------------------------- */
/* Shared                                                                    */
/* ------------------------------------------------------------------------- */

function PanelSkeleton() {
  return <div className="h-64 animate-pulse rounded bg-muted/40" />
}

function NoData() {
  return (
    <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
      No data in the last hour.
    </div>
  )
}

function shortTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
