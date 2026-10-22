import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'
import { queryKeys } from '@/api/queryKeys'
import type { components } from '@/api/schema'
import { CrudSheet } from '@/components/crud-sheet'
import { DataTable, type DataTableColumn, paginationFromListSearch } from '@/components/data-table'
import { EmptyState } from '@/components/empty-state'
import {
  FilterBar,
  ResetFiltersButton,
  StatusFilter,
  WithDeletedToggle,
} from '@/components/filter-bar'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { type ApiError, apiFetch } from '@/lib/api'
import { type ListSearch, listSearchSchema } from '@/lib/listSearch'
import { useListQuery } from '@/lib/useListQuery'

type WebsiteRead = components['schemas']['WebsiteRead']
type WebsiteCreateBody = components['schemas']['WebsiteCreate']
type WebsiteUpdateBody = components['schemas']['WebsiteUpdate']

const websiteFormSchema = z.object({
  host: z.string().min(1, 'Host is required'),
  display_name: z.string().min(1, 'Display name is required'),
})

type WebsiteFormValues = z.infer<typeof websiteFormSchema>

export const Route = createFileRoute('/_authed/websites')({
  validateSearch: (search) => listSearchSchema.parse(search),
  component: WebsitesPage,
})

function WebsitesPage() {
  const filters = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const queryClient = useQueryClient()
  const [sheetMode, setSheetMode] = useState<SheetState>({ open: false, mode: 'create' })
  const [deleteTarget, setDeleteTarget] = useState<WebsiteRead | null>(null)

  const list = useListQuery<WebsiteRead>({
    queryKey: queryKeys.websites.list(filters),
    endpoint: '/api/v1/websites',
    filters,
  })

  const updateFilters = (next: Partial<ListSearch>) => {
    navigate({ search: (prev) => ({ ...prev, ...next }) })
  }

  const columns: DataTableColumn<WebsiteRead>[] = useMemo(
    () => [
      {
        key: 'host',
        header: 'Host',
        cell: (row) => (
          <Link
            to="/websites/$websiteId"
            params={{ websiteId: row.id }}
            search={{ page: 1, page_size: 50, with_deleted: false }}
            className="font-medium text-primary hover:underline"
          >
            {row.host}
          </Link>
        ),
      },
      { key: 'display_name', header: 'Display name', cell: (row) => row.display_name },
      {
        key: 'status',
        header: 'Status',
        cell: (row) => <StatusBadge value={row.status} />,
      },
      {
        key: 'updated_at',
        header: 'Updated',
        cell: (row) => formatDate(row.updated_at),
        className: 'text-muted-foreground',
      },
      {
        key: 'actions',
        header: '',
        className: 'w-[1%] whitespace-nowrap text-right',
        cell: (row) => (
          <div className="flex justify-end gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Edit ${row.host}`}
              onClick={() => setSheetMode({ open: true, mode: 'edit', website: row })}
            >
              <Pencil />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Delete ${row.host}`}
              onClick={() => setDeleteTarget(row)}
            >
              <Trash2 />
            </Button>
          </div>
        ),
      },
    ],
    [],
  )

  const openCreate = () => setSheetMode({ open: true, mode: 'create' })

  return (
    <div className="space-y-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Websites</h1>
          <p className="text-sm text-muted-foreground">
            Registered websites. Click a host to open its targets.
          </p>
        </div>
        <Button type="button" onClick={openCreate}>
          <Plus /> Register website
        </Button>
      </header>

      <FilterBar
        actions={
          <ResetFiltersButton
            onReset={() =>
              navigate({ search: { page: 1, page_size: 50, with_deleted: false } as ListSearch })
            }
          />
        }
      >
        <StatusFilter
          value={filters.status}
          onChange={(status) => updateFilters({ status, page: 1 })}
        />
        <WithDeletedToggle
          value={filters.with_deleted}
          onChange={(with_deleted) => updateFilters({ with_deleted, page: 1 })}
        />
      </FilterBar>

      <DataTable
        columns={columns}
        rows={list.data?.items}
        isLoading={list.isPending}
        isError={list.isError}
        errorMessage="Failed to load websites."
        empty={
          <EmptyState
            title="No websites registered yet."
            description="Register a website to start adding targets and workflows under it."
            action={{ label: 'Register website', onClick: openCreate, icon: <Plus /> }}
          />
        }
        pagination={paginationFromListSearch(filters, list.data?.total ?? 0, updateFilters)}
      />

      <WebsiteSheet
        state={sheetMode}
        onClose={() => setSheetMode((prev) => ({ ...prev, open: false }))}
        onSuccess={() => {
          queryClient.invalidateQueries({ queryKey: queryKeys.websites.all })
        }}
      />

      <DeleteWebsiteDialog
        website={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onDeleted={() => {
          queryClient.invalidateQueries({ queryKey: queryKeys.websites.all })
        }}
      />
    </div>
  )
}

function StatusBadge({ value }: { value: WebsiteRead['status'] }) {
  const tone =
    value === 'active'
      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
      : 'bg-muted text-muted-foreground'
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
      {value}
    </span>
  )
}

function formatDate(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString()
}

type SheetState =
  | { open: boolean; mode: 'create' }
  | { open: boolean; mode: 'edit'; website: WebsiteRead }

function WebsiteSheet({
  state,
  onClose,
  onSuccess,
}: {
  state: SheetState
  onClose: () => void
  onSuccess: () => void
}) {
  const isEdit = state.mode === 'edit'
  const form = useForm<WebsiteFormValues>({
    resolver: zodResolver(websiteFormSchema),
    defaultValues: { host: '', display_name: '' },
  })

  useEffect(() => {
    if (!state.open) return
    if (state.mode === 'edit') {
      form.reset({ host: state.website.host, display_name: state.website.display_name })
    } else {
      form.reset({ host: '', display_name: '' })
    }
  }, [state, form])

  const mutation = useMutation<WebsiteRead, ApiError, WebsiteFormValues>({
    mutationFn: async (values) => {
      if (state.mode === 'edit') {
        const body: WebsiteUpdateBody = { display_name: values.display_name }
        return apiFetch<WebsiteRead>(`/api/v1/websites/${state.website.id}`, {
          method: 'PATCH',
          body: JSON.stringify(body),
          rhfSetError: form.setError as never,
        })
      }
      const body: WebsiteCreateBody = { host: values.host, display_name: values.display_name }
      return apiFetch<WebsiteRead>('/api/v1/websites', {
        method: 'POST',
        body: JSON.stringify(body),
        rhfSetError: form.setError as never,
      })
    },
    onSuccess: () => {
      toast.success(isEdit ? 'Website updated.' : 'Website registered.')
      onSuccess()
      onClose()
    },
  })

  const onSubmit = form.handleSubmit((values) => mutation.mutate(values))

  return (
    <CrudSheet
      open={state.open}
      onOpenChange={(next) => (next ? undefined : onClose())}
      title={isEdit ? 'Edit website' : 'Register website'}
      description={
        isEdit
          ? 'Update the display name or status. The host is immutable.'
          : 'Add a website so you can register targets and workflows under it.'
      }
      mode={isEdit ? 'edit' : 'create'}
      onSubmit={onSubmit}
      isSubmitting={mutation.isPending}
    >
      <div className="flex flex-col gap-2">
        <Label htmlFor="website-host">Host</Label>
        <Input
          id="website-host"
          placeholder="example.com"
          autoComplete="off"
          disabled={isEdit}
          {...form.register('host')}
        />
        {isEdit ? (
          <p className="text-xs text-muted-foreground">
            Host is immutable; create a new website to change it.
          </p>
        ) : null}
        {form.formState.errors.host ? (
          <p className="text-xs text-destructive" role="alert">
            {form.formState.errors.host.message}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="website-display-name">Display name</Label>
        <Input id="website-display-name" {...form.register('display_name')} />
        {form.formState.errors.display_name ? (
          <p className="text-xs text-destructive" role="alert">
            {form.formState.errors.display_name.message}
          </p>
        ) : null}
      </div>
    </CrudSheet>
  )
}

function DeleteWebsiteDialog({
  website,
  onClose,
  onDeleted,
}: {
  website: WebsiteRead | null
  onClose: () => void
  onDeleted: () => void
}) {
  const [typed, setTyped] = useState('')

  useEffect(() => {
    if (!website) setTyped('')
  }, [website])

  const mutation = useMutation<void, ApiError, string>({
    mutationFn: (id) => apiFetch<void>(`/api/v1/websites/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      toast.success('Website deleted.')
      onDeleted()
      onClose()
    },
  })

  const canDelete = website !== null && typed === website.host && !mutation.isPending

  return (
    <AlertDialog
      open={website !== null}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete website</AlertDialogTitle>
          <AlertDialogDescription>
            Deleting also soft deletes every target URL under this website. Type the host{' '}
            <code className="font-mono text-foreground">{website?.host}</code> to confirm.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="delete-website-host">Host</Label>
          <Input
            id="delete-website-host"
            autoComplete="off"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder={website?.host ?? ''}
          />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onClose}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={!canDelete}
            onClick={(event) => {
              event.preventDefault()
              if (website) mutation.mutate(website.id)
            }}
          >
            {mutation.isPending ? 'Deleting…' : 'Delete'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
