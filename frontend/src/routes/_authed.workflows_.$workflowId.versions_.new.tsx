import { createFileRoute } from '@tanstack/react-router'

import { VersionEditor } from '@/components/version-editor'

/**
 * Version editor on the provisional "new draft" path (spec 0009 AC-9 / M5).
 * No POST runs on route entry; the editor's First Save creates the row and
 * then navigates to `/workflows/:workflowId/versions/:versionId` so later
 * saves PATCH the created row.
 */
export const Route = createFileRoute('/_authed/workflows_/$workflowId/versions_/new')({
  component: NewVersionRoute,
})

function NewVersionRoute() {
  const { workflowId } = Route.useParams()
  return <VersionEditor mode={{ kind: 'new', workflowId }} />
}
