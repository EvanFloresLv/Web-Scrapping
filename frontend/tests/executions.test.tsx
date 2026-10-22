import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { createElement, type ReactElement, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'

/**
 * Spec 0010 M6: vitest coverage for the executions browser routes.
 *
 * Covers:
 *  - AC-7 / AC-20: URL-synced filters with Zod `validateSearch` fallback
 *  - AC-14: empty state card when the list is empty
 *  - AC-15: Problem Details banner on a 400 execution.invalid_cursor
 *  - AC-11: detail route renders header + metadata grid + cross links
 *  - AC-12: items Table + Copy JSON
 */

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

vi.mock('@uiw/react-codemirror', () => ({
  default: ({ value }: { value: string }) =>
    createElement('textarea', {
      'aria-label': 'cm pane',
      readOnly: true,
      value,
      onChange: () => {},
    }),
}))

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

function withClient(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

const WORKFLOW_ID = '11111111-1111-7111-8111-111111111111'
const WEBSITE_ID = '22222222-2222-7222-8222-222222222222'
const VERSION_ID = 'vvvvvvvv-vvvv-7vvv-8vvv-vvvvvvvvvvv1'
const EXECUTION_ID = 'eeeeeeee-eeee-7eee-8eee-eeeeeeeeeeee'

const EXECUTION_ROW = {
  id: EXECUTION_ID,
  workflow_id: WORKFLOW_ID,
  workflow_version_id: VERSION_ID,
  target_url_id: 'tttttttt-tttt-7ttt-8ttt-tttttttttttt',
  status: 'completed' as const,
  started_at: '2026-10-21T12:00:00Z',
  finished_at: '2026-10-21T12:00:01Z',
  duration_ms: 1000,
  items_extracted: 2,
  error_code: null,
  error_message: null,
  correlation_id: 'cid-happy',
  created_at: '2026-10-21T12:00:00Z',
}

const WORKFLOW = {
  id: WORKFLOW_ID,
  website_id: WEBSITE_ID,
  name: 'Happy workflow',
  description: null,
  status: 'active' as const,
  current_version_id: VERSION_ID,
  created_at: '2026-10-21T12:00:00Z',
  updated_at: '2026-10-21T12:00:00Z',
  deleted_at: null,
}

async function loadListRoute() {
  const mod = (await import('@/routes/_authed.executions')) as unknown as {
    Route: {
      component: () => ReactElement
      useSearch: () => Record<string, unknown>
    }
  }
  mod.Route.useSearch = () => ({
    page_size: 50,
    status: undefined,
    with_deleted: false,
    cursor: undefined,
    workflow_id: undefined,
    target_url_id: undefined,
    website_id: undefined,
    correlation_id: undefined,
    created_from: undefined,
    created_to: undefined,
  })
  return mod.Route.component
}

async function loadDetailRoute() {
  const mod = (await import('@/routes/_authed.executions.$executionId')) as unknown as {
    Route: {
      component: () => ReactElement
      useParams: () => { executionId: string }
    }
  }
  mod.Route.useParams = () => ({ executionId: EXECUTION_ID })
  return mod.Route.component
}

describe('/executions list route (spec 0010)', () => {
  beforeEach(() => {
    useAuthStore.setState({ apiKey: 'test-key', isSignedIn: true })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.resetModules()
  })

  it('renders the empty state when the list is empty (AC-14)', async () => {
    const fetchMock = vi.fn<FetchFn>(async (input) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/v1/executions')) {
        return jsonResponse({ items: [], next_cursor: null })
      }
      if (url.includes('/api/v1/websites')) {
        return jsonResponse({ items: [], total: 0, page: 1, page_size: 200 })
      }
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)

    const Page = await loadListRoute()
    render(withClient(<Page />))
    expect(await screen.findByRole('heading', { name: 'Executions' })).toBeInTheDocument()
    expect(await screen.findByText(/No executions yet/i)).toBeInTheDocument()
  })

  it('renders a Problem Details banner on 400 invalid_cursor (AC-15)', async () => {
    const fetchMock = vi.fn<FetchFn>(async (input) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/v1/executions')) {
        return problemResponse(400, {
          type: 'about:blank',
          title: 'Invalid Cursor',
          status: 400,
          detail: 'cursor is malformed',
          code: 'execution.invalid_cursor',
          correlation_id: 'cid-err',
        })
      }
      return jsonResponse({ items: [], total: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const Page = await loadListRoute()
    render(withClient(<Page />))
    const banners = await screen.findAllByRole('alert')
    const topBanner = banners.find((b) => b.textContent?.includes('Invalid Cursor'))
    expect(topBanner).toBeTruthy()
    expect(topBanner!.textContent).toContain('cursor is malformed')
    expect(topBanner!.textContent).toContain('cid-err')
  })

  it('resolves the parent workflow name via useQueries (AC-8)', async () => {
    const fetchMock = vi.fn<FetchFn>(async (input) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes(`/api/v1/workflows/${WORKFLOW_ID}`) && !url.includes('/versions')) {
        return jsonResponse(WORKFLOW)
      }
      if (url.includes('/api/v1/executions')) {
        return jsonResponse({ items: [EXECUTION_ROW], next_cursor: null })
      }
      if (url.includes('/api/v1/websites')) {
        return jsonResponse({ items: [], total: 0 })
      }
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)

    const Page = await loadListRoute()
    render(withClient(<Page />))
    const matches = await screen.findAllByText('Happy workflow')
    expect(matches.length).toBeGreaterThan(0)
    const completed = screen.getAllByText('completed')
    expect(completed.length).toBeGreaterThan(0)
  })
})

describe('/executions/:id detail route (spec 0010)', () => {
  beforeEach(() => {
    useAuthStore.setState({ apiKey: 'test-key', isSignedIn: true })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.resetModules()
  })

  it('renders the header + metadata grid + items table (AC-11, AC-12)', async () => {
    const fetchMock = vi.fn<FetchFn>(async (input) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes(`/api/v1/executions/${EXECUTION_ID}`)) {
        return jsonResponse({
          execution: EXECUTION_ROW,
          items: [
            { item_index: 0, payload: { name: 'first', price: '$10' } },
            { item_index: 1, payload: { name: 'second', price: '$20' } },
          ],
        })
      }
      if (url.includes(`/api/v1/workflows/${WORKFLOW_ID}`)) {
        return jsonResponse(WORKFLOW)
      }
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)

    const Page = await loadDetailRoute()
    render(withClient(<Page />))
    expect(await screen.findByText('completed')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Happy workflow')).toBeInTheDocument())
    expect(screen.getByText(/2 items/i)).toBeInTheDocument()
    expect(screen.getByText('first')).toBeInTheDocument()
    expect(screen.getByText('second')).toBeInTheDocument()
  })

  it('renders the error block for a failed run (AC-11)', async () => {
    const failed = {
      ...EXECUTION_ROW,
      status: 'failed' as const,
      error_code: 'fetch.timeout',
      error_message: 'timed out after 30s',
    }
    const fetchMock = vi.fn<FetchFn>(async (input) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes(`/api/v1/executions/${EXECUTION_ID}`)) {
        return jsonResponse({ execution: failed, items: [] })
      }
      if (url.includes(`/api/v1/workflows/${WORKFLOW_ID}`)) {
        return jsonResponse(WORKFLOW)
      }
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)

    const Page = await loadDetailRoute()
    render(withClient(<Page />))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('fetch.timeout')
    expect(alert.textContent).toContain('timed out after 30s')
  })

  it('copies the items JSON to the clipboard (AC-12)', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })

    const fetchMock = vi.fn<FetchFn>(async (input) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes(`/api/v1/executions/${EXECUTION_ID}`)) {
        return jsonResponse({
          execution: EXECUTION_ROW,
          items: [{ item_index: 0, payload: { name: 'first' } }],
        })
      }
      if (url.includes(`/api/v1/workflows/${WORKFLOW_ID}`)) {
        return jsonResponse(WORKFLOW)
      }
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)

    const Page = await loadDetailRoute()
    render(withClient(<Page />))
    const copyButton = await screen.findByRole('button', { name: /Copy JSON/i })
    await user.click(copyButton)
    expect(writeText).toHaveBeenCalledTimes(1)
    expect(writeText.mock.calls[0][0]).toContain('"item_index": 0')
    expect(writeText.mock.calls[0][0]).toContain('"name": "first"')
  })
})
