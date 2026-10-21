import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import type { components } from '@/api/schema'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { apiFetch } from '@/lib/api'

// Spec 0008 AC-6: columns are read from the generated types; no field name is
// hand mirrored. Spec 0002 is the source of truth projected into schema.d.ts.
type WebsiteRead = components['schemas']['WebsiteRead']
type WebsiteListResponse = {
  items: WebsiteRead[]
  total: number
  page: number
  page_size: number
}

export const Route = createFileRoute('/_authed/websites')({
  component: WebsitesPage,
})

function WebsitesPage() {
  const query = useQuery({
    queryKey: ['websites'] as const,
    queryFn: () => apiFetch<WebsiteListResponse>('/api/v1/websites'),
  })

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-xl font-semibold">Websites</h1>
        <p className="text-sm text-muted-foreground">
          Registered websites. Column names come from the generated OpenAPI types.
        </p>
      </div>
      {query.isPending ? <p className="text-sm text-muted-foreground">Loading…</p> : null}
      {query.isError ? (
        <p className="text-sm text-destructive" role="alert">
          Failed to load websites.
        </p>
      ) : null}
      {query.data && query.data.items.length === 0 ? <WebsitesEmpty /> : null}
      {query.data && query.data.items.length > 0 ? (
        <WebsitesTable items={query.data.items} />
      ) : null}
    </div>
  )
}

function WebsitesEmpty() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>No websites registered yet.</CardTitle>
        <CardDescription>
          Register one via <code>POST /api/v1/websites</code>.
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        The admin UI will list every registered website here, with its host, display name, status,
        and timestamps.
      </CardContent>
    </Card>
  )
}

function WebsitesTable({ items }: { items: WebsiteRead[] }) {
  // Derive the column list from the first row's keys so the table shape always
  // matches the generated types; no hand mirrored field names.
  const columns = Object.keys(items[0] ?? {}) as Array<keyof WebsiteRead>
  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((col) => (
              <TableHead key={String(col)}>{String(col)}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((row) => (
            <TableRow key={row.id}>
              {columns.map((col) => (
                <TableCell key={String(col)} className="font-mono text-xs">
                  {formatCell(row[col])}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (value instanceof Date) return value.toISOString()
  return String(value)
}
