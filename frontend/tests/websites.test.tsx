import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { createElement, type ReactElement, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
  Toaster: () => null,
}))
vi.mock('@tanstack/react-router', async () => {
  const actual =
    await vi.importActual<typeof import('@tanstack/react-router')>('@tanstack/react-router')
  return {
    ...actual,
    createFileRoute: () => (opts: unknown) => opts,
    useNavigate: () => vi.fn(),
    Link: ({ children, className }: { children: ReactNode; className?: string }) =>
      createElement('a', { href: '#', className }, children),
  }
})

async function loadRoute() {
  const mod = (await import('@/routes/_authed.websites')) as unknown as {
    Route: {
      component: () => ReactElement
      useSearch: () => { page: 1; page_size: 50; with_deleted: false }
    }
  }
  mod.Route.useSearch = () => ({ page: 1, page_size: 50, with_deleted: false })
  return mod.Route.component
}

describe('/websites screen', () => {
  beforeEach(() => {
    useAuthStore.setState({ apiKey: 'test-key', isSignedIn: true })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.resetModules()
  })

  it('renders the empty state card when the list is empty (AC-1, AC-19)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 50 }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )

    const Page = await loadRoute()
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <Page />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(screen.getByText(/No websites registered yet/i)).toBeInTheDocument())
    // Both the header button and the empty state CTA render a Register website button.
    const registerButtons = screen.getAllByRole('button', { name: /Register website/i })
    expect(registerButtons.length).toBeGreaterThanOrEqual(2)
  })

  it('keeps Delete disabled until the host is typed in the confirmation dialog (AC-2)', async () => {
    const site = {
      id: '00000000-0000-7000-8000-000000000001',
      host: 'example.com',
      display_name: 'Example',
      status: 'active' as const,
      created_at: '2026-10-21T12:00:00Z',
      updated_at: '2026-10-21T12:00:00Z',
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [site], total: 1, page: 1, page_size: 50 }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )

    const Page = await loadRoute()
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={qc}>
        <Page />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(screen.getByText('example.com')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Delete example.com/i }))

    const dialog = await screen.findByRole('alertdialog')
    const deleteButton = screen.getByRole('button', { name: /^Delete$/ })
    expect(deleteButton).toBeDisabled()

    const input = screen.getByLabelText(/^Host$/, { selector: 'input' })
    await user.type(input, 'example.com')
    expect(deleteButton).toBeEnabled()
    expect(dialog).toBeInTheDocument()
  })
})
