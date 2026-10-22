import { createFileRoute } from '@tanstack/react-router'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export const Route = createFileRoute('/_authed/targets')({
  component: TargetsPage,
})

/**
 * Spec 0008 AC-6 asks for `GET /api/v1/targets`, but the backend exposes
 * targets only under a parent website (`/api/v1/websites/{id}/targets`).
 * This screen renders the empty state card today and will be upgraded
 * when either (a) a top level `/targets` list lands on the backend or
 * (b) Feature 10 adds a website picker that scopes the list. Deviation
 * recorded in the scope.
 */
function TargetsPage() {
  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-xl font-semibold">Targets</h1>
        <p className="text-sm text-muted-foreground">Registered target URLs under each website.</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>No targets to list here yet.</CardTitle>
          <CardDescription>
            Targets live under a website today. Register one via{' '}
            <code>POST /api/v1/websites/&#123;website_id&#125;/targets</code>, then open the website
            detail screen (lands in Feature 10) to see its targets.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          A top level cross website list is a backend follow up; the admin UI will light up this
          screen the moment it is available.
        </CardContent>
      </Card>
    </div>
  )
}
