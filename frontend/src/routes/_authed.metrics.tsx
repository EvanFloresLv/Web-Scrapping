import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { queryKeys } from '@/api/queryKeys'
import { type ApiError, apiFetch } from '@/lib/api'

/**
 * Metrics dashboard (spec 0012 M1).
 *
 * M1 ships one panel: Request rate + latency (p50, p95). Panels for HTTP
 * error rate, extraction, and executions land in M2; empty states and
 * deep linking in M3 and M4.
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

const DURATION_METRIC = 'http_request_duration_seconds'
const COUNT_METRIC = 'http_requests_total'

export const Route = createFileRoute('/_authed/metrics')({
  component: MetricsPage,
})

function MetricsPage() {
  const query = useQuery<MetricQueryResponse, ApiError>({
    queryKey: queryKeys.metrics.query([DURATION_METRIC, COUNT_METRIC], { window: '1h' }),
    queryFn: ({ signal }) =>
      apiFetch<MetricQueryResponse>(
        `/api/v1/metrics/query?metric=${DURATION_METRIC}&metric=${COUNT_METRIC}`,
        { signal },
      ),
    refetchInterval: 30_000,
    staleTime: 15_000,
  })

  return (
    <div className="flex flex-col gap-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Metrics</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Operator view, last 60 minutes. Flushed once every{' '}
          <code className="rounded bg-muted px-1 text-xs">METRICS_FLUSH_INTERVAL_S</code> seconds.
        </p>
      </header>

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

      <section className="rounded-lg border bg-card p-4 shadow-sm">
        <header className="mb-3">
          <h2 className="text-base font-semibold">Request rate &amp; latency</h2>
          <p className="text-xs text-muted-foreground">
            Requests per minute, p50 and p95 latency, grouped by route (top 10 by volume).
          </p>
        </header>
        <RequestLatencyPanel data={query.data} isLoading={query.isLoading} />
      </section>
    </div>
  )
}

type MergedPoint = {
  bucket_start: string
  bucket_label: string
  count: number
  p50_ms: number | null
  p95_ms: number | null
}

const TOP_ROUTE_CAP = 10

function RequestLatencyPanel({
  data,
  isLoading,
}: {
  data: MetricQueryResponse | undefined
  isLoading: boolean
}) {
  if (isLoading) {
    return <div className="h-64 animate-pulse rounded bg-muted/40" />
  }
  if (!data || data.series.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        No data in the last hour.
      </div>
    )
  }

  const durationSeries = data.series.filter((s) => s.metric === DURATION_METRIC)
  const countSeries = data.series.filter((s) => s.metric === COUNT_METRIC)

  // Rank routes by total request count in the window and cap at TOP_ROUTE_CAP
  // so a sprawling API does not render 60 lines.
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

  const perRoutePoints: Record<string, Map<string, MergedPoint>> = {}
  for (const route of topRoutes) {
    perRoutePoints[route] = new Map()
  }

  for (const s of countSeries) {
    const route = s.labels.route ?? 'unmatched'
    if (!perRoutePoints[route]) continue
    for (const p of s.points) {
      const existing = perRoutePoints[route].get(p.bucket_start)
      const merged: MergedPoint = existing ?? {
        bucket_start: p.bucket_start,
        bucket_label: new Date(p.bucket_start).toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        }),
        count: 0,
        p50_ms: null,
        p95_ms: null,
      }
      merged.count += p.count
      perRoutePoints[route].set(p.bucket_start, merged)
    }
  }

  // Pull p50/p95 from duration series into the same per-route buckets.
  for (const s of durationSeries) {
    const route = s.labels.route ?? 'unmatched'
    if (!perRoutePoints[route]) continue
    for (const p of s.points) {
      const existing = perRoutePoints[route].get(p.bucket_start)
      if (!existing) continue
      existing.p50_ms = p.p50_ms
      existing.p95_ms = p.p95_ms
    }
  }

  const sampleRoute = topRoutes[0]
  if (!sampleRoute) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        No data in the last hour.
      </div>
    )
  }

  // Shape the chart data: one row per bucket, each top route as its own
  // count series. For M1 we show the aggregated (summed) latency across
  // the top routes rather than one latency line per route, which keeps
  // the chart readable at 10 series.
  const bucketKeys = Array.from(
    new Set(topRoutes.flatMap((r) => Array.from(perRoutePoints[r].keys()))),
  ).sort()

  const chartData = bucketKeys.map((bucket) => {
    const row: Record<string, number | string | null> = {
      bucket_label: new Date(bucket).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      }),
    }
    let totalCount = 0
    let p50Sum = 0
    let p50Weight = 0
    let p95Sum = 0
    let p95Weight = 0
    for (const route of topRoutes) {
      const point = perRoutePoints[route].get(bucket)
      row[route] = point?.count ?? 0
      totalCount += point?.count ?? 0
      if (point?.p50_ms != null && point.count > 0) {
        p50Sum += point.p50_ms * point.count
        p50Weight += point.count
      }
      if (point?.p95_ms != null && point.count > 0) {
        p95Sum += point.p95_ms * point.count
        p95Weight += point.count
      }
    }
    row.__total = totalCount
    row.__p50_ms = p50Weight > 0 ? p50Sum / p50Weight : null
    row.__p95_ms = p95Weight > 0 ? p95Sum / p95Weight : null
    return row
  })

  const routeColors = [
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

  return (
    <div className="flex flex-col gap-4">
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
                stroke={routeColors[i % routeColors.length]}
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
