import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link, Outlet } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'

import { queryKeys } from '@/api/queryKeys'
import type { components } from '@/api/schema'
import { type ApiError, apiFetch } from '@/lib/api'
import { cn } from '@/lib/utils'

type WorkflowRead = components['schemas']['WorkflowRead']

/**
 * Workflow detail layout (spec 0009 AC-7). Three tabs live under this parent
 * as nested routes so the active tab lives in the URL: `/overview`,
 * `/versions`, `/preview`. The bare `/workflows/:id` index route redirects to
 * `/overview`.
 */
export const Route = createFileRoute('/_authed/workflows_/$workflowId')({
  component: WorkflowLayout,
})

const TABS = [
  { to: '/workflows/$workflowId/overview', label: 'Overview' },
  { to: '/workflows/$workflowId/versions', label: 'Versions' },
  { to: '/workflows/$workflowId/preview', label: 'Preview' },
] as const

function WorkflowLayout() {
  const { workflowId } = Route.useParams()
  const workflow = useQuery<WorkflowRead, ApiError>({
    queryKey: queryKeys.workflows.detail(workflowId),
    queryFn: ({ signal }) =>
      apiFetch<WorkflowRead>(`/api/v1/workflows/${workflowId}`, { signal, silent: true }),
    retry: false,
  })

  return (
    <div className="flex min-h-full flex-col">
      <div className="border-b bg-background px-6 pt-6">
        <Link
          to="/workflows"
          search={{ page: 1, page_size: 50, with_deleted: false }}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back to workflows
        </Link>
        <h1 className="mt-3 text-xl font-semibold">
          {workflow.data?.name ?? (workflow.isPending ? 'Loading…' : 'Workflow')}
        </h1>
        <nav className="mt-4 flex gap-1" aria-label="Workflow tabs">
          {TABS.map((tab) => (
            <Link
              key={tab.to}
              to={tab.to}
              params={{ workflowId }}
              className={cn(
                'rounded-t-md border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground',
                '[&.active]:border-primary [&.active]:text-foreground',
              )}
              activeProps={{ className: 'active' }}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
      </div>
      <div className="flex-1">
        <Outlet />
      </div>
    </div>
  )
}
