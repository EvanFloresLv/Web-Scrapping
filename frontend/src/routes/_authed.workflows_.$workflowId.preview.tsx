import { createFileRoute } from '@tanstack/react-router'

import { EmptyState } from '@/components/empty-state'

/**
 * Placeholder for the Preview tab. The full editor + preview panel lands in
 * milestones 5 and 6.
 */
export const Route = createFileRoute('/_authed/workflows_/$workflowId/preview')({
  component: PreviewPlaceholder,
})

function PreviewPlaceholder() {
  return (
    <div className="p-6">
      <EmptyState
        title="Preview tab lands in milestone 6."
        description="The editor and preview panel ship together once the version editor is in place."
      />
    </div>
  )
}
