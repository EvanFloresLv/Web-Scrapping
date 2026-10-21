import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'

vi.mock('sonner', () => ({ toast: { error: vi.fn() }, Toaster: () => null }))
vi.mock('@tanstack/react-router', async () => {
  const actual =
    await vi.importActual<typeof import('@tanstack/react-router')>('@tanstack/react-router')
  return {
    ...actual,
    createFileRoute: () => (opts: unknown) => opts,
  }
})

describe('/websites screen', () => {
  beforeEach(() => {
    useAuthStore.setState({ apiKey: 'test-key', isSignedIn: true })
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the empty state card when the list is empty (AC-6)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 50 }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )

    const mod = (await import('@/routes/_authed.websites')) as unknown as {
      Route: { component: () => JSX.Element }
    }
    const Page = mod.Route.component

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <Page />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(screen.getByText(/No websites registered yet/i)).toBeInTheDocument())
  })
})
