import { createFileRoute } from '@tanstack/react-router'

import { EmptyState } from '@/components/empty-state'

/**
 * Placeholder for the Versions tab. The full implementation (lifecycle
 * actions, 409 handlers, editor route) lands in milestones 4 and 5.
 */
export const Route = createFileRoute('/_authed/workflows_/$workflowId/versions')({
  component: VersionsPlaceholder,
})

function VersionsPlaceholder() {
  return (
    <div className="p-6">
      <EmptyState
        title="Versions tab lands in milestone 4."
        description="Draft creation, publish, archive, and delete actions arrive next."
      />
    </div>
  )
}
