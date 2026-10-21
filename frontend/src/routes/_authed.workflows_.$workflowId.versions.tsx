import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { Archive, FilePlus2, Send, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { z } from 'zod'

import { queryKeys } from '@/api/queryKeys'
import type { components } from '@/api/schema'
import { DataTable, type DataTableColumn } from '@/components/data-table'
import { EmptyState } from '@/components/empty-state'
import { FilterBar, FilterField, ResetFiltersButton } from '@/components/filter-bar'
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
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { type ApiError, apiFetch } from '@/lib/api'
import { pageSchema, pageSizeSchema, withDeletedSchema } from '@/lib/listSearch'
import type { PaginatedResponse } from '@/lib/useListQuery'

type WorkflowRead = components['schemas']['WorkflowRead']
type WorkflowVersionRead = components['schemas']['WorkflowVersionRead']
type WorkflowVersionStatus = components['schemas']['WorkflowVersionStatus']

/**
 * Versions tab (spec 0009 M4 / AC-9, AC-14, AC-15, AC-16).
 *
 * Lists `workflow_versions` under a workflow, URL-synced status filter plus
 * pagination, per-row lifecycle actions (Publish draft, Archive published,
 * Delete draft). Every known 409 from spec 0004 (`version_conflict`,
 * `version_is_current`, `version_not_published`, `version_not_draft`) renders
 * as a specific banner inside the matching dialog or Sheet, triggers a
 * refetch, and keeps the dialog open with Confirm disabled.
 */

const versionStatusSchema = z
  .union([z.literal('draft'), z.literal('published'), z.literal('archived')])
  .optional()
  .catch(undefined)

const versionsSearchSchema = z.object({
  page: pageSchema,
  page_size: pageSizeSchema,
  status: versionStatusSchema,
  with_deleted: withDeletedSchema,
})
type VersionsSearch = z.infer<typeof versionsSearchSchema>

const DEFAULT_SEARCH: VersionsSearch = {
  page: 1,
  page_size: 50,
  with_deleted: false,
  status: undefined,
}

export const Route = createFileRoute('/_authed/workflows_/$workflowId/versions')({
  validateSearch: (search) => versionsSearchSchema.parse(search),
  component: VersionsTab,
})

function VersionsTab() {
  const { workflowId } = Route.useParams()
  const filters = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const queryClient = useQueryClient()

  const [publishTarget, setPublishTarget] = useState<WorkflowVersionRead | null>(null)
  const [archiveTarget, setArchiveTarget] = useState<WorkflowVersionRead | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<WorkflowVersionRead | null>(null)

  const workflow = useQuery<WorkflowRead, ApiError>({
    queryKey: queryKeys.workflows.detail(workflowId),
    queryFn: ({ signal }) =>
      apiFetch<WorkflowRead>(`/api/v1/workflows/${workflowId}`, { signal, silent: true }),
    retry: false,
  })

  const versions = useQuery<PaginatedResponse<WorkflowVersionRead>, ApiError>({
    queryKey: queryKeys.workflows.versions.list(workflowId, filters),
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams()
      qs.set('page', String(filters.page))
      qs.set('page_size', String(filters.page_size))
      if (filters.status) qs.set('status', filters.status)
      if (filters.with_deleted) qs.set('with_deleted', 'true')
      return apiFetch<PaginatedResponse<WorkflowVersionRead>>(
        `/api/v1/workflows/${workflowId}/versions?${qs.toString()}`,
        { signal },
      )
    },
  })

  const updateFilters = (next: Partial<VersionsSearch>) => {
    navigate({ search: (prev) => ({ ...prev, ...next }) })
  }

  const openNewDraft = () => {
    navigate({ to: '/workflows/$workflowId/versions/new', params: { workflowId } })
  }

  const invalidateVersions = () => {
    queryClient.invalidateQueries({ queryKey: ['workflows', workflowId, 'versions'] })
    queryClient.invalidateQueries({ queryKey: queryKeys.workflows.detail(workflowId) })
  }

  const currentVersionId = workflow.data?.current_version_id ?? null

  const columns: DataTableColumn<WorkflowVersionRead>[] = [
    {
      key: 'version',
      header: 'Version',
      cell: (row) => (
        <span className="font-medium">
          <Link
            to="/workflows/$workflowId/versions/$versionId"
            params={{ workflowId, versionId: row.id }}
            className="text-primary hover:underline"
          >
            v{row.version_number}
          </Link>
          {currentVersionId === row.id ? (
            <span className="ml-2 rounded-full bg-primary/15 px-2 py-0.5 text-xs text-primary">
              current
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (row) => <VersionStatusBadge value={row.status} />,
    },
    {
      key: 'published_at',
      header: 'Published',
      cell: (row) => (row.published_at ? formatDate(row.published_at) : '—'),
      className: 'text-muted-foreground',
    },
    {
      key: 'archived_at',
      header: 'Archived',
      cell: (row) => (row.archived_at ? formatDate(row.archived_at) : '—'),
      className: 'text-muted-foreground',
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
        <RowActions
          version={row}
          isCurrent={currentVersionId === row.id}
          onPublish={() => setPublishTarget(row)}
          onArchive={() => setArchiveTarget(row)}
          onDelete={() => setDeleteTarget(row)}
        />
      ),
    },
  ]

  return (
    <div className="space-y-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Versions</h2>
          <p className="text-sm text-muted-foreground">
            Draft, publish, archive, and delete configuration versions of this workflow.
          </p>
        </div>
        <Button type="button" onClick={openNewDraft}>
          <FilePlus2 /> New draft
        </Button>
      </header>

      <FilterBar
        actions={<ResetFiltersButton onReset={() => navigate({ search: DEFAULT_SEARCH })} />}
      >
        <FilterField label="Status" htmlFor="version-status">
          <select
            id="version-status"
            className="h-9 rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            value={filters.status ?? ''}
            onChange={(event) => {
              const next = event.target.value
              updateFilters({
                status: next === '' ? undefined : (next as WorkflowVersionStatus),
                page: 1,
              })
            }}
          >
            <option value="">All</option>
            <option value="draft">Draft</option>
            <option value="published">Published</option>
            <option value="archived">Archived</option>
          </select>
        </FilterField>
      </FilterBar>

      <DataTable
        columns={columns}
        rows={versions.data?.items}
        isLoading={versions.isPending}
        isError={versions.isError}
        errorMessage="Failed to load versions."
        empty={
          <EmptyState
            title="No versions yet."
            description="Create a draft to start authoring this workflow's configuration."
            action={{ label: 'New draft', onClick: openNewDraft, icon: <FilePlus2 /> }}
          />
        }
        pagination={{
          page: filters.page,
          pageSize: filters.page_size,
          total: versions.data?.total ?? 0,
          onChange: ({ page, page_size }) => updateFilters({ page, page_size }),
        }}
      />

      <PublishDialog
        workflowId={workflowId}
        version={publishTarget}
        onClose={() => setPublishTarget(null)}
        onSettled={invalidateVersions}
      />
      <ArchiveDialog
        workflowId={workflowId}
        version={archiveTarget}
        isCurrent={archiveTarget !== null && currentVersionId === archiveTarget.id}
        onClose={() => setArchiveTarget(null)}
        onSettled={invalidateVersions}
      />
      <DeleteDraftDialog
        workflowId={workflowId}
        version={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onSettled={invalidateVersions}
      />
    </div>
  )
}

function RowActions({
  version,
  isCurrent,
  onPublish,
  onArchive,
  onDelete,
}: {
  version: WorkflowVersionRead
  isCurrent: boolean
  onPublish: () => void
  onArchive: () => void
  onDelete: () => void
}) {
  if (version.status === 'draft') {
    return (
      <div className="flex justify-end gap-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onPublish}
          aria-label={`Publish version ${version.version_number}`}
        >
          <Send /> Publish
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onDelete}
          aria-label={`Delete draft ${version.version_number}`}
        >
          <Trash2 />
        </Button>
      </div>
    )
  }
  if (version.status === 'published') {
    return (
      <div className="flex justify-end">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={isCurrent}
          title={
            isCurrent
              ? 'Publish a replacement first; archiving the current version would leave the workflow with no runnable version.'
              : undefined
          }
          onClick={onArchive}
          aria-label={`Archive version ${version.version_number}`}
        >
          <Archive /> Archive
        </Button>
      </div>
    )
  }
  return <span className="text-xs text-muted-foreground">—</span>
}

/**
 * Publish Sheet (spec 0009 AC-14). Handles the 409
 * `workflow.version_conflict` race by swapping the body for a Reload button
 * that refetches the versions list and closes the Sheet; the local draft is
 * not re-POSTed on reload.
 */
function PublishDialog({
  workflowId,
  version,
  onClose,
  onSettled,
}: {
  workflowId: string
  version: WorkflowVersionRead | null
  onClose: () => void
  onSettled: () => void
}) {
  const queryClient = useQueryClient()
  const [conflict, setConflict] = useState<string | null>(null)

  useEffect(() => {
    if (!version) setConflict(null)
  }, [version])

  const mutation = useMutation<WorkflowVersionRead, ApiError, string>({
    mutationFn: (versionId) =>
      apiFetch<WorkflowVersionRead>(
        `/api/v1/workflows/${workflowId}/versions/${versionId}/publish`,
        { method: 'POST', silent: true },
      ),
    onSuccess: () => {
      toast.success('Version published.')
      onSettled()
      onClose()
    },
    onError: (error) => {
      if (error.code === 'workflow.version_conflict') {
        setConflict(
          error.detail ?? 'Another operator changed this workflow. Reload to see the latest state.',
        )
        return
      }
      toast.error(error.detail ?? error.title)
    },
  })

  const handleReload = () => {
    queryClient.invalidateQueries({ queryKey: ['workflows', workflowId, 'versions'] })
    queryClient.invalidateQueries({ queryKey: queryKeys.workflows.detail(workflowId) })
    onClose()
  }

  return (
    <Sheet
      open={version !== null}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <SheetContent side="right" className="w-full gap-4 sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Publish version</SheetTitle>
          <SheetDescription>
            Promote this draft to published. If there is a current published version, it is archived
            in the same transaction. The workflow's current version pointer will swap to this one.
          </SheetDescription>
        </SheetHeader>
        <div className="px-4 text-sm">
          <p>
            Draft to publish: <span className="font-medium">v{version?.version_number ?? '…'}</span>
          </p>
        </div>
        {conflict ? (
          <div
            className="mx-4 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
            role="alert"
          >
            {conflict}
          </div>
        ) : null}
        <SheetFooter className="flex-row justify-end gap-2">
          <SheetClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </SheetClose>
          {conflict ? (
            <Button type="button" onClick={handleReload}>
              Reload
            </Button>
          ) : (
            <Button
              type="button"
              disabled={!version || mutation.isPending}
              onClick={() => {
                if (version) mutation.mutate(version.id)
              }}
            >
              {mutation.isPending ? 'Publishing…' : 'Publish'}
            </Button>
          )}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

/**
 * Archive confirm dialog (spec 0009 AC-15). Disabled on the current version
 * (handled at the row level); still handles a race where the server returns
 * 409 `workflow.version_is_current` or `workflow.version_not_published` by
 * rendering the specific error and refetching the list.
 */
function ArchiveDialog({
  workflowId,
  version,
  isCurrent,
  onClose,
  onSettled,
}: {
  workflowId: string
  version: WorkflowVersionRead | null
  isCurrent: boolean
  onClose: () => void
  onSettled: () => void
}) {
  const [conflict, setConflict] = useState<string | null>(null)

  useEffect(() => {
    if (!version) setConflict(null)
  }, [version])

  const mutation = useMutation<WorkflowVersionRead, ApiError, string>({
    mutationFn: (versionId) =>
      apiFetch<WorkflowVersionRead>(
        `/api/v1/workflows/${workflowId}/versions/${versionId}/archive`,
        { method: 'POST', silent: true },
      ),
    onSuccess: () => {
      toast.success('Version archived.')
      onSettled()
      onClose()
    },
    onError: (error) => {
      if (
        error.code === 'workflow.version_is_current' ||
        error.code === 'workflow.version_not_published'
      ) {
        setConflict(error.detail ?? error.title)
        onSettled()
        return
      }
      toast.error(error.detail ?? error.title)
    },
  })

  const canArchive = version !== null && !isCurrent && conflict === null && !mutation.isPending

  return (
    <AlertDialog
      open={version !== null}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Archive version</AlertDialogTitle>
          <AlertDialogDescription>
            Archive v{version?.version_number ?? '…'}. Archived versions become read only and cannot
            be published or executed again.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {isCurrent ? (
          <div
            className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
            role="alert"
          >
            Publish a replacement first; archiving the current version would leave the workflow with
            no runnable version.
          </div>
        ) : null}
        {conflict ? (
          <div
            className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
            role="alert"
          >
            {conflict}
          </div>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onClose}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={!canArchive}
            onClick={(e) => {
              e.preventDefault()
              if (version) mutation.mutate(version.id)
            }}
          >
            {mutation.isPending ? 'Archiving…' : 'Archive'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/**
 * Delete draft confirm dialog (spec 0009 AC-16). Plain confirm (no
 * type-to-confirm; drafts are safer than workflow-level deletes). Handles
 * 409 `workflow.version_not_draft` by rendering the specific banner and
 * refetching.
 */
function DeleteDraftDialog({
  workflowId,
  version,
  onClose,
  onSettled,
}: {
  workflowId: string
  version: WorkflowVersionRead | null
  onClose: () => void
  onSettled: () => void
}) {
  const [conflict, setConflict] = useState<string | null>(null)

  useEffect(() => {
    if (!version) setConflict(null)
  }, [version])

  const mutation = useMutation<void, ApiError, string>({
    mutationFn: (versionId) =>
      apiFetch<void>(`/api/v1/workflows/${workflowId}/versions/${versionId}`, {
        method: 'DELETE',
        silent: true,
      }),
    onSuccess: () => {
      toast.success('Draft deleted.')
      onSettled()
      onClose()
    },
    onError: (error) => {
      if (error.code === 'workflow.version_not_draft') {
        setConflict(error.detail ?? 'Only draft versions can be deleted.')
        onSettled()
        return
      }
      toast.error(error.detail ?? error.title)
    },
  })

  const canDelete = version !== null && conflict === null && !mutation.isPending

  return (
    <AlertDialog
      open={version !== null}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete draft</AlertDialogTitle>
          <AlertDialogDescription>
            Hard delete draft v{version?.version_number ?? '…'}. This cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {conflict ? (
          <div
            className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
            role="alert"
          >
            {conflict}
          </div>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onClose}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={!canDelete}
            onClick={(e) => {
              e.preventDefault()
              if (version) mutation.mutate(version.id)
            }}
          >
            {mutation.isPending ? 'Deleting…' : 'Delete'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function VersionStatusBadge({ value }: { value: WorkflowVersionStatus }) {
  const tone =
    value === 'published'
      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
      : value === 'draft'
        ? 'bg-amber-500/15 text-amber-700 dark:text-amber-300'
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
