import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import type { ListSearch } from '@/lib/listSearch'
import { cn } from '@/lib/utils'

/**
 * Shared filter row (spec 0009 M1) for every admin list route. The caller
 * decides which filters to show by composing `FilterSelect` and
 * `FilterCheckbox` children (so the Workflows list can add its
 * `website_id` combobox without the primitive growing a prop for it).
 */
export function FilterBar({
  children,
  actions,
  className,
}: {
  children: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap items-end justify-between gap-3', className)}>
      <div className="flex flex-wrap items-end gap-3">{children}</div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function FilterField({
  label,
  htmlFor,
  children,
}: {
  label: string
  htmlFor: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={htmlFor} className="text-xs text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  )
}

export type StatusFilterValue = ListSearch['status']

export function StatusFilter({
  id = 'status-filter',
  value,
  onChange,
}: {
  id?: string
  value: StatusFilterValue
  onChange: (next: StatusFilterValue) => void
}) {
  return (
    <FilterField label="Status" htmlFor={id}>
      <select
        id={id}
        className="h-9 rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        value={value ?? ''}
        onChange={(event) => {
          const next = event.target.value
          onChange(next === '' ? undefined : (next as StatusFilterValue))
        }}
      >
        <option value="">All</option>
        <option value="active">Active</option>
        <option value="inactive">Inactive</option>
      </select>
    </FilterField>
  )
}

export function WithDeletedToggle({
  id = 'with-deleted',
  value,
  onChange,
}: {
  id?: string
  value: boolean
  onChange: (next: boolean) => void
}) {
  return (
    <label htmlFor={id} className="flex items-center gap-2 text-sm text-muted-foreground">
      <input
        id={id}
        type="checkbox"
        checked={value}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 rounded border-input"
      />
      Include deleted
    </label>
  )
}

/**
 * `Reset` button that writes the defaults back to the search params. Each
 * list route provides its own `onReset` so additional filters (e.g. the
 * Workflows list's `website_id`) are reset in the same action.
 */
export function ResetFiltersButton({ onReset }: { onReset: () => void }) {
  return (
    <Button type="button" variant="ghost" size="sm" onClick={onReset}>
      Reset filters
    </Button>
  )
}
