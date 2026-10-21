import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/_authed/targets')({
  component: () => (
    <div className="p-6">
      <h1 className="text-xl font-semibold">Targets</h1>
      <p className="mt-2 text-sm text-muted-foreground">Lands in M5.</p>
    </div>
  ),
})
