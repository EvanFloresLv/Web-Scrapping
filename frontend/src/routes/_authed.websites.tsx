import { createFileRoute } from '@tanstack/react-router'

// Stub for M3; the real list screen lands in M5.
export const Route = createFileRoute('/_authed/websites')({
  component: () => (
    <div className="p-6 text-foreground">
      <h1 className="text-xl font-semibold">Websites</h1>
      <p className="mt-2 text-sm text-muted-foreground">Lands in M5.</p>
    </div>
  ),
})
