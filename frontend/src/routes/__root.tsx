import type { QueryClient } from '@tanstack/react-query'
import { QueryClient as QueryClientCtor } from '@tanstack/react-query'
import { createRootRouteWithContext, Outlet } from '@tanstack/react-router'
import { Toaster } from 'sonner'

import { ThemeApplier } from '@/stores/theme'

export type RouterContext = {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
  errorComponent: RootErrorBoundary,
})

function RootComponent() {
  return (
    <>
      <ThemeApplier />
      <Outlet />
      <Toaster richColors position="top-right" />
    </>
  )
}

function RootErrorBoundary({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : 'Unknown error'
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-8 text-foreground">
      <div className="max-w-md space-y-3 text-center">
        <h1 className="text-xl font-semibold">Something went wrong</h1>
        <p className="text-sm text-muted-foreground">{message}</p>
      </div>
    </div>
  )
}

export function createRouterContext(): RouterContext {
  return {
    queryClient: new QueryClientCtor({
      defaultOptions: {
        queries: { retry: false, refetchOnWindowFocus: false },
      },
    }),
  }
}
