import { createFileRoute, Link } from '@tanstack/react-router'

import { EmptyState } from '@/components/empty-state'
import { Button } from '@/components/ui/button'

/**
 * Placeholder for the version editor (new draft path), spec 0009 M5. For now
 * the versions tab (M4) navigates here so the "+ New draft" flow is wired;
 * the actual CodeMirror editor and First-Save POST land in milestone 5.
 */
export const Route = createFileRoute('/_authed/workflows_/$workflowId/versions_/new')({
  component: NewDraftPlaceholder,
})

function NewDraftPlaceholder() {
  const { workflowId } = Route.useParams()
  return (
    <div className="space-y-4 p-6">
      <EmptyState
        title="Version editor lands in milestone 5."
        description="The structured form, CodeMirror panes, and first-save POST are coming next."
      />
      <Button asChild variant="outline">
        <Link
          to="/workflows/$workflowId/versions"
          params={{ workflowId }}
          search={{ page: 1, page_size: 50, with_deleted: false, status: undefined }}
        >
          Back to versions
        </Link>
      </Button>
    </div>
  )
}
