import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { queryKeys } from '@/api/queryKeys'
import type { components } from '@/api/schema'
import { VersionEditor } from '@/components/version-editor'
import { type ApiError, apiFetch } from '@/lib/api'

type WorkflowVersionRead = components['schemas']['WorkflowVersionRead']

/**
 * Version editor for an existing row (spec 0009 AC-10, AC-12). Loads the
 * version via its stable query key and hands it to `VersionEditor`, which
 * owns the RHF form, dirty state, `useBlocker` guard, and the full-config
 * PATCH on Save. Non-draft rows render read only.
 */
export const Route = createFileRoute('/_authed/workflows_/$workflowId/versions_/$versionId')({
  component: EditVersionRoute,
})

function EditVersionRoute() {
  const { workflowId, versionId } = Route.useParams()
  const version = useQuery<WorkflowVersionRead, ApiError>({
    queryKey: queryKeys.workflows.versions.detail(workflowId, versionId),
    queryFn: ({ signal }) =>
      apiFetch<WorkflowVersionRead>(`/api/v1/workflows/${workflowId}/versions/${versionId}`, {
        signal,
        silent: true,
      }),
    retry: false,
  })

  if (version.isPending) {
    return <p className="p-6 text-sm text-muted-foreground">Loading…</p>
  }
  if (version.isError || !version.data) {
    return (
      <p className="p-6 text-sm text-destructive" role="alert">
        Failed to load version.
      </p>
    )
  }
  return <VersionEditor mode={{ kind: 'edit', workflowId, version: version.data }} />
}
