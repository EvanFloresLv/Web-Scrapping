import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/_authed/executions')({
  component: () => (
    <div className="p-6">
      <h1 className="text-xl font-semibold">Executions</h1>
      <p className="mt-2 text-sm text-muted-foreground">This screen lands in Feature 11.</p>
    </div>
  ),
})
