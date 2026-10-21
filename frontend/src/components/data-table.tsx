import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { type ListSearch, PAGE_SIZE_OPTIONS, type PageSize } from '@/lib/listSearch'
import { cn } from '@/lib/utils'

/**
 * Shared list table (spec 0009 M1) that pairs a shadcn `Table` with the
 * pagination controls every list route needs. The caller supplies column
 * definitions and a row renderer; the table owns the empty / loading
 * fallbacks so a list route reads top down.
 */

export type DataTableColumn<T> = {
  /** Unique key, used for React keys and also the column heading when
   * `header` is not supplied. */
  key: string
  /** Column heading; defaults to `key` when omitted. */
  header?: ReactNode
  /** Renders the cell for one row. */
  cell: (row: T) => ReactNode
  /** Tailwind classes applied to the cell. */
  className?: string
}

export type DataTableProps<T> = {
  columns: DataTableColumn<T>[]
  rows: readonly T[] | undefined
  /** React key for a row; defaults to each row's `id` property when present. */
  rowKey?: (row: T) => string
  isLoading?: boolean
  isError?: boolean
  errorMessage?: string
  /** Rendered when `rows` is defined and empty. */
  empty?: ReactNode
  /** Pagination props; omit to hide the footer entirely. */
  pagination?: PaginationProps
}

export type PaginationProps = {
  page: number
  pageSize: PageSize
  total: number
  onChange: (next: { page: number; page_size: PageSize }) => void
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  isLoading,
  isError,
  errorMessage,
  empty,
  pagination,
}: DataTableProps<T>) {
  const hasRows = rows !== undefined && rows.length > 0
  return (
    <div className="space-y-3">
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((col) => (
                <TableHead key={col.key} className={col.className}>
                  {col.header ?? col.key}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="py-6 text-center text-sm text-muted-foreground"
                >
                  Loading…
                </TableCell>
              </TableRow>
            ) : null}
            {isError ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="py-6 text-center text-sm text-destructive"
                  role="alert"
                >
                  {errorMessage ?? 'Failed to load.'}
                </TableCell>
              </TableRow>
            ) : null}
            {!isLoading && !isError && hasRows
              ? rows.map((row, index) => (
                  <TableRow key={rowKey ? rowKey(row) : defaultRowKey(row, index)}>
                    {columns.map((col) => (
                      <TableCell key={col.key} className={col.className}>
                        {col.cell(row)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              : null}
          </TableBody>
        </Table>
      </div>
      {!isLoading && !isError && !hasRows && empty ? empty : null}
      {pagination ? <PaginationBar {...pagination} /> : null}
    </div>
  )
}

function defaultRowKey(row: unknown, index: number): string {
  if (row && typeof row === 'object' && 'id' in row) {
    const id = (row as { id: unknown }).id
    if (typeof id === 'string' || typeof id === 'number') {
      return String(id)
    }
  }
  return String(index)
}

function PaginationBar({ page, pageSize, total, onChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const canPrev = page > 1
  const canNext = page < totalPages
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1
  const end = Math.min(total, page * pageSize)
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
      <p className="text-muted-foreground">
        {total === 0 ? 'No results' : `Showing ${start}–${end} of ${total}`}
      </p>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-muted-foreground">
          <span>Rows</span>
          <select
            className={cn(
              'h-8 rounded-md border border-input bg-background px-2 text-sm',
              'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
            )}
            value={pageSize}
            onChange={(event) =>
              onChange({ page: 1, page_size: Number(event.target.value) as PageSize })
            }
          >
            {PAGE_SIZE_OPTIONS.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="icon"
            disabled={!canPrev}
            aria-label="Previous page"
            onClick={() => onChange({ page: page - 1, page_size: pageSize })}
          >
            <ChevronLeft />
          </Button>
          <span className="min-w-[6rem] text-center text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="icon"
            disabled={!canNext}
            aria-label="Next page"
            onClick={() => onChange({ page: page + 1, page_size: pageSize })}
          >
            <ChevronRight />
          </Button>
        </div>
      </div>
    </div>
  )
}

/**
 * Convenience helper for binding `DataTable` pagination to a `ListSearch`
 * object (every list route reuses this). Keeps the "reset page to 1 on
 * page_size change" rule in one place.
 */
export function paginationFromListSearch(
  filters: ListSearch,
  total: number,
  update: (next: Partial<ListSearch>) => void,
): PaginationProps {
  return {
    page: filters.page,
    pageSize: filters.page_size,
    total,
    onChange: ({ page, page_size }) => update({ page, page_size }),
  }
}
