import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { ArrowLeft, Pencil, Plus, Trash2 } from 'lucide-react'
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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { type ApiError, apiFetch } from '@/lib/api'
import { type ListSearch, listSearchSchema } from '@/lib/listSearch'
import { useListQuery } from '@/lib/useListQuery'

type WebsiteRead = components['schemas']['WebsiteRead']
type TargetRead = components['schemas']['TargetRead']
type TargetCreateBody = components['schemas']['TargetCreate']
type TargetUpdateBody = components['schemas']['TargetUpdate']

const targetFormSchema = z.object({
  url: z.string().url('Must be a valid URL'),
  label: z.string().min(1, 'Label is required'),
})

type TargetFormValues = z.infer<typeof targetFormSchema>

export const Route = createFileRoute('/_authed/websites_/$websiteId')({
  validateSearch: (search) => listSearchSchema.parse(search),
  component: WebsiteDetailPage,
})

function WebsiteDetailPage() {
  const { websiteId } = Route.useParams()
  const filters = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const queryClient = useQueryClient()
  const [sheetState, setSheetState] = useState<TargetSheetState>({ open: false, mode: 'create' })
  const [deleteTarget, setDeleteTarget] = useState<TargetRead | null>(null)

  const websiteQuery = useQuery<WebsiteRead, ApiError>({
    queryKey: queryKeys.websites.detail(websiteId),
    queryFn: ({ signal }) =>
      apiFetch<WebsiteRead>(`/api/v1/websites/${websiteId}`, { signal, silent: true }),
    retry: false,
  })

  // AC-3: redirect to /websites with a toast when the website is missing / soft deleted.
  useEffect(() => {
    const error = websiteQuery.error
    if (!error) return
    if (error.status === 404) {
      toast.error('Website not found or has been deleted.')
      navigate({ to: '/websites', search: { page: 1, page_size: 50, with_deleted: false } })
    } else {
      toast.error(error.title)
    }
  }, [websiteQuery.error, navigate])

  const targetsQuery = useListQuery<TargetRead>({
    queryKey: queryKeys.websites.targets.list(websiteId, filters),
    endpoint: `/api/v1/websites/${websiteId}/targets`,
    filters,
    enabled: websiteQuery.data !== undefined,
  })

  const updateFilters = (next: Partial<ListSearch>) => {
    navigate({ search: (prev) => ({ ...prev, ...next }) })
  }

  const columns: DataTableColumn<TargetRead>[] = useMemo(
    () => [
      {
        key: 'url',
        header: 'URL',
        cell: (row) => <span className="font-mono text-xs">{row.url}</span>,
      },
      { key: 'label', header: 'Label', cell: (row) => row.label },
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
              aria-label={`Edit ${row.label}`}
              onClick={() => setSheetState({ open: true, mode: 'edit', target: row })}
            >
              <Pencil />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Delete ${row.label}`}
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

  const openCreate = () => setSheetState({ open: true, mode: 'create' })

  if (websiteQuery.isPending) {
    return <p className="p-6 text-sm text-muted-foreground">Loading…</p>
  }
  if (!websiteQuery.data) {
    return null
  }
  const website = websiteQuery.data

  return (
    <div className="space-y-6 p-6">
      <div>
        <Link
          to="/websites"
          search={{ page: 1, page_size: 50, with_deleted: false }}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back to websites
        </Link>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{website.display_name}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm sm:grid-cols-2">
          <Metadata label="Host" value={<code className="font-mono">{website.host}</code>} />
          <Metadata label="Status" value={<StatusBadge value={website.status} />} />
          <Metadata label="Created" value={formatDate(website.created_at)} />
          <Metadata label="Updated" value={formatDate(website.updated_at)} />
        </CardContent>
      </Card>

      <Separator />

      <section className="space-y-4">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Target URLs</h2>
            <p className="text-sm text-muted-foreground">
              Pages registered under this website that workflows can execute against.
            </p>
          </div>
          <Button type="button" onClick={openCreate}>
            <Plus /> Add target
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
          rows={targetsQuery.data?.items}
          isLoading={targetsQuery.isPending}
          isError={targetsQuery.isError}
          errorMessage="Failed to load targets."
          empty={
            <EmptyState
              title="No target URLs yet."
              description="Add a target so workflows under this website have something to scrape."
              action={{ label: 'Add target', onClick: openCreate, icon: <Plus /> }}
            />
          }
          pagination={paginationFromListSearch(
            filters,
            targetsQuery.data?.total ?? 0,
            updateFilters,
          )}
        />
      </section>

      <TargetSheet
        websiteId={websiteId}
        state={sheetState}
        onClose={() => setSheetState((prev) => ({ ...prev, open: false }))}
        onSuccess={() => {
          queryClient.invalidateQueries({
            queryKey: ['websites', websiteId, 'targets'],
          })
        }}
      />

      <DeleteTargetDialog
        target={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onDeleted={() => {
          queryClient.invalidateQueries({
            queryKey: ['websites', websiteId, 'targets'],
          })
        }}
      />
    </div>
  )
}

function Metadata({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span>{value}</span>
    </div>
  )
}

function StatusBadge({ value }: { value: 'active' | 'inactive' }) {
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

type TargetSheetState =
  | { open: boolean; mode: 'create' }
  | { open: boolean; mode: 'edit'; target: TargetRead }

function TargetSheet({
  websiteId,
  state,
  onClose,
  onSuccess,
}: {
  websiteId: string
  state: TargetSheetState
  onClose: () => void
  onSuccess: () => void
}) {
  const isEdit = state.mode === 'edit'
  const form = useForm<TargetFormValues>({
    resolver: zodResolver(targetFormSchema),
    defaultValues: { url: '', label: '' },
  })
  const [conflictBanner, setConflictBanner] = useState<string | null>(null)

  useEffect(() => {
    if (!state.open) return
    setConflictBanner(null)
    if (state.mode === 'edit') {
      form.reset({ url: state.target.url, label: state.target.label })
    } else {
      form.reset({ url: '', label: '' })
    }
  }, [state, form])

  const mutation = useMutation<TargetRead, ApiError, TargetFormValues>({
    mutationFn: async (values) => {
      if (state.mode === 'edit') {
        const body: TargetUpdateBody = { label: values.label }
        return apiFetch<TargetRead>(`/api/v1/targets/${state.target.id}`, {
          method: 'PATCH',
          body: JSON.stringify(body),
          rhfSetError: form.setError as never,
          silent: true,
        })
      }
      const body: TargetCreateBody = { url: values.url, label: values.label }
      return apiFetch<TargetRead>(`/api/v1/websites/${websiteId}/targets`, {
        method: 'POST',
        body: JSON.stringify(body),
        rhfSetError: form.setError as never,
        silent: true,
      })
    },
    onSuccess: () => {
      toast.success(isEdit ? 'Target updated.' : 'Target added.')
      onSuccess()
      onClose()
    },
    onError: (error) => {
      // AC-4: 409 becomes a dialog level banner; 422 field errors are already
      // routed by apiFetch via `rhfSetError`. Everything else surfaces as a toast.
      if (error.status === 409) {
        setConflictBanner(error.detail ?? error.title)
        return
      }
      if (error.errors.length === 0) {
        toast.error(error.detail ?? error.title)
      }
    },
  })

  const onSubmit = form.handleSubmit((values) => {
    setConflictBanner(null)
    mutation.mutate(values)
  })

  return (
    <CrudSheet
      open={state.open}
      onOpenChange={(next) => (next ? undefined : onClose())}
      title={isEdit ? 'Edit target' : 'Add target'}
      description={
        isEdit
          ? 'Update the label or status. The URL is immutable.'
          : 'Register a new URL under this website for workflows to execute against.'
      }
      mode={isEdit ? 'edit' : 'create'}
      onSubmit={onSubmit}
      isSubmitting={mutation.isPending}
    >
      {conflictBanner ? (
        <div
          className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
          role="alert"
        >
          {conflictBanner}
        </div>
      ) : null}
      <div className="flex flex-col gap-2">
        <Label htmlFor="target-url">URL</Label>
        <Input
          id="target-url"
          placeholder="https://example.com/path"
          autoComplete="off"
          disabled={isEdit}
          {...form.register('url')}
        />
        {isEdit ? (
          <p className="text-xs text-muted-foreground">
            URL is immutable; add a new target to change it.
          </p>
        ) : null}
        {form.formState.errors.url ? (
          <p className="text-xs text-destructive" role="alert">
            {form.formState.errors.url.message}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="target-label">Label</Label>
        <Input id="target-label" {...form.register('label')} />
        {form.formState.errors.label ? (
          <p className="text-xs text-destructive" role="alert">
            {form.formState.errors.label.message}
          </p>
        ) : null}
      </div>
    </CrudSheet>
  )
}

function DeleteTargetDialog({
  target,
  onClose,
  onDeleted,
}: {
  target: TargetRead | null
  onClose: () => void
  onDeleted: () => void
}) {
  const mutation = useMutation<void, ApiError, string>({
    mutationFn: (id) => apiFetch<void>(`/api/v1/targets/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      toast.success('Target deleted.')
      onDeleted()
      onClose()
    },
  })

  return (
    <AlertDialog
      open={target !== null}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete target</AlertDialogTitle>
          <AlertDialogDescription>
            Soft deletes <span className="font-mono text-foreground">{target?.label}</span> (
            <span className="font-mono text-foreground">{target?.url}</span>). Workflows that
            reference this URL will fail to execute until it is restored.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onClose}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={mutation.isPending}
            onClick={(event) => {
              event.preventDefault()
              if (target) mutation.mutate(target.id)
            }}
          >
            {mutation.isPending ? 'Deleting…' : 'Delete'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
