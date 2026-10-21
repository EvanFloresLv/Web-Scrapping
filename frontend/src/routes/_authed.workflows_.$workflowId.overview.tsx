import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { toast } from 'sonner'

import { queryKeys } from '@/api/queryKeys'
import type { components } from '@/api/schema'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { type ApiError, apiFetch } from '@/lib/api'

type WorkflowRead = components['schemas']['WorkflowRead']
type WorkflowVersionRead = { id: string; version_number: number; status: string }
type WebsiteRead = components['schemas']['WebsiteRead']
type WorkflowUpdateBody = components['schemas']['WorkflowUpdate']

export const Route = createFileRoute('/_authed/workflows_/$workflowId/overview')({
  component: OverviewTab,
})

function OverviewTab() {
  const { workflowId } = Route.useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const workflow = useQuery<WorkflowRead, ApiError>({
    queryKey: queryKeys.workflows.detail(workflowId),
    queryFn: ({ signal }) =>
      apiFetch<WorkflowRead>(`/api/v1/workflows/${workflowId}`, { signal, silent: true }),
    retry: false,
  })

  // AC-3 style: route the user back to the list on 404.
  useEffect(() => {
    const err = workflow.error
    if (!err) return
    if (err.status === 404) {
      toast.error('Workflow not found or has been deleted.')
      navigate({ to: '/workflows', search: { page: 1, page_size: 50, with_deleted: false } })
    } else {
      toast.error(err.title)
    }
  }, [workflow.error, navigate])

  const website = useQuery<WebsiteRead, ApiError>({
    queryKey: queryKeys.websites.detail(workflow.data?.website_id ?? ''),
    queryFn: ({ signal }) =>
      apiFetch<WebsiteRead>(`/api/v1/websites/${workflow.data?.website_id}`, { signal }),
    enabled: Boolean(workflow.data?.website_id),
  })

  const currentVersion = useQuery<WorkflowVersionRead, ApiError>({
    queryKey: queryKeys.workflows.versions.detail(
      workflowId,
      workflow.data?.current_version_id ?? '',
    ),
    queryFn: ({ signal }) =>
      apiFetch<WorkflowVersionRead>(
        `/api/v1/workflows/${workflowId}/versions/${workflow.data?.current_version_id}`,
        { signal },
      ),
    enabled: Boolean(workflow.data?.current_version_id),
  })

  // AC-8: optimistic status toggle with rollback on error and invalidation on settle.
  const toggleStatus = useMutation<WorkflowRead, ApiError, 'active' | 'inactive'>({
    mutationFn: (nextStatus) => {
      const body: WorkflowUpdateBody = { status: nextStatus }
      return apiFetch<WorkflowRead>(`/api/v1/workflows/${workflowId}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
        silent: true,
      })
    },
    onMutate: async (nextStatus) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.workflows.detail(workflowId) })
      const previous = queryClient.getQueryData<WorkflowRead>(
        queryKeys.workflows.detail(workflowId),
      )
      if (previous) {
        queryClient.setQueryData<WorkflowRead>(queryKeys.workflows.detail(workflowId), {
          ...previous,
          status: nextStatus,
        })
      }
      return { previous }
    },
    onError: (error, _nextStatus, context) => {
      const prev = (context as { previous?: WorkflowRead } | undefined)?.previous
      if (prev) {
        queryClient.setQueryData(queryKeys.workflows.detail(workflowId), prev)
      }
      const suffix = error.correlationId ? ` (correlation ${error.correlationId})` : ''
      toast.error(`${error.title}${suffix}`)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.detail(workflowId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.all })
    },
  })

  if (workflow.isPending) {
    return <p className="p-6 text-sm text-muted-foreground">Loading…</p>
  }
  if (!workflow.data) {
    return null
  }
  const wf = workflow.data
  const nextStatus: 'active' | 'inactive' = wf.status === 'active' ? 'inactive' : 'active'

  return (
    <div className="space-y-6 p-6">
      <Card>
        <CardHeader>
          <CardTitle>Metadata</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm sm:grid-cols-2">
          <Metadata label="Name" value={wf.name} />
          <Metadata
            label="Status"
            value={
              <div className="flex items-center gap-2">
                <StatusBadge value={wf.status} />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={toggleStatus.isPending}
                  onClick={() => toggleStatus.mutate(nextStatus)}
                  aria-label={`Set workflow ${nextStatus}`}
                >
                  Set {nextStatus}
                </Button>
              </div>
            }
          />
          <Metadata
            label="Website"
            value={
              website.data ? (
                <Link
                  to="/websites/$websiteId"
                  params={{ websiteId: website.data.id }}
                  search={{ page: 1, page_size: 50, with_deleted: false }}
                  className="text-primary hover:underline"
                >
                  {website.data.display_name}
                </Link>
              ) : (
                <span className="text-muted-foreground">…</span>
              )
            }
          />
          <Metadata
            label="Current version"
            value={
              wf.current_version_id ? (
                currentVersion.data ? (
                  <span>v{currentVersion.data.version_number}</span>
                ) : (
                  <span className="text-muted-foreground">…</span>
                )
              ) : (
                <span className="text-muted-foreground">No published version yet</span>
              )
            }
          />
          <Metadata label="Description" value={wf.description ?? '—'} />
          <Metadata label="Created" value={formatDate(wf.created_at)} />
          <Metadata label="Updated" value={formatDate(wf.updated_at)} />
        </CardContent>
      </Card>
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
