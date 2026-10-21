import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
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

/**
 * covers:
 *  - AC-14: Publish 409 `workflow.version_conflict` renders a Sheet banner
 *    with a Reload button that refetches and closes the dialog; the local
 *    draft is not re-POSTed.
 *  - AC-15: Archive is disabled on the workflow's current published version
 *    with the explanatory tooltip.
 *  - AC-19: Empty state card renders with the New draft call to action.
 */

const WORKFLOW = {
  id: '11111111-1111-7111-8111-111111111111',
  website_id: '22222222-2222-7222-8222-222222222222',
  name: 'My workflow',
  description: null,
  status: 'active' as const,
  current_version_id: 'vvvvvvvv-vvvv-7vvv-8vvv-vvvvvvvvvvv2',
  created_at: '2026-10-21T12:00:00Z',
  updated_at: '2026-10-21T12:00:00Z',
  deleted_at: null,
}

const DRAFT_VERSION = {
  id: 'dddddddd-dddd-7ddd-8ddd-dddddddddddd',
  workflow_id: WORKFLOW.id,
  version_number: 2,
  status: 'draft' as const,
  config: { container_selector: 'body', fields: [], output_schema: {} },
  published_at: null,
  archived_at: null,
  created_at: '2026-10-21T12:00:00Z',
  updated_at: '2026-10-21T12:00:00Z',
}
const PUBLISHED_CURRENT = {
  id: WORKFLOW.current_version_id,
  workflow_id: WORKFLOW.id,
  version_number: 1,
  status: 'published' as const,
  config: {},
  published_at: '2026-10-21T12:00:00Z',
  archived_at: null,
  created_at: '2026-10-21T12:00:00Z',
  updated_at: '2026-10-21T12:00:00Z',
}

type FetchFn = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'content-type': 'application/json', ...(init.headers ?? {}) },
  })
}

function problemResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/problem+json' },
  })
}

async function loadVersionsRoute() {
  const mod = (await import('@/routes/_authed.workflows_.$workflowId.versions')) as unknown as {
    Route: {
      component: () => ReactElement
      useParams: () => { workflowId: string }
      useSearch: () => { page: 1; page_size: 50; with_deleted: false; status: undefined }
    }
  }
  mod.Route.useParams = () => ({ workflowId: WORKFLOW.id })
  mod.Route.useSearch = () => ({
    page: 1,
    page_size: 50,
    with_deleted: false,
    status: undefined,
  })
  return mod.Route.component
}

function withClient(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('versions tab', () => {
  beforeEach(() => {
    useAuthStore.setState({ apiKey: 'test-key', isSignedIn: true })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.resetModules()
  })

  it('renders empty state with "New draft" when no versions exist (AC-19)', async () => {
    const fetchMock = vi.fn<FetchFn>(async (input) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/versions')) {
        return jsonResponse({ items: [], total: 0, page: 1, page_size: 50 })
      }
      return jsonResponse(WORKFLOW)
    })
    vi.stubGlobal('fetch', fetchMock)

    const Page = await loadVersionsRoute()
    render(withClient(<Page />))

    await waitFor(() => {
      expect(screen.getByText(/No versions yet/i)).toBeInTheDocument()
    })
    const draftButtons = screen.getAllByRole('button', { name: /New draft/i })
    expect(draftButtons.length).toBeGreaterThanOrEqual(2)
  })

  it('disables Archive on the current published version with a tooltip (AC-15)', async () => {
    const fetchMock = vi.fn<FetchFn>(async (input) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/versions')) {
        return jsonResponse({
          items: [PUBLISHED_CURRENT],
          total: 1,
          page: 1,
          page_size: 50,
        })
      }
      return jsonResponse(WORKFLOW)
    })
    vi.stubGlobal('fetch', fetchMock)

    const Page = await loadVersionsRoute()
    render(withClient(<Page />))

    const archive = await screen.findByRole('button', { name: /Archive version 1/i })
    expect(archive).toBeDisabled()
    expect(archive.getAttribute('title')).toMatch(/Publish a replacement first/i)
  })

  it('surfaces a Reload banner on 409 version_conflict without re-POSTing (AC-14)', async () => {
    const postCalls: string[] = []
    const fetchMock = vi.fn<FetchFn>(async (input, init) => {
      const url = typeof input === 'string' ? input : input.toString()
      const method = (init?.method ?? 'GET').toUpperCase()
      if (method === 'POST' && url.endsWith('/publish')) {
        postCalls.push(url)
        return problemResponse(409, {
          title: 'Conflict',
          status: 409,
          code: 'workflow.version_conflict',
          detail: 'Another operator changed this workflow. Reload to see the latest state.',
        })
      }
      if (url.includes('/versions')) {
        return jsonResponse({
          items: [DRAFT_VERSION],
          total: 1,
          page: 1,
          page_size: 50,
        })
      }
      return jsonResponse(WORKFLOW)
    })
    vi.stubGlobal('fetch', fetchMock)

    const user = userEvent.setup()
    const Page = await loadVersionsRoute()
    render(withClient(<Page />))

    const publishButton = await screen.findByRole('button', { name: /Publish version 2/i })
    await user.click(publishButton)

    const sheet = await screen.findByText(/Promote this draft to published/i)
    const sheetContainer =
      sheet.closest('div[role="dialog"], [data-slot="sheet-content"]') ?? sheet.parentElement
    if (!sheetContainer) throw new Error('publish sheet container not found')
    const confirmButton = within(sheetContainer as HTMLElement).getByRole('button', {
      name: /^Publish$/,
    })
    await user.click(confirmButton)

    await waitFor(() =>
      expect(screen.getByText(/Reload to see the latest state/i)).toBeInTheDocument(),
    )
    expect(postCalls).toHaveLength(1)

    const reload = screen.getByRole('button', { name: /Reload/i })
    await user.click(reload)

    // Clicking Reload must NOT re-POST publish; it only refetches lists.
    expect(postCalls).toHaveLength(1)
  })
})
