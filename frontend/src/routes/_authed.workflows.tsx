import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
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
  FilterField,
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
import { listSearchSchema } from '@/lib/listSearch'
import type { PaginatedResponse } from '@/lib/useListQuery'

type WorkflowRead = components['schemas']['WorkflowRead']
type WorkflowCreateBody = components['schemas']['WorkflowCreate']
type WorkflowUpdateBody = components['schemas']['WorkflowUpdate']
type WebsiteRead = components['schemas']['WebsiteRead']

const workflowsSearchSchema = listSearchSchema.extend({
  website_id: z.string().uuid().optional().catch(undefined),
})
type WorkflowsSearch = z.infer<typeof workflowsSearchSchema>

const workflowFormSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  description: z.string().optional(),
  website_id: z.string().uuid('Pick a website'),
})
type WorkflowFormValues = z.infer<typeof workflowFormSchema>

export const Route = createFileRoute('/_authed/workflows')({
  validateSearch: (search) => workflowsSearchSchema.parse(search),
  component: WorkflowsPage,
})

const DEFAULT_SEARCH: WorkflowsSearch = {
  page: 1,
  page_size: 50,
  with_deleted: false,
  status: undefined,
  website_id: undefined,
}

function WorkflowsPage() {
  const filters = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const queryClient = useQueryClient()
  const [sheetState, setSheetState] = useState<SheetState>({ open: false, mode: 'create' })
  const [deleteTarget, setDeleteTarget] = useState<WorkflowRead | null>(null)

  const activeWebsites = useQuery<PaginatedResponse<WebsiteRead>, ApiError>({
    queryKey: queryKeys.websites.list({ status: 'active', page: 1, page_size: 200 }),
    queryFn: ({ signal }) =>
      apiFetch<PaginatedResponse<WebsiteRead>>(
        '/api/v1/websites?status=active&page=1&page_size=200',
        { signal },
      ),
  })

  const workflowsResult = useWorkflowsList(filters, activeWebsites.data?.items)

  const websiteNameMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const w of activeWebsites.data?.items ?? []) {
      map.set(w.id, w.display_name)
    }
    for (const w of workflowsResult.supplementalWebsites) {
      map.set(w.id, w.display_name)
    }
    return map
  }, [activeWebsites.data, workflowsResult.supplementalWebsites])

  const updateFilters = (next: Partial<WorkflowsSearch>) => {
    navigate({ search: (prev) => ({ ...prev, ...next }) })
  }

  const openCreate = () => setSheetState({ open: true, mode: 'create' })

  const columns: DataTableColumn<WorkflowRead>[] = useMemo(
    () => [
      {
        key: 'name',
        header: 'Name',
        cell: (row) => (
          <Link
            to="/workflows/$workflowId/overview"
            params={{ workflowId: row.id }}
            className="font-medium text-primary hover:underline"
          >
            {row.name}
          </Link>
        ),
      },
      {
        key: 'website',
        header: 'Website',
        cell: (row) => websiteNameMap.get(row.website_id) ?? '—',
      },
      {
        key: 'status',
        header: 'Status',
        cell: (row) => <StatusBadge value={row.status} />,
      },
      {
        key: 'current_version',
        header: 'Current version',
        cell: (row) =>
          row.current_version_id ? <VersionNumber id={row.id} vid={row.current_version_id} /> : '—',
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
              aria-label={`Edit ${row.name}`}
              onClick={() => setSheetState({ open: true, mode: 'edit', workflow: row })}
            >
              <Pencil />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Delete ${row.name}`}
              onClick={() => setDeleteTarget(row)}
            >
              <Trash2 />
            </Button>
          </div>
        ),
      },
    ],
    [websiteNameMap],
  )

  return (
    <div className="space-y-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Workflows</h1>
          <p className="text-sm text-muted-foreground">
            Scraping workflows registered under your websites.
          </p>
        </div>
        <Button type="button" onClick={openCreate} disabled={!activeWebsites.data?.items.length}>
          <Plus /> Register workflow
        </Button>
      </header>

      <FilterBar
        actions={<ResetFiltersButton onReset={() => navigate({ search: DEFAULT_SEARCH })} />}
      >
        <StatusFilter
          value={filters.status}
          onChange={(status) => updateFilters({ status, page: 1 })}
        />
        <FilterField label="Website" htmlFor="website-filter">
          <select
            id="website-filter"
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            value={filters.website_id ?? ''}
            onChange={(e) => updateFilters({ website_id: e.target.value || undefined, page: 1 })}
          >
            <option value="">All websites</option>
            {(activeWebsites.data?.items ?? []).map((w) => (
              <option key={w.id} value={w.id}>
                {w.display_name}
              </option>
            ))}
          </select>
        </FilterField>
        <WithDeletedToggle
          value={filters.with_deleted}
          onChange={(with_deleted) => updateFilters({ with_deleted, page: 1 })}
        />
      </FilterBar>

      <DataTable
        columns={columns}
        rows={workflowsResult.rows}
        isLoading={workflowsResult.isPending}
        isError={workflowsResult.isError}
        errorMessage="Failed to load workflows."
        empty={
          <EmptyState
            title="No workflows yet."
            description={
              activeWebsites.data?.items.length
                ? 'Register a workflow under one of your websites to start scraping.'
                : 'Register a website first, then come back to add workflows.'
            }
            action={
              activeWebsites.data?.items.length
                ? { label: 'Register workflow', onClick: openCreate, icon: <Plus /> }
                : undefined
            }
          />
        }
        pagination={
          filters.website_id
            ? paginationFromListSearch(filters, workflowsResult.total, (next) =>
                updateFilters(next),
              )
            : undefined
        }
      />
      {!filters.website_id && workflowsResult.rows && workflowsResult.rows.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          Showing workflows across every active website. Pick a website filter above to paginate.
        </p>
      ) : null}

      <WorkflowSheet
        state={sheetState}
        websites={activeWebsites.data?.items ?? []}
        onClose={() => setSheetState((prev) => ({ ...prev, open: false }))}
        onSuccess={() => {
          queryClient.invalidateQueries({ queryKey: queryKeys.workflows.all })
        }}
      />

      <DeleteWorkflowDialog
        workflow={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onDeleted={() => {
          queryClient.invalidateQueries({ queryKey: queryKeys.workflows.all })
        }}
      />
    </div>
  )
}

/**
 * Two mode fetch for the workflows list (spec 0009 AC-5):
 * - When `website_id` is set, call the nested endpoint and paginate normally.
 * - When no `website_id` is set, fan out across the active websites and
 *   flatten the first page of each; pagination is hidden because stitching
 *   across websites would mix two unrelated page cursors.
 */
function useWorkflowsList(filters: WorkflowsSearch, activeWebsites: WebsiteRead[] | undefined) {
  const singleWebsiteQuery = useQuery<PaginatedResponse<WorkflowRead>, ApiError>({
    queryKey: queryKeys.workflows.list({ ...filters, mode: 'single' }),
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams()
      qs.set('page', String(filters.page))
      qs.set('page_size', String(filters.page_size))
      if (filters.status) qs.set('status', filters.status)
      if (filters.with_deleted) qs.set('with_deleted', 'true')
      return apiFetch<PaginatedResponse<WorkflowRead>>(
        `/api/v1/websites/${filters.website_id}/workflows?${qs.toString()}`,
        { signal },
      )
    },
    enabled: Boolean(filters.website_id),
  })

  const websiteIds = activeWebsites?.map((w) => w.id) ?? []
  const stitchedQueries = useQueries({
    queries: websiteIds.map((websiteId) => ({
      queryKey: queryKeys.workflows.list({ ...filters, website_id: websiteId, mode: 'stitched' }),
      queryFn: ({ signal }: { signal: AbortSignal }) => {
        const qs = new URLSearchParams()
        qs.set('page', '1')
        qs.set('page_size', '200')
        if (filters.status) qs.set('status', filters.status)
        if (filters.with_deleted) qs.set('with_deleted', 'true')
        return apiFetch<PaginatedResponse<WorkflowRead>>(
          `/api/v1/websites/${websiteId}/workflows?${qs.toString()}`,
          { signal },
        )
      },
      enabled: !filters.website_id && activeWebsites !== undefined,
    })),
  })

  if (filters.website_id) {
    return {
      rows: singleWebsiteQuery.data?.items,
      total: singleWebsiteQuery.data?.total ?? 0,
      isPending: singleWebsiteQuery.isPending,
      isError: singleWebsiteQuery.isError,
      supplementalWebsites: [] as WebsiteRead[],
    }
  }

  const rows: WorkflowRead[] = []
  let isPending = activeWebsites === undefined
  let isError = false
  for (const q of stitchedQueries) {
    if (q.isPending) isPending = true
    if (q.isError) isError = true
    if (q.data) rows.push(...q.data.items)
  }
  return {
    rows: activeWebsites === undefined ? undefined : rows,
    total: rows.length,
    isPending,
    isError,
    supplementalWebsites: [] as WebsiteRead[],
  }
}

function VersionNumber({ id, vid }: { id: string; vid: string }) {
  const q = useQuery<{ version_number: number }, ApiError>({
    queryKey: queryKeys.workflows.versions.detail(id, vid),
    queryFn: ({ signal }) =>
      apiFetch<{ version_number: number }>(`/api/v1/workflows/${id}/versions/${vid}`, { signal }),
    staleTime: 60_000,
  })
  if (q.isPending) return <span className="text-muted-foreground">…</span>
  if (q.isError || !q.data) return <span>—</span>
  return <span>v{q.data.version_number}</span>
}

function StatusBadge({ value }: { value: WorkflowRead['status'] }) {
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
  | { open: boolean; mode: 'edit'; workflow: WorkflowRead }

function WorkflowSheet({
  state,
  websites,
  onClose,
  onSuccess,
}: {
  state: SheetState
  websites: WebsiteRead[]
  onClose: () => void
  onSuccess: () => void
}) {
  const isEdit = state.mode === 'edit'
  const form = useForm<WorkflowFormValues>({
    resolver: zodResolver(workflowFormSchema),
    defaultValues: { name: '', description: '', website_id: '' },
  })

  useEffect(() => {
    if (!state.open) return
    if (state.mode === 'edit') {
      form.reset({
        name: state.workflow.name,
        description: state.workflow.description ?? '',
        website_id: state.workflow.website_id,
      })
    } else {
      form.reset({
        name: '',
        description: '',
        website_id: websites[0]?.id ?? '',
      })
    }
  }, [state, websites, form])

  const mutation = useMutation<WorkflowRead, ApiError, WorkflowFormValues>({
    mutationFn: async (values) => {
      if (state.mode === 'edit') {
        const body: WorkflowUpdateBody = {
          name: values.name,
          description: values.description || null,
        }
        return apiFetch<WorkflowRead>(`/api/v1/workflows/${state.workflow.id}`, {
          method: 'PATCH',
          body: JSON.stringify(body),
          rhfSetError: form.setError as never,
        })
      }
      const body: WorkflowCreateBody = {
        name: values.name,
        description: values.description || null,
      }
      return apiFetch<WorkflowRead>(`/api/v1/websites/${values.website_id}/workflows`, {
        method: 'POST',
        body: JSON.stringify(body),
        rhfSetError: form.setError as never,
      })
    },
    onSuccess: () => {
      toast.success(isEdit ? 'Workflow updated.' : 'Workflow registered.')
      onSuccess()
      onClose()
    },
  })

  const onSubmit = form.handleSubmit((values) => mutation.mutate(values))

  return (
    <CrudSheet
      open={state.open}
      onOpenChange={(next) => (next ? undefined : onClose())}
      title={isEdit ? 'Edit workflow' : 'Register workflow'}
      description={
        isEdit
          ? 'Update the workflow name or description. The parent website is immutable.'
          : 'Add a workflow under a website. You can draft versions and preview extraction after creation.'
      }
      mode={isEdit ? 'edit' : 'create'}
      onSubmit={onSubmit}
      isSubmitting={mutation.isPending}
    >
      <div className="flex flex-col gap-2">
        <Label htmlFor="workflow-website">Website</Label>
        <select
          id="workflow-website"
          disabled={isEdit}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
          {...form.register('website_id')}
        >
          <option value="">Pick a website…</option>
          {websites.map((w) => (
            <option key={w.id} value={w.id}>
              {w.display_name} ({w.host})
            </option>
          ))}
        </select>
        {isEdit ? (
          <p className="text-xs text-muted-foreground">
            Parent website is immutable; create a new workflow under a different website if needed.
          </p>
        ) : null}
        {form.formState.errors.website_id ? (
          <p className="text-xs text-destructive" role="alert">
            {form.formState.errors.website_id.message}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="workflow-name">Name</Label>
        <Input id="workflow-name" {...form.register('name')} />
        {form.formState.errors.name ? (
          <p className="text-xs text-destructive" role="alert">
            {form.formState.errors.name.message}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="workflow-description">Description</Label>
        <Input id="workflow-description" {...form.register('description')} />
      </div>
    </CrudSheet>
  )
}

function DeleteWorkflowDialog({
  workflow,
  onClose,
  onDeleted,
}: {
  workflow: WorkflowRead | null
  onClose: () => void
  onDeleted: () => void
}) {
  const [typed, setTyped] = useState('')
  const [inFlightBanner, setInFlightBanner] = useState<string | null>(null)

  useEffect(() => {
    if (!workflow) {
      setTyped('')
      setInFlightBanner(null)
    }
  }, [workflow])

  const mutation = useMutation<void, ApiError, string>({
    mutationFn: (id) =>
      apiFetch<void>(`/api/v1/workflows/${id}`, { method: 'DELETE', silent: true }),
    onSuccess: () => {
      toast.success('Workflow deleted.')
      onDeleted()
      onClose()
    },
    onError: (error) => {
      if (error.code === 'workflow.has_in_flight_executions') {
        setInFlightBanner(
          error.detail ??
            'One or more executions are pending or running; wait for them to finish before deleting.',
        )
        return
      }
      toast.error(error.detail ?? error.title)
    },
  })

  const canDelete =
    workflow !== null && typed === workflow.name && !mutation.isPending && inFlightBanner === null

  return (
    <AlertDialog
      open={workflow !== null}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete workflow</AlertDialogTitle>
          <AlertDialogDescription>
            Soft deletes <span className="font-mono text-foreground">{workflow?.name}</span> and
            every version under it. Type the workflow name to confirm.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {inFlightBanner ? (
          <div
            className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
            role="alert"
          >
            {inFlightBanner}
          </div>
        ) : null}
        <div className="flex flex-col gap-2">
          <Label htmlFor="delete-workflow-name">Name</Label>
          <Input
            id="delete-workflow-name"
            autoComplete="off"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={workflow?.name ?? ''}
          />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onClose}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={!canDelete}
            onClick={(e) => {
              e.preventDefault()
              if (workflow) mutation.mutate(workflow.id)
            }}
          >
            {mutation.isPending ? 'Deleting…' : 'Delete'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
